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

from app.api.conversation.controller import append_turns, read_history
from app.api.run.controller import append_run_event, finish_run, get_run, start_run
from app.config.constants import (
    AGENT_FLUSH_MS,
    AGENT_MAX_TURNS,
    AGENT_TOOL_OUTPUT_MAX_CHARS,
)
from app.models.conversation.type import NewTurn
from app.models.run.enums import RunErrorCode, RunEventType, RunStatus, ToolCallStatus
from app.models.run.interface import RunRecord
from app.services import tool
from app.services.anthropic import Block, ModelUnavailable, TurnResult, served_blocks, stream_turn
from app.services.logger import log

_DENIED_OUTPUT: Final = "this tool is not permitted"
_FAILED_OUTPUT: Final = "the tool failed"
_INVALID_INPUT_OUTPUT: Final = "invalid input"


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


async def _run_tool(name: str, raw: dict[str, object]) -> tuple[ToolCallStatus, str]:
    if tool.decide(name) == "deny":
        return ToolCallStatus.denied, _DENIED_OUTPUT
    registered = tool.get_tool(name)
    if registered is None:
        return ToolCallStatus.denied, _DENIED_OUTPUT
    try:
        parsed = tool.validate_input(registered, raw)
    except tool.InvalidToolInput as error:
        return ToolCallStatus.failed, str(error)
    try:
        output = await registered.run(parsed)
    except Exception as error:
        # The tool's own failure is logged; the model gets a fixed message, never its text.
        log.error("tool failed", {"tool": name}, error)
        return ToolCallStatus.failed, _FAILED_OUTPUT
    return ToolCallStatus.succeeded, output[:AGENT_TOOL_OUTPUT_MAX_CHARS]


async def _call_tool(run_id: str, block: Block) -> Block:
    """One `tool_use` block to its `tool_result` block, with the two events around it."""
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
    if isinstance(raw, dict):
        status, output = await _run_tool(name, arguments)
    else:
        status, output = ToolCallStatus.failed, _INVALID_INPUT_OUTPUT
    await append_run_event(
        run_id,
        RunEventType.tool_call_finished,
        {"toolUseId": tool_use_id, "status": status.value, "output": output},
    )
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": output,
        "is_error": status is not ToolCallStatus.succeeded,
    }


async def _model_call(run: RunRecord) -> TurnResult:
    history = await read_history(run.conversation_id)
    batcher = _DeltaBatcher(run.id)
    try:
        return await stream_turn(history, tool.definitions(), batcher.add)
    finally:
        await batcher.close()


async def _step(run: RunRecord) -> _Outcome | None:
    """One model call and what follows it; an outcome ends the run, `None` calls the model again."""
    result = await _model_call(run)
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
            return await _answer_tools(run, result)
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


async def _answer_tools(run: RunRecord, result: TurnResult) -> _Outcome | None:
    calls = [block for block in served_blocks(result.content) if block.get("type") == "tool_use"]
    if not calls:
        return _failed(RunErrorCode.internal)
    # Checked before any tool runs or any event is written: a `tool_use` input must be an object
    # (the API refuses the stored turn otherwise, and stored history is never edited, so it would
    # fail every later send). The turn is dropped and the run fails, with nothing left started.
    if any(not isinstance(call.get("input"), dict) for call in calls):
        log.error("tool input is not an object", {"runId": run.id})
        return _failed(RunErrorCode.internal)
    # Concurrent, and returned together in one user turn in the order the model asked.
    answers = await asyncio.gather(*(_call_tool(run.id, call) for call in calls))
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
    for _ in range(AGENT_MAX_TURNS):
        outcome = await _step(run)
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
