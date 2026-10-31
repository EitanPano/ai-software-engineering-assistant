"""controller.py belongs: the source module's business logic and its HTTP handlers, and the system
operations the boot sweep and the indexer subscriber call. Each handler rechecks the admin role,
because `routes.py` gates with `require_role` and an endpoint mounted without its gate must still
refuse.
It does not belong: gates (`routes.py`), queries (`service.py`) or schemas (`schema.py`).

Connecting asks GitHub twice (the repository in its own spelling and default branch, then the
commit the ref names, so an unknown repository, ref or an empty repository is a 404 here and not a
failed index later), stores the source `queued` and publishes `source.queued`.

`index_source` is the index, a system operation with no caller. It claims the `queued` row,
clears an earlier attempt, resolves the commit, streams the archive to a spooled file and, on a
worker thread, reads it and chunks it (the parse worker child does the tree-sitter work, under a
deadline); then it embeds and commits batch by batch, because a large repository's embeddings do
not fit in memory, and ends `ready`. Every exit ends the source: a failure removes its documents
and ends `failed` with a code, a cancellation (shutdown) ends it `failed` as `interrupted`, and
the parse worker child is ended on every path. Nothing is searchable until the source is `ready`.
"""

import asyncio
import itertools
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import IO, Annotated, assert_never

from fastapi import Query, Request
from pydantic import MISSING

from app.api.source import service
from app.api.source.schema import (
    ConnectSourceBody,
    Source,
    SourceErrorCodeName,
    SourceId,
    SourcePage,
    SourceStatusName,
)
from app.config.constants import EMBEDDING, INDEX_CAPS, SEARCH
from app.middleware.auth import require_caller
from app.models.auth.type import Caller
from app.models.search.interface import SearchCounts, SearchHitRecord, SearchOutcome
from app.models.source.enums import SourceErrorCode, SourceStatus
from app.models.source.interface import ChunkRecord, DocumentRecord, SourceRecord
from app.models.source.type import Chunk
from app.models.user.enums import UserRole
from app.services import github
from app.services.chunk import chunk_text, language_of
from app.services.event import SOURCE_QUEUED, publish
from app.services.github import (
    ArchiveTooLarge,
    GithubError,
    RepositoryNotFound,
    download_archive,
    read_archive,
)
from app.services.logger import log
from app.services.parse import ParseSession
from app.services.utils import clock
from app.services.utils.error import AppError
from app.services.utils.pagination import PageQuery
from app.services.voyage import EmbeddingUnavailable, embed_documents

_GITHUB_PREFIX = "https://github.com/"


def _wire_status(status: SourceStatus) -> SourceStatusName:
    """The edge between the domain enum and the wire's literal; `match` makes mypy fail here when
    a member is added to one and not the other."""
    match status:
        case SourceStatus.queued:
            return "queued"
        case SourceStatus.indexing:
            return "indexing"
        case SourceStatus.ready:
            return "ready"
        case SourceStatus.failed:
            return "failed"
        case _:
            assert_never(status)


def _wire_error(code: SourceErrorCode | None) -> SourceErrorCodeName | None:
    match code:
        case None:
            return None
        case SourceErrorCode.repository_unavailable:
            return "repository_unavailable"
        case SourceErrorCode.repository_too_large:
            return "repository_too_large"
        case SourceErrorCode.embedding_unavailable:
            return "embedding_unavailable"
        case SourceErrorCode.interrupted:
            return "interrupted"
        case SourceErrorCode.internal:
            return "internal"
        case _:
            assert_never(code)


def _to_wire(record: SourceRecord) -> Source:
    return Source(
        id=record.id,
        url=record.url,
        ref=record.ref,
        status=_wire_status(record.status),
        error_code=_wire_error(record.error_code),
        indexed_commit=record.indexed_commit,
        document_count=record.document_count,
        chunk_count=record.chunk_count,
        created_at=clock.to_iso(record.created_at),
        updated_at=clock.to_iso(record.updated_at),
    )


def _assert_admin(caller: Caller) -> None:
    if caller.role is not UserRole.admin:
        raise AppError("forbidden", "insufficient role")


def _owner_and_repo(url: str) -> tuple[str, str]:
    """The two segments of a stored `https://github.com/<owner>/<repo>`."""
    owner, _, repo = url.removeprefix(_GITHUB_PREFIX).partition("/")
    return owner, repo


async def connect_source(request: Request, body: ConnectSourceBody) -> Source:
    _assert_admin(require_caller(request))
    owner, repo = _owner_and_repo(body.url)
    try:
        repository = await github.lookup_repository(owner, repo)
        ref = repository.default_branch if body.ref is MISSING else body.ref
        canonical_owner, canonical_repo = _owner_and_repo(repository.url)
        await github.resolve_commit(canonical_owner, canonical_repo, ref)
    except RepositoryNotFound:
        raise AppError("not_found", "no such public repository or ref") from None
    except GithubError as error:
        fields: dict[str, str | int] = {"error": type(error).__name__}
        if error.status is not None:
            fields["status"] = error.status
        log.warning("github unavailable", fields)
        raise AppError("upstream_unavailable", "GitHub is unavailable") from None
    now = clock.now()
    record = await service.insert_source(
        SourceRecord(
            id=str(uuid.uuid4()),
            url=repository.url,
            ref=ref,
            status=SourceStatus.queued,
            error_code=None,
            indexed_commit=None,
            document_count=0,
            chunk_count=0,
            created_at=now,
            updated_at=now,
        )
    )
    await publish(SOURCE_QUEUED, {"source_id": record.id})
    return _to_wire(record)


async def list_source(request: Request, query: Annotated[PageQuery, Query()]) -> SourcePage:
    _assert_admin(require_caller(request))
    page = await service.list_sources(
        cursor=None if query.cursor is MISSING else query.cursor, limit=query.limit
    )
    return SourcePage(
        items=[_to_wire(record) for record in page.items], next_cursor=page.next_cursor
    )


async def retry_source(request: Request, source_id: SourceId) -> Source:
    """A failed source goes back to `queued`; anything else is a conflict."""
    _assert_admin(require_caller(request))
    record = await service.requeue_failed(source_id, clock.now())
    if record is None:
        if await service.find_source(source_id) is None:
            raise AppError("not_found", "source not found")
        raise AppError("conflict", "only a failed source can be indexed again")
    await publish(SOURCE_QUEUED, {"source_id": record.id})
    return _to_wire(record)


@dataclass(frozen=True)
class _Draft:
    """A document and its chunks, before they are embedded."""

    document: DocumentRecord
    chunks: list[Chunk]


def _failure_code(error: Exception) -> SourceErrorCode | None:
    """The code an expected failure ends a source with; `None` for anything else."""
    if isinstance(error, ArchiveTooLarge):
        return SourceErrorCode.repository_too_large
    if isinstance(error, GithubError):
        return SourceErrorCode.repository_unavailable
    if isinstance(error, EmbeddingUnavailable):
        return SourceErrorCode.embedding_unavailable
    return None


def _prepare(source_id: str, archive: IO[bytes], session: ParseSession) -> list[_Draft]:
    """On a worker thread: reads the archive, finds each file's symbols in the parse worker and
    chunks it. A file with no chunk (blank after trimming) is not a document.

    The input caps do not bound what chunking produces (a file of `def a():0` lines is one chunk
    per ten bytes), so the chunks and their characters are counted here, as the drafts accumulate
    and before anything is embedded: over a cap the repository fails whole. The thread owns the
    archive file and closes it, so a cancelled index never closes it under a reader."""
    now = clock.now()
    drafts: list[_Draft] = []
    chunk_count = 0
    embedded_chars = 0
    try:
        for file in read_archive(archive, INDEX_CAPS):
            language = language_of(file.path)
            symbols = None if language is None else session.symbols(language, file.text)
            chunks = chunk_text(file.text, symbols)
            chunk_count += len(chunks)
            embedded_chars += sum(len(chunk.content) for chunk in chunks)
            if chunk_count > INDEX_CAPS.chunks or embedded_chars > INDEX_CAPS.embedded_chars:
                raise ArchiveTooLarge
            if chunks:
                document = DocumentRecord(
                    id=str(uuid.uuid4()),
                    source_id=source_id,
                    path=file.path,
                    language=language,
                    created_at=now,
                )
                drafts.append(_Draft(document=document, chunks=chunks))
    finally:
        archive.close()
    return drafts


async def _store(drafts: list[_Draft]) -> tuple[int, int]:
    """Embeds and commits the chunks `EMBEDDING.commit_chunks` at a time; returns the document and
    chunk counts. A document row is written with its first chunk."""
    items = [(draft.document, chunk) for draft in drafts for chunk in draft.chunks]
    stored: set[str] = set()
    total = 0
    for batch in itertools.batched(items, EMBEDDING.commit_chunks, strict=False):
        vectors = await embed_documents([chunk.content for _, chunk in batch])
        now = clock.now()
        fresh = {d.id: d for d, _ in batch if d.id not in stored}
        records = [
            ChunkRecord(
                id=str(uuid.uuid4()),
                document_id=document.id,
                symbol=chunk.symbol,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content=chunk.content,
                created_at=now,
            )
            for document, chunk in batch
        ]

        await _commit([*fresh.values()], records, vectors)
        stored.update(fresh)
        total += len(records)
    return len(stored), total


async def _commit(
    documents: list[DocumentRecord], chunks: list[ChunkRecord], embeddings: list[list[float]]
) -> None:
    """One batch, all or nothing."""

    async def work(db: service.Tx) -> None:
        await service.insert_documents(documents, db=db)
        await service.insert_chunks(chunks, embeddings, db=db)

    await service.with_transaction(work)


async def _index(source: SourceRecord, session: ParseSession) -> None:
    owner, repo = _owner_and_repo(source.url)
    await service.clear_documents(source.id)  # an earlier attempt's rows
    commit = await github.resolve_commit(owner, repo, source.ref)
    archive = await download_archive(owner, repo, commit, max_bytes=INDEX_CAPS.archive_bytes)
    # The thread starts with no await between here and it, and closes the archive itself.
    drafts = await asyncio.to_thread(_prepare, source.id, archive, session)
    documents, chunks = await _store(drafts)
    if not await service.finish_ready(source.id, commit, documents, chunks, clock.now()):
        log.warning("source left indexing before it finished", {"sourceId": source.id})
        return
    await _refresh_statistics(source.id)


async def _refresh_statistics(source_id: str) -> None:
    """Best effort: the source is already `ready`, so a failure here must not end it `failed`. A
    cancellation is not caught."""
    try:
        await service.refresh_statistics()
    except Exception as error:
        log.warning(
            "could not refresh statistics",
            {"sourceId": source_id, "error": type(error).__name__},
        )


async def _end_failed(source_id: str, code: SourceErrorCode) -> bool:
    """Ends an active source `failed` and removes its documents, together. False when it was
    already finished or the write failed (logged): this runs on exit paths and never raises."""
    try:

        async def work(db: service.Tx) -> bool:
            return await service.finish_failed(source_id, code, clock.now(), db=db)

        return await service.with_transaction(work)
    except Exception as error:
        log.error("could not end a source", {"sourceId": source_id, "reason": code.value}, error)
        return False


async def index_source(source_id: str) -> None:
    """System operation: indexes one queued source to its end. A source that is not queued
    (another indexer has it, or the boot sweep ended it) is left alone. Every exit ends it `ready`
    or `failed`, and ends the parse worker."""
    claimed = await service.claim_source(source_id, clock.now())
    if claimed is None:
        return
    session = ParseSession()
    try:
        await _index(claimed, session)
    except asyncio.CancelledError:
        # A shutdown: free the parse in progress and end the source now rather than leave it for
        # the next boot's sweep. Closing here is direct: nothing may delay a cancelled task.
        session.close()
        await asyncio.shield(_end_failed(claimed.id, SourceErrorCode.interrupted))
        raise
    except Exception as error:
        code = _failure_code(error)
        if code is None:
            log.error("index failed", {"sourceId": claimed.id}, error)
            code = SourceErrorCode.internal
        else:
            log.warning("index failed", _failure_fields(claimed.id, code, error))
        await _end_failed(claimed.id, code)
    finally:
        _log_fallbacks(claimed.id, session)
        # Ending the child can wait for it to die: not on the event loop that serves chat.
        if not session.closed:
            await asyncio.to_thread(session.close)


def _failure_fields(
    source_id: str, code: SourceErrorCode, error: Exception
) -> dict[str, str | int]:
    """What an operator needs to tell failures of one code apart: the class of the error and, for
    GitHub, the status it answered. Never a message, a path or a payload."""
    fields: dict[str, str | int] = {
        "sourceId": source_id,
        "reason": code.value,
        "error": type(error).__name__,
    }
    if isinstance(error, GithubError) and error.status is not None:
        fields["status"] = error.status
    return fields


def _log_fallbacks(source_id: str, session: ParseSession) -> None:
    """A fallback to line windows is not silent: how many files, and why, with no path."""
    summary = session.summary()
    if summary.fallbacks or summary.syntax_errors:
        log.warning(
            "parse fell back",
            {
                "sourceId": source_id,
                "overruns": summary.overruns,
                "crashes": summary.crashes,
                "budgetSkipped": summary.budget_skipped,
                "syntaxErrors": summary.syntax_errors,
            },
        )


async def search_ready_chunks(
    *, embedding: Sequence[float], text: str, trigram_token: str | None, limit: int
) -> SearchOutcome:
    """Rule for the search module: the best `limit` chunks of the `ready` sources, fused from a
    semantic, a full-text and a trigram search, and whether a limit cut any of them short.

    `incomplete` is true when the keyword searches reached their cap of matches, or when the
    semantic search found fewer chunks than the `ready` sources could supply: pgvector filters
    after its index scan and documents no signal when a scan stops at `max_scan_tuples`, so the
    shortfall is the signal. The log line carries counts and no query text."""

    async def work(db: service.Tx) -> tuple[list[SearchHitRecord], SearchCounts, int]:
        await service.prepare_search(db=db)
        ready = await service.count_ready_chunks(db=db)
        hits, counts = await service.search_chunks(
            embedding=embedding, text=text, trigram_token=trigram_token, limit=limit, db=db
        )
        return hits, counts, ready

    hits, counts, ready = await service.with_transaction(work)
    capped = max(counts.full_text, counts.trigram) >= SEARCH.keyword_candidates
    short = counts.semantic < min(SEARCH.candidates, ready)
    incomplete = capped or short
    if incomplete:
        log.warning(
            "search incomplete",
            {
                "semantic": counts.semantic,
                "fullText": counts.full_text,
                "trigram": counts.trigram,
                "readyChunks": ready,
            },
        )
    return SearchOutcome(hits=hits, incomplete=incomplete)


async def fail_lost_sources(started_before: datetime) -> int:
    """System operation: the boot sweep. Sources still active that were last touched before this
    process started belong to a process that is gone; each ends `failed` as `interrupted`."""
    failed = 0
    for record in await service.list_active_sources_before(started_before):
        if await _end_failed(record.id, SourceErrorCode.interrupted):
            failed += 1
    if failed:
        log.warning("failed lost sources", {"count": failed})
    return failed
