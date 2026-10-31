"""controller.py belongs: the search module's business logic and its HTTP handler. The handler
rechecks the caller, because `routes.py` gates with `require_auth` and an endpoint mounted without
its gate must still refuse.
It does not belong: gates (`routes.py`) or schemas (`schema.py`).

This module has no `service.py`: the chunks belong to `api/source/`, and the search reaches them
through that controller's exported rule `search_ready_chunks`. The query is embedded here, outside
any transaction, so a slow Voyage call holds no pooled connection.
"""

from typing import Annotated

from fastapi import Query, Request

from app.api.search.schema import SearchHit, SearchQuery, SearchResult
from app.api.source.controller import search_ready_chunks
from app.config.constants import SEARCH
from app.middleware.auth import require_caller
from app.models.search.interface import SearchHitRecord, SearchOutcome
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
