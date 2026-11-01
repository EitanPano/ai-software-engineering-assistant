"""service.py belongs: every query for the `run` and `run_event` tables and nothing else, private to
this directory: only its `controller.py` imports it. Rows are plain records; the controller makes
the rules and the wire shapes.
It does not belong: business rules, error mapping or events (`controller.py`).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from app.models.approval.enums import ApprovalDecision
from app.models.approval.interface import ApprovalCall, ApprovalRecord
from app.models.run.enums import RunErrorCode, RunEventType, RunStatus, ToolCallStatus
from app.models.run.interface import PendingTurn, RunEventRecord, RunRecord, ToolCallRecord
from app.services.db import Executor, execute, fetch_all, fetch_one, get_db


@dataclass(frozen=True)
class _RunRow:
    id: str
    conversation_id: str
    user_id: str
    status: str
    error_code: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class _EventRow:
    run_id: str
    sequence: int
    type: str
    payload: dict[str, object]
    created_at: datetime


@dataclass(frozen=True)
class _Flag:
    found: bool


@dataclass(frozen=True)
class _Total:
    total: int


@dataclass(frozen=True)
class _StatusRow:
    status: str


@dataclass(frozen=True)
class _PendingRow:
    pending_turn: dict[str, object] | None


@dataclass(frozen=True)
class _ArgumentsRow:
    arguments: dict[str, object]


@dataclass(frozen=True)
class _ApprovalCallRow:
    id: str
    run_id: str
    tool_call_id: str
    user_id: str
    arguments_digest: str
    decision: str | None
    created_at: datetime
    decided_at: datetime | None
    tool_use_id: str
    mcp_server_id: str | None
    tool_name: str
    arguments: dict[str, object]


def _to_approval_call(row: _ApprovalCallRow) -> ApprovalCall:
    return ApprovalCall(
        approval=ApprovalRecord(
            id=row.id,
            run_id=row.run_id,
            tool_call_id=row.tool_call_id,
            user_id=row.user_id,
            arguments_digest=row.arguments_digest,
            decision=None if row.decision is None else ApprovalDecision(row.decision),
            created_at=row.created_at.astimezone(UTC),
            decided_at=None if row.decided_at is None else row.decided_at.astimezone(UTC),
        ),
        tool_use_id=row.tool_use_id,
        mcp_server_id=row.mcp_server_id,
        tool_name=row.tool_name,
        arguments=row.arguments,
    )


def _to_run(row: _RunRow) -> RunRecord:
    return RunRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        user_id=row.user_id,
        status=RunStatus(row.status),
        error_code=None if row.error_code is None else RunErrorCode(row.error_code),
        created_at=row.created_at.astimezone(UTC),
        updated_at=row.updated_at.astimezone(UTC),
    )


def _to_event(row: _EventRow) -> RunEventRecord:
    return RunEventRecord(
        run_id=row.run_id,
        sequence=row.sequence,
        type=RunEventType(row.type),
        payload=row.payload,
        created_at=row.created_at.astimezone(UTC),
    )


_RUN_COLUMNS = "id, conversation_id, user_id, status, error_code, created_at, updated_at"


type Tx = Executor
"""The connection a transaction holds, named here so the controller never imports the db seam."""


async def with_transaction[T](work: Callable[[Executor], Awaitable[T]]) -> T:
    """Runs `work` in one transaction; the controller passes the handle to each query."""
    async with get_db() as connection, connection.transaction():
        return await work(connection)


async def insert_run(record: RunRecord, *, db: Executor | None = None) -> RunRecord:
    """A second active run for the conversation is a unique violation, mapped to a 409."""
    row = await fetch_one(
        _RunRow,
        """
        insert into run (id, conversation_id, user_id, status, error_code, created_at, updated_at)
        values (%s, %s, %s, %s, %s, %s, %s)
        returning id, conversation_id, user_id, status, error_code, created_at, updated_at""",
        (
            record.id,
            record.conversation_id,
            record.user_id,
            record.status,
            record.error_code,
            record.created_at,
            record.updated_at,
        ),
        db=db,
    )
    if row is None:
        raise RuntimeError("run insert returned no row")
    return _to_run(row)


async def find_run(run_id: str, *, db: Executor | None = None) -> RunRecord | None:
    row = await fetch_one(
        _RunRow,
        "select id, conversation_id, user_id, status, error_code, created_at, updated_at "
        "from run where id = %s",
        (run_id,),
        db=db,
    )
    return None if row is None else _to_run(row)


async def find_owned_run(
    run_id: str, user_id: str, *, db: Executor | None = None
) -> RunRecord | None:
    row = await fetch_one(
        _RunRow,
        "select id, conversation_id, user_id, status, error_code, created_at, updated_at "
        "from run where id = %s and user_id = %s",
        (run_id, user_id),
        db=db,
    )
    return None if row is None else _to_run(row)


async def find_latest_run(conversation_id: str, *, db: Executor | None = None) -> RunRecord | None:
    row = await fetch_one(
        _RunRow,
        "select id, conversation_id, user_id, status, error_code, created_at, updated_at "
        "from run where conversation_id = %s order by created_at desc, id desc limit 1",
        (conversation_id,),
        db=db,
    )
    return None if row is None else _to_run(row)


async def mark_running(run_id: str, now: datetime, *, db: Executor | None = None) -> bool:
    row = await fetch_one(
        _Flag,
        "update run set status = 'running', updated_at = %s "
        "where id = %s and status = 'queued' returning true as found",
        (now, run_id),
        db=db,
    )
    return row is not None


async def finish_run(
    run_id: str,
    status: RunStatus,
    error_code: RunErrorCode | None,
    now: datetime,
    *,
    db: Executor | None = None,
) -> bool:
    """True when this call finished the run: only an active run changes, so exactly one caller
    wins and writes the `run_finished` event."""
    row = await fetch_one(
        _Flag,
        "update run set status = %s, error_code = %s, updated_at = %s "
        "where id = %s and status in ('queued', 'running') returning true as found",
        (status, error_code, now, run_id),
        db=db,
    )
    return row is not None


async def list_active_runs_before(
    before: datetime, *, db: Executor | None = None
) -> list[RunRecord]:
    rows = await fetch_all(
        _RunRow,
        "select id, conversation_id, user_id, status, error_code, created_at, updated_at "
        "from run where status in ('queued', 'running') and created_at < %s order by created_at",
        (before,),
        db=db,
    )
    return [_to_run(row) for row in rows]


async def insert_event(
    run_id: str,
    event_type: RunEventType,
    payload: dict[str, object],
    now: datetime,
    *,
    db: Executor | None = None,
) -> RunEventRecord:
    """The next sequence of the run (1, 2, ...). The controller's per-run writer serializes the
    callers; the primary key refuses a duplicate anyway."""
    row = await fetch_one(
        _EventRow,
        """
        insert into run_event (run_id, sequence, type, payload, created_at)
        select %s, coalesce(max(sequence), 0) + 1, %s, %s, %s from run_event where run_id = %s
        returning run_id, sequence, type, payload, created_at""",
        (run_id, event_type, Jsonb(payload), now, run_id),
        db=db,
    )
    if row is None:
        raise RuntimeError("run_event insert returned no row")
    return _to_event(row)


async def insert_tool_call(record: ToolCallRecord, *, db: Executor | None = None) -> None:
    """One row per call; the pair (run, `tool_use_id`) is the API's identity of it, so a repeat
    changes nothing."""
    await execute(
        """
        insert into tool_call
          (id, run_id, tool_use_id, mcp_server_id, tool_name, arguments, result, status, created_at)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (run_id, tool_use_id) do nothing""",
        (
            record.id,
            record.run_id,
            record.tool_use_id,
            record.mcp_server_id,
            record.tool_name,
            Jsonb(record.arguments),
            record.result,
            record.status,
            record.created_at,
        ),
        db=db,
    )


async def count_tool_calls(run_id: str, *, db: Executor | None = None) -> int:
    row = await fetch_one(
        _Total,
        "select count(*) as total from tool_call where run_id = %s",
        (run_id,),
        db=db,
    )
    return 0 if row is None else row.total


async def list_events_after(
    run_id: str, after: int, limit: int, *, db: Executor | None = None
) -> list[RunEventRecord]:
    rows = await fetch_all(
        _EventRow,
        "select run_id, sequence, type, payload, created_at from run_event "
        "where run_id = %s and sequence > %s order by sequence limit %s",
        (run_id, after, limit),
        db=db,
    )
    return [_to_event(row) for row in rows]


async def is_at_rest(run_id: str, *, db: Executor | None = None) -> bool:
    """Whether the run will write no event until something outside it acts: it ended, or it waits
    for a person's decision. A stream that has delivered its events then closes."""
    row = await fetch_one(
        _Flag,
        "select true as found from run where id = %s "
        "and status in ('completed', 'failed', 'awaiting_approval')",
        (run_id,),
        db=db,
    )
    return row is not None


async def lock_run_status(run_id: str, *, db: Executor) -> RunStatus | None:
    """The run's status, holding its row until the transaction ends: concurrent last decisions
    take turns, so exactly one sees nothing left undecided."""
    row = await fetch_one(
        _StatusRow, "select status from run where id = %s for update", (run_id,), db=db
    )
    return None if row is None else RunStatus(row.status)


async def mark_awaiting_approval(
    run_id: str, pending: PendingTurn, now: datetime, *, db: Executor
) -> bool:
    """Running to `awaiting_approval`, keeping the turn the resume appends."""
    row = await fetch_one(
        _Flag,
        "update run set status = 'awaiting_approval', pending_turn = %s, updated_at = %s "
        "where id = %s and status = 'running' returning true as found",
        (Jsonb({"content": pending.content, "results": pending.results}), now, run_id),
        db=db,
    )
    return row is not None


async def mark_running_again(run_id: str, now: datetime, *, db: Executor) -> bool:
    """The last decision: `awaiting_approval` to running. False when the run is not waiting."""
    row = await fetch_one(
        _Flag,
        "update run set status = 'running', updated_at = %s "
        "where id = %s and status = 'awaiting_approval' returning true as found",
        (now, run_id),
        db=db,
    )
    return row is not None


async def claim_pending_turn(run_id: str, *, db: Executor | None = None) -> PendingTurn | None:
    """Takes the turn a paused run kept, in one statement: only a running run that still holds one
    returns it, and it holds none afterwards, so a second delivery of the same flip, or a run a
    sweep ended, claims nothing."""
    row = await fetch_one(
        _PendingRow,
        # `returning` shows the row after the update, so the turn is read through a locking
        # subquery: a second claim waits for the first, then finds the column null.
        "with old as (select id, pending_turn from run where id = %s and status = 'running' "
        "and pending_turn is not null for update) "
        "update run set pending_turn = null from old where run.id = old.id "
        "returning old.pending_turn as pending_turn",
        (run_id,),
        db=db,
    )
    if row is None or row.pending_turn is None:
        return None
    content = row.pending_turn.get("content")
    results = row.pending_turn.get("results")
    if not isinstance(content, list) or not isinstance(results, list):
        # Claimed and unreadable: an empty turn, which the resume fails as `internal`, so the run
        # ends and is not left running with nothing to do.
        return PendingTurn(content=[], results=[])
    return PendingTurn(
        content=[block for block in content if isinstance(block, dict)],
        results=[block for block in results if isinstance(block, dict)],
    )


async def insert_waiting_call(record: ToolCallRecord, *, db: Executor) -> dict[str, object]:
    """A call that waits for a person; the arguments as the store reads them back, which is what
    the approval's digest is computed over."""
    row = await fetch_one(
        _ArgumentsRow,
        """
        insert into tool_call
          (id, run_id, tool_use_id, mcp_server_id, tool_name, arguments, result, status, created_at)
        values (%s, %s, %s, %s, %s, %s, '', 'awaiting_approval', %s)
        returning arguments""",
        (
            record.id,
            record.run_id,
            record.tool_use_id,
            record.mcp_server_id,
            record.tool_name,
            Jsonb(record.arguments),
            record.created_at,
        ),
        db=db,
    )
    if row is None:
        raise RuntimeError("tool_call insert returned no row")
    return row.arguments


async def finish_tool_call(
    run_id: str,
    tool_use_id: str,
    status: ToolCallStatus,
    result: str,
    *,
    db: Executor | None = None,
) -> bool:
    """Ends a waiting call: only a row still at `awaiting_approval` changes, so a call ends once.
    (`insert_tool_call` does nothing on a conflict, which would leave the row waiting.)"""
    row = await fetch_one(
        _Flag,
        "update tool_call set status = %s, result = %s "
        "where run_id = %s and tool_use_id = %s and status = 'awaiting_approval' "
        "returning true as found",
        (status, result, run_id, tool_use_id),
        db=db,
    )
    return row is not None


async def insert_approval(record: ApprovalRecord, *, db: Executor) -> None:
    await execute(
        "insert into approval (id, run_id, tool_call_id, user_id, arguments_digest, decision, "
        "created_at, decided_at) values (%s, %s, %s, %s, %s, null, %s, null)",
        (
            record.id,
            record.run_id,
            record.tool_call_id,
            record.user_id,
            record.arguments_digest,
            record.created_at,
        ),
        db=db,
    )


async def find_approval_call(
    approval_id: str, *, db: Executor | None = None
) -> ApprovalCall | None:
    row = await fetch_one(
        _ApprovalCallRow,
        """
        select a.id, a.run_id, a.tool_call_id, a.user_id, a.arguments_digest, a.decision,
               a.created_at, a.decided_at, c.tool_use_id, c.mcp_server_id, c.tool_name, c.arguments
        from approval a join tool_call c on c.id = a.tool_call_id where a.id = %s""",
        (approval_id,),
        db=db,
    )
    return None if row is None else _to_approval_call(row)


async def list_approval_calls(run_id: str, *, db: Executor | None = None) -> list[ApprovalCall]:
    rows = await fetch_all(
        _ApprovalCallRow,
        """
        select a.id, a.run_id, a.tool_call_id, a.user_id, a.arguments_digest, a.decision,
               a.created_at, a.decided_at, c.tool_use_id, c.mcp_server_id, c.tool_name, c.arguments
        from approval a join tool_call c on c.id = a.tool_call_id where c.run_id = %s
        order by a.created_at, a.id""",
        (run_id,),
        db=db,
    )
    return [_to_approval_call(row) for row in rows]


async def decide_approval(
    approval_id: str,
    decision: ApprovalDecision,
    now: datetime,
    *,
    db: Executor,
) -> bool:
    """Records the decision of an approval still undecided; false when it was already decided."""
    row = await fetch_one(
        _Flag,
        "update approval set decision = %s, decided_at = %s "
        "where id = %s and decision is null returning true as found",
        (decision, now, approval_id),
        db=db,
    )
    return row is not None


async def count_undecided(run_id: str, *, db: Executor) -> int:
    row = await fetch_one(
        _Total,
        "select count(*) as total from approval where run_id = %s and decision is null",
        (run_id,),
        db=db,
    )
    return 0 if row is None else row.total
