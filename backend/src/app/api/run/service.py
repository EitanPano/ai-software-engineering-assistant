"""service.py belongs: every query for the `run` and `run_event` tables and nothing else, private to
this directory: only its `controller.py` imports it. Rows are plain records; the controller makes
the rules and the wire shapes.
It does not belong: business rules, error mapping or events (`controller.py`).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from app.models.run.enums import RunErrorCode, RunEventType, RunStatus
from app.models.run.interface import RunEventRecord, RunRecord
from app.services.db import Executor, fetch_all, fetch_one, get_db


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


async def is_finished(run_id: str, *, db: Executor | None = None) -> bool:
    row = await fetch_one(
        _Flag,
        "select true as found from run where id = %s and status in ('completed', 'failed')",
        (run_id,),
        db=db,
    )
    return row is not None
