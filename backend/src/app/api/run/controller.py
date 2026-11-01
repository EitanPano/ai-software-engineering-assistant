"""controller.py belongs: this directory's business logic and its HTTP handler, and the rules the
conversation and agent modules call (create, start, append to and finish a run; fail the runs a
process lost).
Authentication and ownership of the stream run as dependencies, because a generator's body runs
after the 200 is sent and a 404 raised there never reaches the client; the handler is annotated
`AsyncIterable[RunEvent]` with no `response_model`, so the item type reaches the contract.
It does not belong: gates (`routes.py`), queries (`service.py`) or schemas (`schema.py`).
"""

import asyncio
import uuid
from collections.abc import AsyncIterable
from datetime import datetime, timedelta
from typing import Annotated, Final, assert_never

from fastapi import Depends, Header, Request
from fastapi.sse import ServerSentEvent

from app.api.run import service
from app.api.run.schema import (
    EventSequence,
    Run,
    RunErrorCodeName,
    RunEvent,
    RunId,
    RunStatusName,
)
from app.config.constants import AGENT_POLL_MS, AGENT_STREAM_MAX_SECONDS, EVENT_BATCH_LIMIT
from app.middleware.auth import require_caller
from app.models.run.enums import RunErrorCode, RunEventType, RunStatus, ToolCallStatus
from app.models.run.interface import RunEventRecord, RunRecord, ToolCallRecord
from app.services.logger import log
from app.services.utils import clock
from app.services.utils.error import AppError

# One writer per run: events are allocated and committed in order, so a poller that has read
# sequence N never sees N-1 appear later. Parallel tool calls queue on it.
_WRITERS: Final[dict[str, asyncio.Lock]] = {}


def _writer(run_id: str) -> asyncio.Lock:
    lock = _WRITERS.get(run_id)
    if lock is None:
        lock = asyncio.Lock()
        _WRITERS[run_id] = lock
    return lock


def _wire_status(status: RunStatus) -> RunStatusName:
    """The edge between the domain enum and the wire's literal; `match` makes mypy fail here when
    a member is added to one and not the other."""
    match status:
        case RunStatus.queued:
            return "queued"
        case RunStatus.running:
            return "running"
        case RunStatus.completed:
            return "completed"
        case RunStatus.failed:
            return "failed"
        case _:
            assert_never(status)


def _wire_error(code: RunErrorCode | None) -> RunErrorCodeName | None:
    match code:
        case None:
            return None
        case RunErrorCode.refused:
            return "refused"
        case RunErrorCode.truncated:
            return "truncated"
        case RunErrorCode.turn_limit:
            return "turn_limit"
        case RunErrorCode.upstream_unavailable:
            return "upstream_unavailable"
        case RunErrorCode.interrupted:
            return "interrupted"
        case RunErrorCode.internal:
            return "internal"
        case _:
            assert_never(code)


def to_wire_run(record: RunRecord) -> Run:
    """The wire shape of a run; a rule the conversation module calls."""
    return Run(
        id=record.id,
        status=_wire_status(record.status),
        error_code=_wire_error(record.error_code),
        created_at=clock.to_iso(record.created_at),
    )


async def create_run(conversation_id: str, user_id: str) -> RunRecord:
    """A queued run. A second active run for the conversation is a 409 (the partial unique index
    on active runs, mapped by the error handler)."""
    now = clock.now()
    return await service.insert_run(
        RunRecord(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            user_id=user_id,
            status=RunStatus.queued,
            error_code=None,
            created_at=now,
            updated_at=now,
        )
    )


async def get_latest_run(conversation_id: str) -> RunRecord | None:
    return await service.find_latest_run(conversation_id)


async def get_run(run_id: str) -> RunRecord:
    """System operation: the run an agent executes, with no caller."""
    record = await service.find_run(run_id)
    if record is None:
        raise AppError("not_found", "run not found")
    return record


async def _append(
    run_id: str,
    event_type: RunEventType,
    payload: dict[str, object],
    *,
    db: service.Tx | None = None,
) -> RunEventRecord:
    return await service.insert_event(run_id, event_type, payload, clock.now(), db=db)


async def append_run_event(
    run_id: str, event_type: RunEventType, payload: dict[str, object]
) -> RunEventRecord:
    """Appends one event through the run's writer."""
    async with _writer(run_id):
        return await _append(run_id, event_type, payload)


async def record_tool_call(
    *,
    run_id: str,
    tool_use_id: str,
    mcp_server_id: str | None,
    tool_name: str,
    arguments: dict[str, object],
    result: str,
    status: ToolCallStatus,
) -> None:
    """System operation: stores one tool call of a run with its arguments, the text the model got
    back and how it ended. The loop counts these rows to hold a run's budget."""
    await service.insert_tool_call(
        ToolCallRecord(
            id=str(uuid.uuid4()),
            run_id=run_id,
            tool_use_id=tool_use_id,
            mcp_server_id=mcp_server_id,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            status=status,
            created_at=clock.now(),
        )
    )


async def count_tool_calls(run_id: str) -> int:
    """System operation: how many tool calls the run has recorded, denied ones included."""
    return await service.count_tool_calls(run_id)


async def start_run(run_id: str) -> bool:
    """Queued to running, with `run_started`. False when the run is not queued (already running,
    or finished by the boot sweep): the caller must not execute it."""
    async with _writer(run_id):

        async def work(db: service.Tx) -> bool:
            if not await service.mark_running(run_id, clock.now(), db=db):
                return False
            await _append(run_id, RunEventType.run_started, {}, db=db)
            return True

        return await service.with_transaction(work)


async def finish_run(run_id: str, status: RunStatus, error_code: RunErrorCode | None) -> bool:
    """Ends an active run and writes its one `run_finished`, together. False when it was already
    finished, so a second exit never writes a second event."""
    async with _writer(run_id):

        async def work(db: service.Tx) -> bool:
            if not await service.finish_run(run_id, status, error_code, clock.now(), db=db):
                return False
            await _append(
                run_id,
                RunEventType.run_finished,
                {
                    "status": status.value,
                    "errorCode": None if error_code is None else error_code.value,
                },
                db=db,
            )
            return True

        finished = await service.with_transaction(work)
    _WRITERS.pop(run_id, None)
    return finished


async def fail_lost_runs(started_before: datetime) -> int:
    """System operation: the boot sweep. Runs still active that started before this process did
    belong to a process that is gone; each ends as `interrupted`, with its `run_finished`, so a
    stream a client holds open closes."""
    failed = 0
    for record in await service.list_active_runs_before(started_before):
        if await finish_run(record.id, RunStatus.failed, RunErrorCode.interrupted):
            failed += 1
    if failed:
        log.warning("failed lost runs", {"count": failed})
    return failed


def to_wire_event(record: RunEventRecord) -> RunEvent:
    return RunEvent.model_validate(
        {
            "type": record.type.value,
            "sequence": record.sequence,
            "createdAt": clock.to_iso(record.created_at),
            **record.payload,
        }
    )


async def _owned_run(request: Request, run_id: RunId) -> RunRecord:
    caller = require_caller(request)
    record = await service.find_owned_run(run_id, caller.id)
    if record is None:
        raise AppError("not_found", "run not found")
    return record


async def stream_run_event(
    run: Annotated[RunRecord, Depends(_owned_run)],
    last_event_id: Annotated[EventSequence | None, Header(alias="Last-Event-ID")] = None,
) -> AsyncIterable[RunEvent]:
    """The events after `Last-Event-ID`, in order and once each, polling until `run_finished`.
    Whether the run is finished is read before the events are: the status and `run_finished`
    commit together, so a finished run's events are all visible by then.

    The stream ends cleanly after `AGENT_STREAM_MAX_SECONDS`, `run_finished` or not, so one open
    cannot hold the pool for long; the client reopens with `Last-Event-ID` and carries on."""
    cursor = 0 if last_event_id is None else last_event_id
    deadline = clock.now() + timedelta(seconds=AGENT_STREAM_MAX_SECONDS)
    while clock.now() < deadline:
        finished = await service.is_finished(run.id)
        events = await service.list_events_after(run.id, cursor, EVENT_BATCH_LIMIT)
        for record in events:
            cursor = record.sequence
            wire = to_wire_event(record)
            yield ServerSentEvent(  # type: ignore[misc]  # the SSE frame carries the id
                raw_data=wire.model_dump_json(by_alias=True), id=str(record.sequence)
            )
            if record.type is RunEventType.run_finished:
                return
        if not events:
            if finished:
                return
            await asyncio.sleep(AGENT_POLL_MS / 1000)
