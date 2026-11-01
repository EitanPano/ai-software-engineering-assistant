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
from app.models.approval.enums import ApprovalDecision
from app.models.approval.interface import ApprovalCall, ApprovalRecord
from app.models.approval.type import DecidedApproval, HeldCall
from app.models.auth.type import Caller
from app.models.run.enums import RunErrorCode, RunEventType, RunStatus, ToolCallStatus
from app.models.run.interface import PendingTurn, RunEventRecord, RunRecord, ToolCallRecord
from app.services import tool
from app.services.logger import log
from app.services.security.crypto import constant_time_equals
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
        case RunStatus.awaiting_approval:
            return "awaiting_approval"
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
    """System operation: how many tool calls the run has recorded, denied and waiting ones
    included."""
    return await service.count_tool_calls(run_id)


async def pause_run(
    run: RunRecord,
    *,
    content: list[dict[str, object]],
    results: list[dict[str, object]],
    held: list[HeldCall],
) -> None:
    """System operation: stops a running run at `awaiting_approval`, in one transaction. A waiting
    `tool_call` and an `approval` for each held call (the digest is over the arguments as the store
    reads them back), an `approval_requested` event for each, the status and the pending turn
    (`content` is the assistant turn whole, `results` the answers already known). A crash leaves
    all of it or none, so a pause is never half written. No process waits afterwards."""
    pending = PendingTurn(content=content, results=results)
    async with _writer(run.id):

        async def work(db: service.Tx) -> None:
            now = clock.now()
            for call in held:
                call_id = str(uuid.uuid4())
                stored = await service.insert_waiting_call(
                    ToolCallRecord(
                        id=call_id,
                        run_id=run.id,
                        tool_use_id=call.tool_use_id,
                        mcp_server_id=call.mcp_server_id,
                        tool_name=call.tool_name,
                        arguments=call.arguments,
                        result="",
                        status=ToolCallStatus.awaiting_approval,
                        created_at=now,
                    ),
                    db=db,
                )
                approval = ApprovalRecord(
                    id=str(uuid.uuid4()),
                    run_id=run.id,
                    tool_call_id=call_id,
                    user_id=run.user_id,
                    arguments_digest=tool.arguments_digest(stored),
                    decision=None,
                    created_at=now,
                    decided_at=None,
                )
                await service.insert_approval(approval, db=db)
                await _append(
                    run.id,
                    RunEventType.approval_requested,
                    {
                        "approvalId": approval.id,
                        "toolUseId": call.tool_use_id,
                        "argumentsDigest": approval.arguments_digest,
                    },
                    db=db,
                )
            if not await service.mark_awaiting_approval(run.id, pending, now, db=db):
                raise RuntimeError("the run is not running")

        await service.with_transaction(work)
    _WRITERS.pop(run.id, None)


async def decide_tool_call(
    approval_id: str,
    *,
    decision: ApprovalDecision,
    arguments_digest: str,
    caller: Caller,
) -> DecidedApproval:
    """Records a person's decision on a waiting call. Another user's approval is a 404, an admin's
    included; a digest that is not the one the person was shown, a decision already made and a run
    that no longer waits are each a 409 that changes nothing. The decision, its `approval_decided`
    event and, for the last one, the flip back to `running` commit together; the run row is locked
    first, so two concurrent last decisions take turns and exactly one flips it."""
    found = await service.find_approval_call(approval_id)
    if found is None or found.approval.user_id != caller.id:
        raise AppError("not_found", "approval not found")
    approval = found.approval
    if not constant_time_equals(arguments_digest, approval.arguments_digest):
        raise AppError("conflict", "the arguments are not the ones that were shown")
    async with _writer(approval.run_id):

        async def work(db: service.Tx) -> DecidedApproval:
            if (
                await service.lock_run_status(approval.run_id, db=db)
                is not RunStatus.awaiting_approval
            ):
                raise AppError("conflict", "the run is not waiting for a decision")
            now = clock.now()
            if not await service.decide_approval(approval.id, decision, now, db=db):
                raise AppError("conflict", "the tool call was already decided")
            await _append(
                approval.run_id,
                RunEventType.approval_decided,
                {
                    "approvalId": approval.id,
                    "toolUseId": found.tool_use_id,
                    "decision": decision.value,
                },
                db=db,
            )
            resumes = await service.count_undecided(
                approval.run_id, db=db
            ) == 0 and await service.mark_running_again(approval.run_id, now, db=db)
            return DecidedApproval(
                id=approval.id,
                run_id=approval.run_id,
                tool_use_id=found.tool_use_id,
                decision=decision,
                decided_at=now,
                resumes=resumes,
            )

        return await service.with_transaction(work)


async def claim_pending_turn(run_id: str) -> PendingTurn | None:
    """System operation: takes what a paused run kept for its resume, once. None when the run is
    not running or the turn was already taken (a redelivery, or a run a sweep ended)."""
    return await service.claim_pending_turn(run_id)


async def list_approval_calls(run_id: str) -> list[ApprovalCall]:
    """System operation: every approval of the run, decided or not, rejected ones included, with
    the calls they bind, oldest first. Not a filter: the resume answers a rejection too."""
    return await service.list_approval_calls(run_id)


async def end_waiting_call(
    run_id: str, tool_use_id: str, status: ToolCallStatus, result: str
) -> bool:
    """System operation: ends a call that waited for a person with the text the model gets back;
    false when it had already ended."""
    return await service.finish_tool_call(run_id, tool_use_id, status, result)


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
    """The events after `Last-Event-ID`, in order and once each, polling until `run_finished` or
    until the run waits for a person's decision. Whether the run is at rest (finished, or at
    `awaiting_approval`) is read before the events are: the status commits with the last event it
    follows, so a run at rest has all its events visible by then.

    The stream ends cleanly after `AGENT_STREAM_MAX_SECONDS`, `run_finished` or not, so one open
    cannot hold the pool for long; the client reopens with `Last-Event-ID` and carries on."""
    cursor = 0 if last_event_id is None else last_event_id
    deadline = clock.now() + timedelta(seconds=AGENT_STREAM_MAX_SECONDS)
    while clock.now() < deadline:
        at_rest = await service.is_at_rest(run.id)
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
            if at_rest:
                return
            await asyncio.sleep(AGENT_POLL_MS / 1000)
