"""controller.py belongs: the agent loop. `agent` has no table, route or schema: it composes the
conversation module (the history and the stored turns), the run module (the events and the run's
end) and the model (`services/anthropic.py`) behind one system operation, `execute_run`.

The loop follows `.doc/conventions.md` (Claude API): it branches on `stop_reason` before it reads
the content, runs parallel tool calls concurrently and answers them in one user turn, validates
every tool input before it runs, and stores the assistant turn exactly as the API returned it. Every
exit writes one `run_finished`, after the turn's messages have committed.
It does not belong: gates or routes (there are none), queries (the modules' services).
"""

import asyncio
from dataclasses import dataclass
from typing import Final

from app.api.conversation.controller import append_turns, freeze_prefix, read_history
from app.api.mcp_server.controller import call_server_tool, discover_tools, find_server
from app.api.run.controller import (
    append_run_event,
    count_tool_calls,
    finish_run,
    get_run,
    record_tool_call,
    start_run,
)
from app.api.tool_policy.controller import find_effect
from app.config.constants import (
    AGENT_FLUSH_MS,
    AGENT_MAX_TURNS,
    AGENT_SYSTEM_PROMPT,
    AGENT_TOOL_CALLS_PER_RUN,
    AGENT_TOOL_OUTPUT_MAX_CHARS,
)
from app.models.conversation.type import ConversationPrefix, NewTurn
from app.models.mcp_server.interface import McpServerRecord
from app.models.run.enums import RunErrorCode, RunEventType, RunStatus, ToolCallStatus
from app.models.run.interface import RunRecord
from app.services import tool
from app.services.anthropic import Block, ModelUnavailable, TurnResult, served_blocks, stream_turn
from app.services.logger import log

_DENIED_OUTPUT: Final = "this tool is not permitted"
_INVALID_INPUT_OUTPUT: Final = "invalid input"
_BUDGET_OUTPUT: Final = "the tool call limit for this run is spent"


@dataclass(frozen=True)
class _Outcome:
    status: RunStatus
    error_code: RunErrorCode | None = None


_COMPLETED: Final = _Outcome(RunStatus.completed)


def _failed(code: RunErrorCode) -> _Outcome:
    return _Outcome(RunStatus.failed, code)


class _DeltaBatcher:
    """Joins the model's text deltas into one `text_delta` event per flush interval. A timer, not
    the next delta, flushes: a delta that is the last for a while still reaches the reader."""

    def __init__(self, run_id: str) -> None:
        self._run_id = run_id
        self._buffer: list[str] = []
        self._pending: asyncio.Task[None] | None = None

    async def add(self, text: str) -> None:
        self._buffer.append(text)
        if self._pending is None:
            self._pending = asyncio.create_task(self._flush_later())

    async def _flush_later(self) -> None:
        await asyncio.sleep(AGENT_FLUSH_MS / 1000)
        self._pending = None
        await self._flush()

    async def _flush(self) -> None:
        if not self._buffer:
            return
        text = "".join(self._buffer)
        self._buffer.clear()
        await append_run_event(self._run_id, RunEventType.text_delta, {"text": text})

    async def close(self) -> None:
        """Writes what is left; called when the model call ends, however it ends."""
        pending = self._pending
        if pending is not None:
            await pending
        await self._flush()


def _text_of(blocks: list[Block]) -> str:
    texts = [block.get("text") for block in blocks if block.get("type") == "text"]
    return "".join(text for text in texts if isinstance(text, str))


@dataclass(frozen=True)
class _Call:
    """How one tool call came out: the outcome, and whose it was. One rule for every path: when a
    server row owns the name (enabled or not), `server_id` is its id and `tool_name` the tool's own
    name; when none does, `server_id` is `None` and `tool_name` the name as the model used it."""

    status: ToolCallStatus
    output: str
    server_id: str | None
    tool_name: str


@dataclass(frozen=True)
class _Owner:
    server: McpServerRecord | None
    tool_name: str


async def _owner(name: str) -> _Owner:
    """Who owns the model's tool name, by the rule on `_Call`."""
    parts = tool.split_name(name)
    server = None if parts is None else await find_server(parts[0])
    if parts is None or server is None:
        return _Owner(None, name)
    return _Owner(server, parts[1])


def _ids(owner: _Owner) -> tuple[str | None, str]:
    """The `(mcp_server_id, tool_name)` a `tool_call` row stores for this owner."""
    return (None if owner.server is None else owner.server.id), owner.tool_name


def _denied(owner: _Owner, output: str = _DENIED_OUTPUT) -> _Call:
    return _Call(ToolCallStatus.denied, output, *_ids(owner))


async def _run_tool(name: str, raw: dict[str, object], prefix: ConversationPrefix) -> _Call:
    """Policy, then schema, then the server. A name no enabled server owns, a tool the model was
    not offered and a tool without an `allow` policy are denied and never reach a server."""
    owner = await _owner(name)
    server = owner.server
    if server is None or not server.enabled:
        return _denied(owner)
    tool_name = owner.tool_name
    effect = await find_effect(mcp_server_id=server.id, tool_name=tool_name)
    if tool.decide(effect) == "deny":
        return _denied(owner)
    definition = next((d for d in prefix.tool_definition if d.get("name") == name), None)
    schema = None if definition is None else definition.get("input_schema")
    if not isinstance(schema, dict):
        # Not offered to the model in this conversation: its prefix never named it.
        return _denied(owner)
    try:
        arguments = tool.validate_input(schema, raw)
    except tool.InvalidToolInput as error:
        return _Call(ToolCallStatus.failed, str(error), server.id, tool_name)
    outcome = await call_server_tool(server=server, tool_name=tool_name, arguments=arguments)
    return _Call(outcome.status, outcome.output[:AGENT_TOOL_OUTPUT_MAX_CHARS], server.id, tool_name)


async def _call_tool(
    run_id: str, block: Block, prefix: ConversationPrefix, *, allowed: bool
) -> Block:
    """One `tool_use` block to its `tool_result` block, with the two events around it and the
    `tool_call` row. A call past the run's budget is a fixed `is_error` result with no server
    call."""
    tool_use_id = str(block.get("id", ""))
    name = str(block.get("name", ""))
    raw = block.get("input")
    # An input that is not a JSON object (the streaming parser returns whatever it parsed) is
    # invalid, never an empty object: that would pass a schema whose fields are all optional.
    arguments = raw if isinstance(raw, dict) else {}
    await append_run_event(
        run_id,
        RunEventType.tool_call_started,
        {"toolUseId": tool_use_id, "name": name, "input": arguments},
    )
    if not allowed:
        call = _denied(await _owner(name), _BUDGET_OUTPUT)
    elif isinstance(raw, dict):
        call = await _run_tool(name, arguments, prefix)
    else:
        call = _Call(ToolCallStatus.failed, _INVALID_INPUT_OUTPUT, *_ids(await _owner(name)))
    await record_tool_call(
        run_id=run_id,
        tool_use_id=tool_use_id,
        mcp_server_id=call.server_id,
        tool_name=call.tool_name,
        arguments=arguments,
        result=call.output,
        status=call.status,
    )
    await append_run_event(
        run_id,
        RunEventType.tool_call_finished,
        {"toolUseId": tool_use_id, "status": call.status.value, "output": call.output},
    )
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": call.output,
        "is_error": call.status is not ToolCallStatus.succeeded,
    }


async def _prepare(run: RunRecord) -> ConversationPrefix:
    """Lists the servers (after `run_started`, so it still comes first), writes one
    `mcp_server_unavailable` for each that did not answer, and binds the conversation to its
    prompt and tools at its first run; a later run replays what is stored."""
    discovery = await discover_tools()
    for name in discovery.unavailable:
        await append_run_event(run.id, RunEventType.mcp_server_unavailable, {"name": name})
    return await freeze_prefix(
        run.conversation_id,
        system_prompt=AGENT_SYSTEM_PROMPT,
        tools=tool.definitions(discovery.listings),
    )


async def _model_call(run: RunRecord, prefix: ConversationPrefix) -> TurnResult:
    history = await read_history(run.conversation_id)
    batcher = _DeltaBatcher(run.id)
    try:
        return await stream_turn(
            history, prefix.tool_definition, batcher.add, system=prefix.system_prompt
        )
    finally:
        await batcher.close()


async def _step(run: RunRecord, prefix: ConversationPrefix) -> _Outcome | None:
    """One model call and what follows it; an outcome ends the run, `None` calls the model again."""
    result = await _model_call(run, prefix)
    log.info(
        "model turn",
        {"runId": run.id, "usage_in": result.input_tokens, "usage_out": result.output_tokens},
    )
    # `stop_reason` first: the content of a refusal or a cut-off turn is never acted on.
    match result.stop_reason:
        case "end_turn" | "stop_sequence":
            return await _store_answer(run, result, _COMPLETED)
        case "pause_turn":
            return await _store_answer(run, result, None)
        case "tool_use":
            return await _answer_tools(run, result, prefix)
        case "max_tokens" | "model_context_window_exceeded":
            return _failed(RunErrorCode.truncated)
        case "refusal":
            return _failed(RunErrorCode.refused)
        case _:
            log.error(
                "unexpected stop reason", {"runId": run.id, "reason": str(result.stop_reason)}
            )
            return _failed(RunErrorCode.internal)


async def _store_answer(
    run: RunRecord, result: TurnResult, then: _Outcome | None
) -> _Outcome | None:
    """Stores a finished assistant turn, then `then`. An empty turn is never stored: the API
    rejects an empty non-final message, and stored history is never edited, so one empty answer
    would fail every later send in the conversation."""
    if not result.content:
        log.error("empty model turn", {"runId": run.id, "reason": str(result.stop_reason)})
        return _failed(RunErrorCode.internal)
    await append_turns(run.conversation_id, run.id, [_assistant(result)])
    return then


def _assistant(result: TurnResult) -> NewTurn:
    return NewTurn(
        role="assistant",
        blocks=list(result.content),
        text=_text_of(served_blocks(result.content)),
    )


def _holds_nul(value: object) -> bool:
    """Whether an input has a NUL anywhere, in a key or a value: a JSONB column cannot store it."""
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_holds_nul(key) or _holds_nul(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_holds_nul(item) for item in value)
    return False


async def _answer_tools(
    run: RunRecord, result: TurnResult, prefix: ConversationPrefix
) -> _Outcome | None:
    calls = [block for block in served_blocks(result.content) if block.get("type") == "tool_use"]
    if not calls:
        return _failed(RunErrorCode.internal)
    # Checked before any tool runs or any event is written: a `tool_use` input must be an object
    # (the API refuses the stored turn otherwise, and stored history is never edited, so it would
    # fail every later send) and must hold no NUL (the `tool_call` row cannot store it). The turn
    # is dropped and the run fails, with nothing left started.
    if any(not isinstance(call.get("input"), dict) for call in calls):
        log.error("tool input is not an object", {"runId": run.id})
        return _failed(RunErrorCode.internal)
    if any(_holds_nul(call["input"]) for call in calls):
        log.error("tool input holds a NUL", {"runId": run.id})
        return _failed(RunErrorCode.internal)
    # The budget is spent here, before any call starts, from the rows already recorded: parallel
    # calls cannot race past it, and an approval's resume keeps the count.
    remaining = max(0, AGENT_TOOL_CALLS_PER_RUN - await count_tool_calls(run.id))
    # Concurrent, and returned together in one user turn in the order the model asked.
    answers = await asyncio.gather(
        *(
            _call_tool(run.id, call, prefix, allowed=position < remaining)
            for position, call in enumerate(calls)
        )
    )
    await append_turns(
        run.conversation_id,
        run.id,
        [
            _assistant(result),
            NewTurn(role="tool_result", blocks=list(answers), text=""),
        ],
    )
    return None


async def _drive(run: RunRecord) -> _Outcome:
    prefix = await _prepare(run)
    for _ in range(AGENT_MAX_TURNS):
        outcome = await _step(run, prefix)
        if outcome is not None:
            return outcome
    return _failed(RunErrorCode.turn_limit)


async def execute_run(run_id: str) -> None:
    """System operation: runs one queued run to its end. A run that is not queued (another
    executor has it, or the boot sweep ended it) is left alone. A cancellation (shutdown) writes
    nothing: the next boot's sweep ends the run as `interrupted`."""
    run = await get_run(run_id)
    if not await start_run(run.id):
        return
    try:
        outcome = await _drive(run)
    except ModelUnavailable as error:
        # Logged with its cause (`error.__cause__`, the SDK or transport error), so an operator can
        # tell an outage from a throttle; the run reports only `upstream_unavailable`.
        log.error("model unavailable", {"runId": run.id}, error)
        outcome = _failed(RunErrorCode.upstream_unavailable)
    except Exception as error:
        log.error("run failed", {"runId": run.id}, error)
        outcome = _failed(RunErrorCode.internal)
    await finish_run(run.id, outcome.status, outcome.error_code)
