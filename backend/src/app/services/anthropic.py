"""The Anthropic SDK wrapper: the only importer of `anthropic`. It builds one request, streams the
answer's text to a callback and returns the stop reason, the usage and the content blocks as JSON.
It is not a `Resource`: readiness never depends on Anthropic, and an outage fails the runs that need
it, not the server.

The request follows `.doc/conventions.md` (Claude API): the model comes from `LLM_MODEL`,
`thinking` is adaptive with an erroring block binding, `effort` is explicit, there are no
sampling parameters and no forced `tool_choice`, the server-side `fallbacks` parameter is sent on
a run's stream (`parse_turn`'s side call sends none: a refused side call only stores nothing), and a
top-level `cache_control` caches the prefix.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Final, Literal, cast

import anthropic
import httpx2
from anthropic import AsyncAnthropic, transform_schema
from anthropic.types.beta import BetaMessage, BetaMessageParam, BetaToolUnionParam
from pydantic import BaseModel, ValidationError

from app.config.constants import AGENT_EFFORT, AGENT_MAX_TOKENS, SIDE_CALL
from app.config.env import env
from app.models.conversation.type import HistoryTurn
from app.services.logger import log

FALLBACK_BETA: Final = "server-side-fallback-2026-07-01"
BINDING_BETA: Final = "thinking-binding-controls-2026-08-01"

type Block = dict[str, object]


class ModelUnavailable(Exception):  # noqa: N818  # named for what the run reports
    """The model API could not be reached or is overloaded or throttling: safe to retry later."""


class InvalidModelOutput(Exception):  # noqa: N818  # named for what the model produced
    """The stream carried something the SDK could not read (a tool input that is not JSON). It has
    no message and no cause: the SDK's own text holds the raw input, which must reach no log."""


class SideCallFailed(Exception):  # noqa: N818  # named for what the caller reports
    """A side call produced no usable answer. No message and no cause: the model's text and the
    SDK's validation error hold the person's words, which must reach no log."""


class SideCallRefused(SideCallFailed):
    """The model declined (`stop_reason: refusal`). Not retried."""


class SideCallCutOff(SideCallFailed):
    """The answer stopped at a limit (`max_tokens`, the context window). Not retried."""


class SideCallInvalid(SideCallFailed):
    """The served text was not the requested shape, twice."""


@dataclass(frozen=True)
class TurnResult:
    stop_reason: str | None
    content: list[Block]
    input_tokens: int
    output_tokens: int


_state: dict[str, AsyncAnthropic] = {}


def _client() -> AsyncAnthropic:
    client = _state.get("client")
    if client is None:
        client = AsyncAnthropic(api_key=env.anthropic_api_key, base_url=env.anthropic_base_url)
        _state["client"] = client
    return client


def use_client(client: AsyncAnthropic | None) -> None:
    """Replaces the client (a test points it at the scripted fake); `None` forgets it."""
    if client is None:
        _state.pop("client", None)
    else:
        _state["client"] = client


_TRANSIENT_ERRORS: Final = frozenset({"overloaded_error", "api_error", "rate_limit_error"})


def _error_type(body: object) -> str | None:
    """The `type` of an API error body, whether it is the envelope or the error inside it."""
    if not isinstance(body, dict):
        return None
    inner = body.get("error")
    candidate = inner.get("type") if isinstance(inner, dict) else body.get("type")
    return candidate if isinstance(candidate, str) else None


def _is_fallback(block: Block) -> bool:
    return block.get("type") == "fallback"


def echo_blocks(content: Sequence[object]) -> list[object]:
    """The blocks to send back for an assistant turn, by the API's "Continuing the conversation"
    (refusals and fallback): from the final `fallback` block on, everything as stored; before it,
    only `text` and `fallback` blocks, in order (each `fallback` stays where it appeared, because
    the API validates the thinking blocks around it by position). `thinking`, `redacted_thinking`
    and a client-side `tool_use` before it are dropped; the `tool_use` has no `tool_result`, as
    tools run only from `served_blocks`. The page's paired `server_tool_use` case cannot arise: no
    server tool is sent. A block of a type this code does not know before the boundary is dropped
    as model-internal. A turn without a `fallback` block is echoed unchanged."""
    last = max(
        (i for i, block in enumerate(content) if isinstance(block, dict) and _is_fallback(block)),
        default=-1,
    )
    if last < 0:
        return list(content)
    kept_before = [
        block
        for block in content[:last]
        if isinstance(block, dict) and block.get("type") in {"text", "fallback"}
    ]
    return [*kept_before, *content[last:]]


def served_blocks(content: Sequence[Block]) -> list[Block]:
    """The blocks the serving model wrote: those after the last `fallback` block. Tools run only
    from these."""
    last = max((i for i, block in enumerate(content) if _is_fallback(block)), default=-1)
    return list(content[last + 1 :])


def _messages(history: Sequence[HistoryTurn]) -> list[BetaMessageParam]:
    turns = [
        {
            "role": turn.role,
            "content": echo_blocks(turn.content) if turn.role == "assistant" else turn.content,
        }
        for turn in history
    ]
    return cast("list[BetaMessageParam]", turns)


@asynccontextmanager
async def _unavailable_as_error() -> AsyncIterator[None]:
    """The transport chain of every model call: connection failures, timeouts, throttling and
    server errors surface as `ModelUnavailable`; anything else (a rejected request) propagates."""
    try:
        yield
    except (
        # The SDK wraps transport errors only around the send; one raised while the body is read
        # arrives raw.
        httpx2.TransportError,
        anthropic.APIConnectionError,
        anthropic.RateLimitError,
        anthropic.InternalServerError,
    ) as error:
        # Chained for the server log; the run reports only `upstream_unavailable`.
        raise ModelUnavailable from error
    except anthropic.APIStatusError as error:
        # A 529, or an `error` event in the middle of a stream (the response status is 200 then).
        if error.status_code >= 500 or _error_type(error.body) in _TRANSIENT_ERRORS:
            raise ModelUnavailable from error
        raise


def _served_text(message: BetaMessage) -> str:
    """The text the serving model wrote: the `text` blocks after the last `fallback` block."""
    blocks: list[Block] = [block.to_dict() for block in message.content]
    texts = [block.get("text") for block in served_blocks(blocks) if block.get("type") == "text"]
    return "".join(text for text in texts if isinstance(text, str))


async def _side_call(
    output_type: type[BaseModel], *, system: str, content: str, model: str, effort: str
) -> str:
    """One non-streaming call; returns the served text of an answer that ended normally."""
    format_schema = transform_schema(output_type)
    async with _unavailable_as_error():
        message = await _client().beta.messages.create(
            model=model,
            max_tokens=SIDE_CALL.max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            # No `thinking` (the model's default applies), no `cache_control` (the prefix is under
            # the minimum), and never `fallbacks`: a refused side call only stores nothing.
            output_config={
                "effort": cast("Literal['low', 'medium', 'high']", effort),
                "format": {"type": "json_schema", "schema": format_schema},
            },
            timeout=SIDE_CALL.timeout_seconds,
        )
    usage = message.usage
    log.info(
        "side call",
        {
            "model": model,
            "usage_in": usage.input_tokens,
            "usage_out": usage.output_tokens,
            "cache_write": usage.cache_creation_input_tokens or 0,
            "cache_read": usage.cache_read_input_tokens or 0,
        },
    )
    # `stop_reason` before any text: a refused or cut-off answer is never read.
    match message.stop_reason:
        case "end_turn" | "stop_sequence":
            return _served_text(message)
        case "max_tokens" | "model_context_window_exceeded":
            raise SideCallCutOff
        case _:
            raise SideCallRefused


async def parse_turn[T: BaseModel](
    output_type: type[T], *, system: str, content: str, model: str, effort: str
) -> T:
    """One non-streaming side call beside a run (memory extraction): `content` is the one user
    message, `output_type` a Pydantic type the API is asked to produce through
    `output_config.format` (the SDK's public `transform_schema` makes its schema acceptable), and
    the result is validated here from the served text. Not `.parse()`: that validates every text
    block inside the response parser, so a cut-off answer, or text before a `fallback` block,
    would raise before `stop_reason` could be read, with the model's raw text in the error.

    Nothing is written to `message`, no `block_binding` is sent and the log carries usage only.
    A text that fails validation is asked for once more, then `SideCallInvalid`; a refusal or a cut
    off is `SideCallRefused` or `SideCallCutOff`, not retried; transport failures are
    `ModelUnavailable`. The errors carry no text and no cause."""
    for attempt in (1, 2):
        text = await _side_call(
            output_type, system=system, content=content, model=model, effort=effort
        )
        try:
            return output_type.model_validate_json(text)
        except ValidationError:
            if attempt == 2:
                raise SideCallInvalid from None
    raise SideCallInvalid


async def count_tokens(tools: Sequence[dict[str, object]], *, system: str) -> int:
    """The input tokens of `system` and `tools` alone, from the free token-counting endpoint (no
    model turn is billed). `tests/live_github.py` uses it to see whether the API accepts a tool
    list as built. A rejected request propagates as the SDK's error."""
    counted = await _client().beta.messages.count_tokens(
        model=env.llm_model,
        system=system,
        messages=[{"role": "user", "content": "x"}],
        tools=cast("list[BetaToolUnionParam]", list(tools)),
        betas=[FALLBACK_BETA, BINDING_BETA],
    )
    return counted.input_tokens


async def stream_turn(
    history: Sequence[HistoryTurn],
    tools: Sequence[dict[str, object]],
    on_text: Callable[[str], Awaitable[None]],
    *,
    system: str,
) -> TurnResult:
    """One model call. `system` and `tools` are the conversation's frozen prefix
    (`api/conversation/`), sent as they are: a thinking block is bound to them, and
    `prefix_mismatch_behavior: "error"` makes an edit loud on any account instead of passing on one
    that does not enforce the binding. `on_text` receives each text delta as it arrives.
    Connection failures, timeouts, throttling and server errors surface as `ModelUnavailable`;
    anything else (a rejected request) propagates and the run ends as `internal`."""
    try:
        async with (
            _unavailable_as_error(),
            _client().beta.messages.stream(
                model=env.llm_model,
                max_tokens=AGENT_MAX_TOKENS,
                system=system,
                messages=_messages(history),
                tools=cast("list[BetaToolUnionParam]", list(tools)) if tools else anthropic.omit,
                thinking={
                    "type": "adaptive",
                    "block_binding": {"prefix_mismatch_behavior": "error"},
                },
                output_config={"effort": AGENT_EFFORT},
                cache_control={"type": "ephemeral"},
                fallbacks="default",
                betas=[FALLBACK_BETA, BINDING_BETA],
            ) as stream,
        ):
            async for text in stream.text_stream:
                await on_text(text)
            message = await stream.get_final_message()
    except ValueError:
        # The SDK's message for a tool input that is not JSON holds the raw input (a search query),
        # which no log may carry: nothing of it is chained.
        raise InvalidModelOutput from None
    content: list[Block] = [
        # A `tool_use` input that is not an object makes the serializer warn (an error under the
        # test configuration); it is kept as the model sent it and the loop fails the run on it
        # (`api/agent/controller.py`, `_answer_tools`). Every other block keeps its warnings.
        block.to_dict(warnings=block.type != "tool_use")
        for block in message.content
    ]
    return TurnResult(
        stop_reason=message.stop_reason,
        content=content,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
    )
