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

from app.config.constants import SEARCH
from app.models.search.interface import SearchCounts, SearchHitRecord
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


async def refresh_statistics(*, db: Executor | None = None) -> None:
    """`analyze` the three tables. A small table never reaches autovacuum's threshold (50
    changes), so `source` keeps no statistics and the planner reads every chunk through the
    document index to find the `ready` ones. Measured at the ceiling: 453 ms."""
    await execute("analyze source, document, chunk", db=db)


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


async def prepare_search(*, db: Executor) -> None:
    """The settings one search needs, for the transaction `db` holds (`set_config(..., true)` is
    `set local`). `strict_order` makes the HNSW scan go on past its first candidates when the
    filter to `ready` sources drops them, up to `max_scan_tuples`; the default scan returned
    nothing when in-flight chunks were nearest. The trigram threshold is 0.9: an exact identifier
    scores 1.0, a typo 0.82 and unrelated words 0.67. `statement_timeout` bounds every later
    statement of the transaction: the search holds a pooled connection, and Postgres tests `<%` on
    every trigram candidate before the filter to `ready` sources, so a common token could hold it
    for seconds; the cancelled statement is a 57014, which the error handler answers as 503."""
    await execute(
        "select set_config('hnsw.iterative_scan', 'strict_order', true), "
        "set_config('hnsw.max_scan_tuples', %s, true), "
        "set_config('pg_trgm.word_similarity_threshold', %s, true), "
        "set_config('statement_timeout', %s, true)",
        (
            str(SEARCH.max_scan_tuples),
            str(SEARCH.trigram_threshold),
            str(SEARCH.statement_timeout_ms),
        ),
        db=db,
    )


@dataclass(frozen=True)
class _CountRow:
    total: int


async def count_ready_chunks(*, db: Executor | None = None) -> int:
    """How many chunks the `ready` sources hold: the sum of their `chunk_count`."""
    row = await fetch_one(
        _CountRow,
        "select coalesce(sum(chunk_count), 0)::bigint as total from source where status = 'ready'",
        db=db,
    )
    return 0 if row is None else row.total


@dataclass(frozen=True)
class _SearchRow:
    """One row of the search: the counts of all three searches on every row, and the hit's columns,
    which are all null on the single row a search with no hit returns."""

    semantic_found: int
    full_text_found: int
    trigram_found: int
    chunk_id: str | None
    source_id: str | None
    url: str | None
    ref: str | None
    path: str | None
    symbol: str | None
    start_line: int | None
    end_line: int | None
    content: str | None
    score: float | None
    semantic_rank: int | None
    full_text_rank: int | None
    trigram_rank: int | None


# Only chunks of `ready` sources can be a hit: a source still indexing has its chunks stored but
# is not searchable until it finishes. The filter is a semi-join the planner applies after the HNSW
# scan; `prepare_search` makes the scan go on until enough survive it.
_READY: Final[LiteralString] = (
    "c.document_id in (select d.id from document d join source s on s.id = d.source_id "
    "where s.status = 'ready')"
)

# Three ranked searches, each reporting how many chunks it found, fused by RRF in this one
# statement. Placeholders in order: the query vector twice and the candidate cap (semantic); the
# text twice and the matches cap, then the candidate cap (full text, the CTE named `keyword`); the
# trigram token twice, the matches cap and the candidate cap (trigram); `rrf_k` three times; the
# limit. Full-text and trigram search each rank at most `keyword_candidates` matches (an arbitrary
# subset when there are more, which the count reveals), then keep `candidates` of them. `<%%` is
# `<%` escaped; with a null token it matches nothing.
SEARCH_STATEMENT: Final[LiteralString] = (
    "with semantic as ("  # noqa: S608  # constant text; every value is a parameter
    " select nearest.id, row_number() over (order by nearest.dist, nearest.id) as rank from ("
    "  select c.id, c.embedding <=> %s::halfvec(1024) as dist from chunk c where " + _READY + ""
    "  order by c.embedding <=> %s::halfvec(1024) limit %s"
    " ) nearest"
    "), keyword as ("
    " select scored.id, row_number() over (order by scored.score desc, scored.id) as rank,"
    "  scored.matched from ("
    "  select m.id, ts_rank_cd(m.keyword, plainto_tsquery('simple', %s::text)) as score,"
    "   count(*) over () as matched from ("
    "   select c.id, c.keyword from chunk c where " + _READY + ""
    "   and c.keyword @@ plainto_tsquery('simple', %s::text) limit %s"
    "  ) m"
    " ) scored order by rank limit %s"
    "), trigram as ("
    " select scored.id, row_number() over (order by scored.sim desc, scored.id) as rank,"
    "  scored.matched from ("
    "  select m.id, word_similarity(%s::text, m.content) as sim, count(*) over () as matched from ("
    "   select c.id, c.content from chunk c where " + _READY + ""
    "   and %s::text <%% c.content limit %s"
    "  ) m"
    " ) scored order by rank limit %s"
    "), hits as ("
    " select c.id as chunk_id, s.id as source_id, s.url, s.ref, d.path, c.symbol, c.start_line,"
    "  c.end_line, c.content,"
    "  coalesce(1.0 / (%s + se.rank), 0) + coalesce(1.0 / (%s + ke.rank), 0)"
    "   + coalesce(1.0 / (%s + tr.rank), 0) as score,"
    "  se.rank as semantic_rank, ke.rank as full_text_rank, tr.rank as trigram_rank"
    " from (select id from semantic union select id from keyword union select id from trigram) ids"
    " join chunk c on c.id = ids.id join document d on d.id = c.document_id"
    " join source s on s.id = d.source_id"
    " left join semantic se on se.id = ids.id left join keyword ke on ke.id = ids.id"
    " left join trigram tr on tr.id = ids.id"
    " order by score desc, c.id limit %s"
    ") select (select count(*) from semantic)::int as semantic_found,"
    " (select coalesce(max(matched), 0) from keyword)::int as full_text_found,"
    " (select coalesce(max(matched), 0) from trigram)::int as trigram_found,"
    " hits.chunk_id, hits.source_id, hits.url, hits.ref, hits.path, hits.symbol, hits.start_line,"
    " hits.end_line, hits.content, hits.score::float8 as score, hits.semantic_rank::int,"
    " hits.full_text_rank::int, hits.trigram_rank::int"
    " from (select 1) one left join hits on true order by hits.score desc nulls last, hits.chunk_id"
)


async def search_chunks(
    *,
    embedding: Sequence[float],
    text: str,
    trigram_token: str | None,
    limit: int,
    db: Executor | None = None,
) -> tuple[list[SearchHitRecord], SearchCounts]:
    """The best `limit` chunks of the `ready` sources, best first (ties on the chunk id), and how
    many chunks each search found. `trigram_token` is `None` when no trigram search should run."""
    vector = _vector_text(embedding)
    rows = await fetch_all(
        _SearchRow,
        SEARCH_STATEMENT,
        (
            vector,
            vector,
            SEARCH.candidates,
            text,
            text,
            SEARCH.keyword_candidates,
            SEARCH.candidates,
            trigram_token,
            trigram_token,
            SEARCH.keyword_candidates,
            SEARCH.candidates,
            SEARCH.rrf_k,
            SEARCH.rrf_k,
            SEARCH.rrf_k,
            limit,
        ),
        db=db,
    )
    first = rows[0]
    counts = SearchCounts(
        semantic=first.semantic_found, full_text=first.full_text_found, trigram=first.trigram_found
    )
    return [hit for hit in map(_to_hit, rows) if hit is not None], counts


def _to_hit(row: _SearchRow) -> SearchHitRecord | None:
    if (
        row.chunk_id is None
        or row.source_id is None
        or row.url is None
        or row.ref is None
        or row.path is None
        or row.start_line is None
        or row.end_line is None
        or row.content is None
        or row.score is None
    ):
        return None
    return SearchHitRecord(
        chunk_id=row.chunk_id,
        source_id=row.source_id,
        url=row.url,
        ref=row.ref,
        path=row.path,
        symbol=row.symbol,
        start_line=row.start_line,
        end_line=row.end_line,
        content=row.content,
        score=row.score,
        semantic_rank=row.semantic_rank,
        full_text_rank=row.full_text_rank,
        trigram_rank=row.trigram_rank,
    )
