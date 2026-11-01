"""controller.py belongs: the search module's business logic and its HTTP handler. The handler
rechecks the caller, because `routes.py` gates with `require_auth` and an endpoint mounted without
its gate must still refuse.
It does not belong: gates (`routes.py`) or schemas (`schema.py`).

This module has no `service.py`: the chunks belong to `api/source/`, and the search reaches them
through that controller's exported rule `search_ready_chunks`. The query is embedded here, outside
any transaction, so a slow Voyage call holds no pooled connection.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Final
from weakref import WeakKeyDictionary

from fastapi import Query, Request
from pydantic import ValidationError

from app.api.search.schema import SearchHit, SearchQuery, SearchResult
from app.api.source.controller import search_ready_chunks
from app.config.constants import KNOWLEDGE, SEARCH
from app.middleware.auth import require_caller
from app.models.search.enums import ToolSearchCode
from app.models.search.interface import SearchHitRecord, SearchOutcome
from app.models.search.type import ToolSearchFailed
from app.services.logger import log
from app.services.utils.error import AppError
from app.services.voyage import EmbeddingUnavailable, embed_query


def _trigram_token(text: str) -> str | None:
    """The text as a trigram search's token: one word of `trigram_min_chars` to
    `trigram_max_chars`. A sentence or a longer word runs no trigram search, since trigrams of
    many words match everything; a two-letter word has no trigram of its own, only padded ones,
    which on real code makes half the chunks candidates. Full-text search still finds a short word,
    but not one inside a dotted call (`self.get(key)` is the lexeme `self.get`), which is why three
    letters still run a trigram search."""
    if not SEARCH.trigram_min_chars <= len(text) <= SEARCH.trigram_max_chars:
        return None
    if len(text.split()) != 1:
        return None
    return text


async def search_knowledge_base(*, text: str, limit: int) -> SearchOutcome:
    """Rule for other modules (the `knowledge` MCP server): the best `limit` chunks of the `ready`
    sources for `text`. System-wide: no caller, since every account searches the same index.
    `text` is trimmed and validated by the caller (`SearchQuery`)."""
    try:
        embedding = await embed_query(text)
    except EmbeddingUnavailable:
        # The reason stays out of the response and the log carries no query text.
        log.warning("search embedding unavailable", {"length": len(text)})
        raise AppError("upstream_unavailable", "search is unavailable") from None
    return await search_ready_chunks(
        embedding=embedding, text=text, trigram_token=_trigram_token(text), limit=limit
    )


_SLOTS: Final[WeakKeyDictionary[asyncio.AbstractEventLoop, tuple[int, asyncio.Semaphore]]] = (
    WeakKeyDictionary()
)


def _semaphore() -> asyncio.Semaphore:
    """The loop's semaphore of `concurrent_searches` slots. Built on first use, because one is
    bound to the loop it first waits on; rebuilt when the number changes (a test sets it)."""
    loop = asyncio.get_running_loop()
    held = _SLOTS.get(loop)
    if held is None or held[0] != KNOWLEDGE.concurrent_searches:
        held = (KNOWLEDGE.concurrent_searches, asyncio.Semaphore(KNOWLEDGE.concurrent_searches))
        _SLOTS[loop] = held
    return held[1]


@asynccontextmanager
async def _slot() -> AsyncIterator[None]:
    """One of the tool's concurrent searches: waits `slot_wait_seconds`, then `busy`."""
    semaphore = _semaphore()
    try:
        await asyncio.wait_for(semaphore.acquire(), KNOWLEDGE.slot_wait_seconds)
    except TimeoutError:
        raise ToolSearchFailed(ToolSearchCode.busy) from None
    try:
        yield
    finally:
        semaphore.release()


def _tool_query(query: str) -> str:
    """The query as `GET /api/search` checks `q`: trimmed, 1 to 500 characters, no NUL."""
    try:
        return SearchQuery.model_validate({"q": query}).q
    except ValidationError:
        raise ToolSearchFailed(ToolSearchCode.invalid_query) from None


def _tool_hit(record: SearchHitRecord) -> dict[str, object]:
    """One hit field by field: the cosine, the score and the ranks stay out of what the model
    reads."""
    return {
        "url": record.url,
        "ref": record.ref,
        "path": record.path,
        "symbol": record.symbol,
        "startLine": record.start_line,
        "endLine": record.end_line,
        "content": record.content,
    }


def _tool_document(hits: list[dict[str, object]], kept: int, incomplete: bool) -> str:
    return json.dumps(
        {"hits": hits[:kept], "incomplete": incomplete, "omitted": len(hits) - kept},
        ensure_ascii=False,
        separators=(",", ":"),
    )


async def search_for_tool(*, query: str) -> str:
    """Rule for the `knowledge` MCP server's `search` tool: the best `hit_limit` hits for `query`
    as one JSON document, best first, whole hits only within `output_max_chars` (`omitted` counts
    the rest). It takes no caller and no `limit`, and sits outside `search_per_user`, which bounds
    a route; what bounds this caller is `concurrent_searches` here and the loop's call budget. A
    failure is a `ToolSearchFailed` with one fixed code; the log carries lengths and counts, never
    the query."""
    text = _tool_query(query)
    async with _slot():
        try:
            outcome = await search_knowledge_base(text=text, limit=KNOWLEDGE.hit_limit)
        except AppError:
            raise ToolSearchFailed(ToolSearchCode.search_unavailable) from None
    hits = [_tool_hit(record) for record in outcome.hits[: KNOWLEDGE.hit_limit]]
    kept = len(hits)
    while (
        kept > 0
        and len(_tool_document(hits, kept, outcome.incomplete)) > KNOWLEDGE.output_max_chars
    ):
        kept -= 1
    log.info(
        "knowledge search",
        {"queryLength": len(text), "hits": kept, "omitted": len(hits) - kept},
    )
    return _tool_document(hits, kept, outcome.incomplete)


def _to_wire(record: SearchHitRecord) -> SearchHit:
    return SearchHit(
        chunk_id=record.chunk_id,
        source_id=record.source_id,
        url=record.url,
        ref=record.ref,
        path=record.path,
        symbol=record.symbol,
        start_line=record.start_line,
        end_line=record.end_line,
        content=record.content,
        score=record.score,
        semantic_rank=record.semantic_rank,
        full_text_rank=record.full_text_rank,
        trigram_rank=record.trigram_rank,
    )


async def search(request: Request, query: Annotated[SearchQuery, Query()]) -> SearchResult:
    require_caller(request)
    outcome = await search_knowledge_base(text=query.q, limit=query.limit)
    return SearchResult(
        items=[_to_wire(hit) for hit in outcome.hits], incomplete=outcome.incomplete
    )
