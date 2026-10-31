"""service.py belongs: every query for the `eval_case` and `eval_run` tables and nothing else,
private to this directory: only its `controller.py` imports it.
It does not belong: business rules, scoring, error mapping or events (`controller.py`).

A run's state changes are conditional updates (`where status = ...` returning the row or counting
it), so exactly one of two racing callers wins: a claim and each finish name the state they move
from. The list pages by `(created_at, id)` newest first and leaves the per-case results out of a
page. A run's JSONB columns hold the records of `models/eval/interface.py` in snake_case; a
`TypeAdapter` is the one place that maps between them. A partial unique index allows one active
run, so a second insert is a unique violation, which the error handler answers as a 409.
"""

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Final, LiteralString

from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, JsonValue, TypeAdapter

from app.models.eval.enums import EvalCaseKind, EvalRunErrorCode, EvalRunStatus
from app.models.eval.interface import (
    EvalCaseRecord,
    EvalCaseResultRecord,
    EvalCorpusRecord,
    EvalCosineRecord,
    EvalRunRecord,
    EvalScoreRecord,
    EvalSettingsRecord,
    ExpectedChunk,
)
from app.services.db import Executor, execute, fetch_all, fetch_one, get_db
from app.services.utils.pagination import Slice, decode_cursor, encode_cursor, to_page

type Tx = Executor
"""The connection a transaction holds, named here so the controller never imports the db seam."""

_SCORES: Final = TypeAdapter(tuple[EvalScoreRecord, ...])
_CASE_RESULTS: Final = TypeAdapter(tuple[EvalCaseResultRecord, ...])
_CORPUS: Final = TypeAdapter(tuple[EvalCorpusRecord, ...])
_SETTINGS: Final = TypeAdapter(EvalSettingsRecord)
_COSINE: Final = TypeAdapter(EvalCosineRecord)
_EXPECTED: Final = TypeAdapter(tuple[ExpectedChunk, ...])

# Constant text only: no value is ever formatted into a statement (values travel as parameters).
_RUN_COLUMNS: Final[LiteralString] = (
    "id, status, error_code, case_count, skipped_case_count, incomplete_case_count, scores, "
    "case_result, cosine, corpus, settings, created_at, updated_at"
)
# A page leaves the per-case results out: they are the large part of a row.
_PAGE_COLUMNS: Final[LiteralString] = (
    "id, status, error_code, case_count, skipped_case_count, incomplete_case_count, scores, "
    "'[]'::jsonb as case_result, cosine, corpus, settings, created_at, updated_at"
)
_SELECT_RUN: Final[LiteralString] = "select " + _RUN_COLUMNS + " from eval_run "  # noqa: S608
_SELECT_PAGE: Final[LiteralString] = "select " + _PAGE_COLUMNS + " from eval_run "  # noqa: S608
_RETURNING: Final[LiteralString] = " returning " + _RUN_COLUMNS
_CASE_COLUMNS: Final[LiteralString] = (
    "id, pinned_commit, kind, question, expected_chunk, created_at, updated_at"
)


@dataclass(frozen=True)
class _RunRow:
    """The columns as stored; `_to_run` is the only place that maps them to the record."""

    id: str
    status: str
    error_code: str | None
    case_count: int
    skipped_case_count: int
    incomplete_case_count: int
    scores: JsonValue
    case_result: JsonValue
    cosine: JsonValue
    corpus: JsonValue
    settings: JsonValue
    created_at: datetime
    updated_at: datetime


def _to_run(row: _RunRow) -> EvalRunRecord:
    return EvalRunRecord(
        id=row.id,
        status=EvalRunStatus(row.status),
        error_code=None if row.error_code is None else EvalRunErrorCode(row.error_code),
        case_count=row.case_count,
        skipped_case_count=row.skipped_case_count,
        incomplete_case_count=row.incomplete_case_count,
        scores=_SCORES.validate_python(row.scores),
        case_results=_CASE_RESULTS.validate_python(row.case_result),
        corpus=_CORPUS.validate_python(row.corpus),
        settings=None if row.settings is None else _SETTINGS.validate_python(row.settings),
        cosine=None if row.cosine is None else _COSINE.validate_python(row.cosine),
        created_at=row.created_at.astimezone(UTC),
        updated_at=row.updated_at.astimezone(UTC),
    )


@dataclass(frozen=True)
class _CaseRow:
    id: str
    pinned_commit: str
    kind: str
    question: str
    expected_chunk: JsonValue
    created_at: datetime
    updated_at: datetime


def _to_case(row: _CaseRow) -> EvalCaseRecord:
    return EvalCaseRecord(
        id=row.id,
        pinned_commit=row.pinned_commit,
        kind=EvalCaseKind(row.kind),
        question=row.question,
        expected_chunks=_EXPECTED.validate_python(row.expected_chunk),
        created_at=row.created_at.astimezone(UTC),
        updated_at=row.updated_at.astimezone(UTC),
    )


_ISO: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T.+")


def _iso_text(value: object) -> object:
    if isinstance(value, str) and _ISO.fullmatch(value):
        return datetime.fromisoformat(value)
    raise ValueError("must be an ISO 8601 timestamp")


class EvalRunCursor(BaseModel):
    """The sort key of the run list: (created_at, id), newest first."""

    model_config = ConfigDict(strict=True)

    created_at: Annotated[AwareDatetime, BeforeValidator(_iso_text)]
    id: str


def _cursor_of(record: EvalRunRecord) -> str:
    return encode_cursor({"created_at": record.created_at.isoformat(), "id": record.id})


async def with_transaction[T](work: Callable[[Executor], Awaitable[T]]) -> T:
    """Runs `work` in one transaction; the controller passes the handle to each query."""
    async with get_db() as connection, connection.transaction():
        return await work(connection)


async def insert_run(record: EvalRunRecord, *, db: Executor | None = None) -> EvalRunRecord:
    """A second active run violates the partial unique index: the error handler maps it to a 409,
    so nothing here checks first."""
    row = await fetch_one(
        _RunRow,
        "insert into eval_run (id, status, error_code, case_count, skipped_case_count, "  # noqa: S608
        "incomplete_case_count, created_at, updated_at) values (%s, %s, %s, %s, %s, %s, %s, %s)"
        + _RETURNING,
        (
            record.id,
            record.status,
            record.error_code,
            record.case_count,
            record.skipped_case_count,
            record.incomplete_case_count,
            record.created_at,
            record.updated_at,
        ),
        db=db,
    )
    if row is None:
        raise RuntimeError("eval run insert returned no row")
    return _to_run(row)


async def find_run(run_id: str, *, db: Executor | None = None) -> EvalRunRecord | None:
    row = await fetch_one(_RunRow, _SELECT_RUN + "where id = %s", (run_id,), db=db)
    return None if row is None else _to_run(row)


async def list_runs(
    *, cursor: str | None, limit: int, db: Executor | None = None
) -> Slice[EvalRunRecord]:
    after = None if cursor is None else decode_cursor(cursor, EvalRunCursor)
    if after is None:
        rows = await fetch_all(
            _RunRow,
            _SELECT_PAGE + "order by created_at desc, id desc limit %s",
            (limit + 1,),
            db=db,
        )
    else:
        rows = await fetch_all(
            _RunRow,
            _SELECT_PAGE
            + "where (created_at, id) < (%s, %s) order by created_at desc, id desc limit %s",
            (after.created_at, after.id, limit + 1),
            db=db,
        )
    return to_page([_to_run(row) for row in rows], limit, _cursor_of)


async def claim_run(run_id: str, now: datetime, *, db: Executor | None = None) -> bool:
    """`queued` to `running`. False when the run is not queued (another executor has it, or the
    boot sweep ended it): the caller must not run it."""
    changed = await execute(
        "update eval_run set status = 'running', error_code = null, updated_at = %s "
        "where id = %s and status = 'queued'",
        (now, run_id),
        db=db,
    )
    return changed == 1


async def record_start(
    run_id: str,
    *,
    case_count: int,
    skipped_case_count: int,
    corpus: Sequence[EvalCorpusRecord],
    settings: EvalSettingsRecord,
    now: datetime,
    db: Executor | None = None,
) -> bool:
    """What the run is about to measure: its counts, the sources it searches and the settings it
    searches with, written before the first embedding is spent."""
    changed = await execute(
        "update eval_run set case_count = %s, skipped_case_count = %s, corpus = %s, "
        "settings = %s, updated_at = %s where id = %s and status = 'running'",
        (
            case_count,
            skipped_case_count,
            Jsonb(_CORPUS.dump_python(tuple(corpus), mode="json")),
            Jsonb(_SETTINGS.dump_python(settings, mode="json")),
            now,
            run_id,
        ),
        db=db,
    )
    return changed == 1


async def finish_completed(
    run_id: str,
    *,
    incomplete_case_count: int,
    scores: Sequence[EvalScoreRecord],
    case_results: Sequence[EvalCaseResultRecord],
    cosine: EvalCosineRecord,
    now: datetime,
    db: Executor | None = None,
) -> bool:
    """`running` to `completed` with every result at once. False when it was not running."""
    changed = await execute(
        "update eval_run set status = 'completed', error_code = null, "
        "incomplete_case_count = %s, scores = %s, case_result = %s, cosine = %s, updated_at = %s "
        "where id = %s and status = 'running'",
        (
            incomplete_case_count,
            Jsonb(_SCORES.dump_python(tuple(scores), mode="json")),
            Jsonb(_CASE_RESULTS.dump_python(tuple(case_results), mode="json")),
            Jsonb(_COSINE.dump_python(cosine, mode="json")),
            now,
            run_id,
        ),
        db=db,
    )
    return changed == 1


async def finish_failed(
    run_id: str, code: EvalRunErrorCode, now: datetime, *, db: Executor | None = None
) -> bool:
    """An active run to `failed` with a reason and no scores. False when it was already over."""
    changed = await execute(
        "update eval_run set status = 'failed', error_code = %s, updated_at = %s "
        "where id = %s and status in ('queued', 'running')",
        (code, now, run_id),
        db=db,
    )
    return changed == 1


async def list_active_before(
    started_before: datetime, *, db: Executor | None = None
) -> list[EvalRunRecord]:
    """Runs still `queued` or `running` that were last touched before this process booted."""
    rows = await fetch_all(
        _RunRow,
        _SELECT_PAGE
        + "where status in ('queued', 'running') and updated_at < %s order by created_at",
        (started_before,),
        db=db,
    )
    return [_to_run(row) for row in rows]


async def list_cases(*, db: Executor | None = None) -> list[EvalCaseRecord]:
    """Every case, in the order a run takes them: by commit, kind, then question."""
    rows = await fetch_all(
        _CaseRow,
        "select "  # noqa: S608  # constant column text
        + _CASE_COLUMNS
        + " from eval_case order by pinned_commit, kind, question",
        db=db,
    )
    return [_to_case(row) for row in rows]


@dataclass(frozen=True)
class _Count:
    total: int


async def count_cases_outside(commit: str, *, db: Executor | None = None) -> int:
    """How many cases belong to a commit other than `commit`."""
    row = await fetch_one(
        _Count,
        "select count(*)::int as total from eval_case where pinned_commit <> %s",
        (commit,),
        db=db,
    )
    return 0 if row is None else row.total


async def upsert_case(record: EvalCaseRecord, *, db: Executor | None = None) -> None:
    """Inserts a case, or updates its kind and label when the commit already holds the question
    (the id and `created_at` stay), so two seeds of one file cannot collide."""
    await execute(
        "insert into eval_case (id, pinned_commit, kind, question, expected_chunk, created_at, "
        "updated_at) values (%s, %s, %s, %s, %s, %s, %s) "
        "on conflict (pinned_commit, question) do update set kind = excluded.kind, "
        "expected_chunk = excluded.expected_chunk, updated_at = excluded.updated_at",
        (
            record.id,
            record.pinned_commit,
            record.kind,
            record.question,
            Jsonb(_EXPECTED.dump_python(record.expected_chunks, mode="json")),
            record.created_at,
            record.updated_at,
        ),
        db=db,
    )


async def delete_cases_except(
    commit: str, questions: Sequence[str], *, db: Executor | None = None
) -> int:
    """Drops the commit's cases whose question is not in `questions`."""
    return await execute(
        "delete from eval_case where pinned_commit = %s and not (question = any(%s))",
        (commit, list(questions)),
        db=db,
    )
