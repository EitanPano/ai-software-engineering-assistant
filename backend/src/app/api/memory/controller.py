"""controller.py belongs: this directory's HTTP handlers, one per endpoint (the caller's memories
and their deletion), and the rules others call: `recall_for_tool` (the `knowledge` server's
`recall`) and `extract_memory` (the reaction to a completed run).
It does not belong: gates (`routes.py`), queries (`service.py`) or schemas (`schema.py`).
"""

import json
import uuid
from typing import Annotated

from fastapi import Query, Request, Response
from pydantic import MISSING, ValidationError

from app.api.conversation.controller import read_user_text
from app.api.memory import service
from app.api.memory.schema import Memory, MemoryExtraction, MemoryId, MemoryPage
from app.api.run.controller import get_run
from app.api.search.controller import ToolBusy, tool_slot
from app.api.search.schema import SearchQuery
from app.config.constants import MEMORY, MEMORY_EXTRACTION_PROMPT
from app.config.env import env
from app.middleware.auth import require_caller
from app.models.memory.enums import ToolRecallCode
from app.models.memory.interface import MemoryRecord
from app.models.memory.type import ToolRecallFailed
from app.services.anthropic import parse_turn
from app.services.logger import log
from app.services.utils import clock
from app.services.utils.error import AppError
from app.services.utils.pagination import PageQuery
from app.services.utils.secret_shape import looks_like_secret
from app.services.voyage import EmbeddingUnavailable, embed_documents, embed_query


def _to_memory(record: MemoryRecord) -> Memory:
    return Memory(
        id=record.id,
        content=record.content,
        conversation_id=record.conversation_id,
        created_at=clock.to_iso(record.created_at),
    )


async def list_memory(request: Request, query: Annotated[PageQuery, Query()]) -> MemoryPage:
    caller = require_caller(request)
    page = await service.list_memories(
        caller.id,
        cursor=None if query.cursor is MISSING else query.cursor,
        limit=query.limit,
    )
    return MemoryPage(
        items=[_to_memory(record) for record in page.items], next_cursor=page.next_cursor
    )


def _tool_query(query: str) -> str:
    """The query as `GET /api/search` checks `q`: trimmed, 1 to 500 characters, no NUL."""
    try:
        return SearchQuery.model_validate({"q": query}).q
    except ValidationError:
        raise ToolRecallFailed(ToolRecallCode.invalid_query) from None


async def recall_for_tool(*, query: str, user_id: str | None) -> str:
    """Rule for the `knowledge` MCP server's `recall` tool: the caller's memories nearest to
    `query`, as one JSON document, best first, at most `MEMORY.recall_limit`, mapped field by
    field (no id, no embedding, no distance). `user_id` is the caller the request's `_meta` named;
    none is `no_caller`, checked before the query, the embedding or any read. It shares the
    search's slots, so the server's pool stays bounded. A failure is a `ToolRecallFailed` with one
    fixed code; the log carries lengths and counts, never the query or a memory."""
    if user_id is None:
        raise ToolRecallFailed(ToolRecallCode.no_caller)
    text = _tool_query(query)
    try:
        async with tool_slot():
            try:
                embedding = await embed_query(text)
            except EmbeddingUnavailable:
                log.warning("recall embedding unavailable", {"queryLength": len(text)})
                raise ToolRecallFailed(ToolRecallCode.recall_unavailable) from None
            records = await service.nearest_memories(user_id, embedding, limit=MEMORY.recall_limit)
    except ToolBusy:
        raise ToolRecallFailed(ToolRecallCode.busy) from None
    log.info("memory recall", {"queryLength": len(text), "memories": len(records)})
    return json.dumps(
        {
            "memories": [
                {"content": record.content, "createdAt": clock.to_iso(record.created_at)}
                for record in records
            ]
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _storable(fact: str) -> str | None:
    """The fact as it is stored, or `None` when it must not be: empty, over `fact_max_chars`,
    holding a NUL (a text column cannot store one) or shaped like a key."""
    text = fact.strip()
    if not text or len(text) > MEMORY.fact_max_chars or "\x00" in text:
        return None
    return None if looks_like_secret(text) else text


async def _new_facts(user_id: str, facts: list[str], room: int) -> list[str]:
    """The facts to store: at most `extract_limit` read, at most `room` kept, each storable, none
    repeated within the list (by the unique index's key, the lowercased text) or already stored."""
    seen: set[str] = set()
    candidates: list[str] = []
    for fact in facts[: MEMORY.extract_limit]:
        text = _storable(fact)
        if text is not None and text.lower() not in seen:
            seen.add(text.lower())
            candidates.append(text)
    if not candidates:
        return []
    stored = await service.find_stored(user_id, [text.lower() for text in candidates])
    return [text for text in candidates if text.lower() not in stored][:room]


async def extract_memory(*, run_id: str) -> None:
    """System operation: stores the durable facts the run's `user` message states, for that
    person. The person's `max_per_user` is checked before any paid call; the side call reads that
    message alone (`read_user_text`), never the answer, a tool output or an earlier turn; the
    insert is last and skips a fact already stored. Any failure (a refusal, invalid output, Voyage
    down, the store) logs its class and touches nothing: the run, its events and `memory` stay as
    they were, and no content is logged."""
    try:
        run = await get_run(run_id)
        held = await service.count_memories(run.user_id)
        if held >= MEMORY.max_per_user:
            log.info("memory full, nothing extracted", {"runId": run_id, "memories": held})
            return
        text = await read_user_text(conversation_id=run.conversation_id, run_id=run_id)
        if text is None or not text.strip():
            return
        extraction = await parse_turn(
            MemoryExtraction,
            system=MEMORY_EXTRACTION_PROMPT,
            content=text,
            model=env.llm_side_model,
            effort=MEMORY.extract_effort,
        )
        facts = await _new_facts(run.user_id, extraction.facts, MEMORY.max_per_user - held)
        if not facts:
            log.info("memory extracted", {"runId": run_id, "facts": 0})
            return
        embeddings = await embed_documents(facts)
        now = clock.now()
        records = [
            MemoryRecord(
                id=str(uuid.uuid4()),
                user_id=run.user_id,
                conversation_id=run.conversation_id,
                content=fact,
                created_at=now,
            )
            for fact in facts
        ]

        async def store(tx: service.Tx) -> int:
            return await service.insert_memories(records, embeddings, db=tx)

        written = await service.with_transaction(store)  # all the facts, or none
        log.info("memory extracted", {"runId": run_id, "facts": written})
    except Exception as error:
        # The class only: the exception's text can hold the person's words.
        log.warning("memory extraction failed", {"runId": run_id, "reason": type(error).__name__})


async def delete_memory(request: Request, memory_id: MemoryId) -> Response:
    """Another user's memory, an admin's included, is a 404, so its existence is not revealed."""
    caller = require_caller(request)
    if not await service.delete_owned_memory(memory_id, caller.id):
        raise AppError("not_found", "memory not found")
    return Response(status_code=204)
