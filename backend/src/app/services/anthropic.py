"""The Anthropic SDK wrapper: the only importer of `anthropic`. It builds one request, streams the
answer's text to a callback and returns the stop reason, the usage and the content blocks as JSON.
It is not a `Resource`: readiness never depends on Anthropic, and an outage fails the runs that need
it, not the server.

The request follows `.doc/conventions.md` (Claude API): the model comes from `LLM_MODEL`,
`thinking` is adaptive with an erroring block binding, `effort` is explicit, there are no
sampling parameters and no forced `tool_choice`, the server-side `fallbacks` parameter is sent,
and a top-level `cache_control` caches the prefix.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final, cast

import anthropic
import httpx2
from anthropic import AsyncAnthropic
from anthropic.types.beta import BetaMessageParam, BetaToolUnionParam

from app.config.constants import AGENT_EFFORT, AGENT_MAX_TOKENS
from app.config.env import env
from app.models.conversation.type import HistoryTurn

FALLBACK_BETA: Final = "server-side-fallback-2026-07-01"
BINDING_BETA: Final = "thinking-binding-controls-2026-08-01"

type Block = dict[str, object]


class ModelUnavailable(Exception):  # noqa: N818  # named for what the run reports
    """The model API could not be reached or is overloaded or throttling: safe to retry later."""


class InvalidModelOutput(Exception):  # noqa: N818  # named for what the model produced
    """The stream carried something the SDK could not read (a tool input that is not JSON). It has
    no message and no cause: the SDK's own text holds the raw input, which must reach no log."""


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
        async with _client().beta.messages.stream(
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
        ) as stream:
            async for text in stream.text_stream:
                await on_text(text)
            message = await stream.get_final_message()
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
    except ValueError:
        # The SDK's message for a tool input that is not JSON holds the raw input (a search query),
        # which no log may carry: nothing of it is chained.
        raise InvalidModelOutput from None
    except anthropic.APIStatusError as error:
        # A 529, or an `error` event in the middle of a stream (the response status is 200 then).
        if error.status_code >= 500 or _error_type(error.body) in _TRANSIENT_ERRORS:
            raise ModelUnavailable from error
        raise
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
