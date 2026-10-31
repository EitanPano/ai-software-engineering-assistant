"""service.py belongs: every query for the `source`, `document` and `chunk` tables and nothing else,
private to this directory: only its `controller.py` imports it.
It does not belong: business rules, error mapping or events (`controller.py`).

A source's state changes are conditional updates (`where status = ...` returning the row), so
exactly one of two racing callers wins: a claim, a retry and a finish each name the state they
move from. The list pages by `(created_at, id)` newest first, like `api/user/service.py` but
descending. An embedding travels as text cast to `halfvec(1024)`; there is no Python vector type.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Final, LiteralString

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict

from app.models.source.enums import SourceErrorCode, SourceStatus
from app.models.source.interface import ChunkRecord, DocumentRecord, SourceRecord
from app.services.db import Executor, execute, fetch_all, fetch_one, get_db
from app.services.utils.pagination import Slice, decode_cursor, encode_cursor, to_page

# Constant text only: no value is ever formatted into a statement (values travel as parameters).
_COLUMNS: Final[LiteralString] = (
    "id, url, ref, status, error_code, indexed_commit, document_count, chunk_count, "
    "created_at, updated_at"
)
_SELECT: Final[LiteralString] = "select " + _COLUMNS + " from source "  # noqa: S608
_RETURNING: Final[LiteralString] = " returning " + _COLUMNS


@dataclass(frozen=True)
class _SourceRow:
    """The columns as stored; `_to_record` is the only place that maps them to the record."""

    id: str
    url: str
    ref: str
    status: str
    error_code: str | None
    indexed_commit: str | None
    document_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


def _to_record(row: _SourceRow) -> SourceRecord:
    return SourceRecord(
        id=row.id,
        url=row.url,
        ref=row.ref,
        status=SourceStatus(row.status),
        error_code=None if row.error_code is None else SourceErrorCode(row.error_code),
        indexed_commit=row.indexed_commit,
        document_count=row.document_count,
        chunk_count=row.chunk_count,
        created_at=row.created_at.astimezone(UTC),
        updated_at=row.updated_at.astimezone(UTC),
    )


_ISO: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T.+")


def _iso_text(value: object) -> object:
    if isinstance(value, str) and _ISO.fullmatch(value):
        return datetime.fromisoformat(value)
    raise ValueError("must be an ISO 8601 timestamp")


class SourceCursor(BaseModel):
    """The sort key of the source list: (created_at, id), newest first."""

    model_config = ConfigDict(strict=True)

    created_at: Annotated[AwareDatetime, BeforeValidator(_iso_text)]
    id: str


def _cursor_of(record: SourceRecord) -> str:
    return encode_cursor({"created_at": record.created_at.isoformat(), "id": record.id})


type Tx = Executor
"""The connection a transaction holds, named here so the controller never imports the db seam."""


async def with_transaction[T](work: Callable[[Executor], Awaitable[T]]) -> T:
    """Runs `work` in one transaction; the controller passes the handle to each query."""
    async with get_db() as connection, connection.transaction():
        return await work(connection)


async def insert_source(record: SourceRecord, *, db: Executor | None = None) -> SourceRecord:
    """A second source for one `(url, ref)` violates the unique index: the error handler maps
    it to a 409, so nothing here checks first."""
    row = await fetch_one(
        _SourceRow,
        "insert into source ("  # noqa: S608  # constant column text, values are parameters
        + _COLUMNS
        + ") values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        + _RETURNING,
        (
            record.id,
            record.url,
            record.ref,
            record.status,
            record.error_code,
            record.indexed_commit,
            record.document_count,
            record.chunk_count,
            record.created_at,
            record.updated_at,
        ),
        db=db,
    )
    if row is None:
        raise RuntimeError("source insert returned no row")
    return _to_record(row)


async def find_source(source_id: str, *, db: Executor | None = None) -> SourceRecord | None:
    row = await fetch_one(
        _SourceRow,
        _SELECT + "where id = %s",
        (source_id,),
        db=db,
    )
    return None if row is None else _to_record(row)


async def list_sources(
    *, cursor: str | None, limit: int, db: Executor | None = None
) -> Slice[SourceRecord]:
    after = None if cursor is None else decode_cursor(cursor, SourceCursor)
    if after is None:
        rows = await fetch_all(
            _SourceRow,
            _SELECT + "order by created_at desc, id desc limit %s",
            (limit + 1,),
            db=db,
        )
    else:
        rows = await fetch_all(
            _SourceRow,
            _SELECT
            + "where (created_at, id) < (%s, %s) order by created_at desc, id desc limit %s",
            (after.created_at, after.id, limit + 1),
            db=db,
        )
    return to_page([_to_record(row) for row in rows], limit, _cursor_of)


async def claim_source(
    source_id: str, now: datetime, *, db: Executor | None = None
) -> SourceRecord | None:
    """`queued` to `indexing`. `None` when the source is not queued (another indexer has it, or
    the boot sweep ended it): the caller must not index it."""
    row = await fetch_one(
        _SourceRow,
        "update source set status = 'indexing', error_code = null, updated_at = %s "  # noqa: S608
        "where id = %s and status = 'queued'" + _RETURNING,
        (now, source_id),
        db=db,
    )
    return None if row is None else _to_record(row)


async def requeue_failed(
    source_id: str, now: datetime, *, db: Executor | None = None
) -> SourceRecord | None:
    """`failed` to `queued`, clearing the reason. `None` when the source is not failed."""
    row = await fetch_one(
        _SourceRow,
        "update source set status = 'queued', error_code = null, updated_at = %s "  # noqa: S608
        "where id = %s and status = 'failed'" + _RETURNING,
        (now, source_id),
        db=db,
    )
    return None if row is None else _to_record(row)


async def clear_documents(source_id: str, *, db: Executor | None = None) -> int:
    """Deletes an earlier attempt's documents; their chunks go with them (the key cascades)."""
    return await execute("delete from document where source_id = %s", (source_id,), db=db)


async def insert_documents(
    documents: Sequence[DocumentRecord], *, db: Executor | None = None
) -> None:
    if not documents:
        return
    async with get_db(db) as connection, connection.cursor() as cursor:
        await cursor.executemany(
            "insert into document (id, source_id, path, language, created_at) "
            "values (%s, %s, %s, %s, %s)",
            [(d.id, d.source_id, d.path, d.language, d.created_at) for d in documents],
        )


def _vector_text(embedding: Sequence[float]) -> str:
    return "[" + ",".join(format(x, ".8g") for x in embedding) + "]"


async def insert_chunks(
    chunks: Sequence[ChunkRecord],
    embeddings: Sequence[Sequence[float]],
    *,
    db: Executor | None = None,
) -> None:
    """`embeddings[i]` is the vector of `chunks[i]`."""
    if len(chunks) != len(embeddings):
        raise ValueError("one embedding per chunk")
    if not chunks:
        return
    # Half a million `format` calls for a full batch: not on the event loop.
    rows = await asyncio.to_thread(_chunk_rows, chunks, embeddings)
    async with get_db(db) as connection, connection.cursor() as cursor:
        await cursor.executemany(
            "insert into chunk (id, document_id, symbol, start_line, end_line, content, "
            "embedding, created_at) values (%s, %s, %s, %s, %s, %s, %s::halfvec(1024), %s)",
            rows,
        )


def _chunk_rows(
    chunks: Sequence[ChunkRecord], embeddings: Sequence[Sequence[float]]
) -> list[tuple[object, ...]]:
    return [
        (
            c.id,
            c.document_id,
            c.symbol,
            c.start_line,
            c.end_line,
            c.content,
            _vector_text(embedding),
            c.created_at,
        )
        for c, embedding in zip(chunks, embeddings, strict=True)
    ]


async def finish_ready(
    source_id: str,
    commit: str,
    document_count: int,
    chunk_count: int,
    now: datetime,
    *,
    db: Executor | None = None,
) -> bool:
    """`indexing` to `ready` with the commit read and the counts. False when it was not indexing."""
    changed = await execute(
        "update source set status = 'ready', error_code = null, indexed_commit = %s, "
        "document_count = %s, chunk_count = %s, updated_at = %s "
        "where id = %s and status = 'indexing'",
        (commit, document_count, chunk_count, now, source_id),
        db=db,
    )
    return changed == 1


async def finish_failed(
    source_id: str, code: SourceErrorCode, now: datetime, *, db: Executor | None = None
) -> bool:
    """An active source to `failed`, with no document left: a failed index is never partial.
    The guarded update runs first and the documents go only when it matched: False, and nothing
    deleted, when the source was already finished (a `ready` source keeps its documents). Callers
    run it in a transaction (`with_transaction`), so the two statements commit together."""
    changed = await execute(
        "update source set status = 'failed', error_code = %s, document_count = 0, "
        "chunk_count = 0, updated_at = %s where id = %s and status in ('queued', 'indexing')",
        (code, now, source_id),
        db=db,
    )
    if changed != 1:
        return False
    await clear_documents(source_id, db=db)
    return True


async def list_active_sources_before(
    started_before: datetime, *, db: Executor | None = None
) -> list[SourceRecord]:
    """Sources still `queued` or `indexing` that were last touched before this process booted."""
    rows = await fetch_all(
        _SourceRow,
        _SELECT + "where status in ('queued', 'indexing') and updated_at < %s order by created_at",
        (started_before,),
        db=db,
    )
    return [_to_record(row) for row in rows]
