"""Helpers for the memory suites: store a memory as extraction would (embedded by the scripted
Voyage, so the `fakes` fixture must be active), and read the rows back."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from app.api.memory import service as memory_service
from app.models.memory.interface import MemoryRecord
from app.services import voyage
from app.services.db import fetch_all, fetch_one
from app.services.utils import clock

FACT: Final = "The person keeps deploy notes in ops/RUNBOOK.md."


@dataclass(frozen=True)
class Stored:
    user_id: str
    conversation_id: str
    content: str
    has_embedding: bool


async def stored_memories() -> list[Stored]:
    return await fetch_all(
        Stored,
        "select user_id, conversation_id, content, embedding is not null as has_embedding "
        "from memory order by created_at, id",
    )


@dataclass(frozen=True)
class _Owner:
    user_id: str


async def owner_of(run_id: str) -> str:
    row = await fetch_one(_Owner, "select user_id from run where id = %s", (run_id,))
    assert row is not None
    return row.user_id


async def remember(
    user_id: str,
    content: str,
    *,
    conversation_id: str = "conversation-1",
    created_at: datetime | None = None,
) -> str:
    """Stores a memory as extraction would; returns its id."""
    [embedding] = await voyage.embed_documents([content])
    record = MemoryRecord(
        id=str(uuid.uuid4()),
        user_id=user_id,
        conversation_id=conversation_id,
        content=content,
        created_at=created_at or clock.now(),
    )
    assert await memory_service.insert_memories([record], [embedding]) == 1
    return record.id
