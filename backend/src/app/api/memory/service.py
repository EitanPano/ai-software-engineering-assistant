"""service.py belongs: every query for the `memory` table and nothing else, private to this
directory: only its `controller.py` imports it. The table is created by `0012-memory.sql`.
It does not belong: business rules, error mapping or events (`controller.py`).
"""

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Final

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, field_validator

from app.models.memory.interface import MemoryRecord
from app.services.db import Executor, execute, fetch_all, fetch_one, get_db
from app.services.utils.pagination import Slice, decode_cursor, encode_cursor, to_page

_ISO: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T.+")


@dataclass(frozen=True)
class _MemoryRow:
    id: str
    user_id: str
    conversation_id: str
    content: str
    created_at: datetime


@dataclass(frozen=True)
class _CountRow:
    total: int


@dataclass(frozen=True)
class _ContentRow:
    content: str


type Tx = Executor
"""The connection a transaction holds, named here so the controller never imports the db seam."""


async def with_transaction[T](work: Callable[[Executor], Awaitable[T]]) -> T:
    """Runs `work` in one transaction; the controller passes the handle to each query."""
    async with get_db() as connection, connection.transaction():
        return await work(connection)


def _vector_text(embedding: Sequence[float]) -> str:
    """An embedding travels as text cast to `halfvec(1024)`; there is no Python vector type."""
    return "[" + ",".join(format(x, ".8g") for x in embedding) + "]"


def _iso_text(value: object) -> object:
    if isinstance(value, str) and _ISO.fullmatch(value):
        return datetime.fromisoformat(value)
    raise ValueError("must be an ISO 8601 timestamp")


class MemoryCursor(BaseModel):
    """The sort key of the memory list: (created_at, id), newest first."""

    model_config = ConfigDict(strict=True)

    created_at: Annotated[AwareDatetime, BeforeValidator(_iso_text)]
    id: str

    @field_validator("id")
    @classmethod
    def _no_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("must not hold a NUL")
        return value


def _to_memory(row: _MemoryRow) -> MemoryRecord:
    return MemoryRecord(
        id=row.id,
        user_id=row.user_id,
        conversation_id=row.conversation_id,
        content=row.content,
        created_at=row.created_at.astimezone(UTC),
    )


def _cursor(record: MemoryRecord) -> str:
    return encode_cursor({"created_at": record.created_at.isoformat(), "id": record.id})


async def list_memories(
    user_id: str, *, cursor: str | None, limit: int, db: Executor | None = None
) -> Slice[MemoryRecord]:
    """The user's memories, newest first, through the `(user_id, created_at, id)` index."""
    after = None if cursor is None else decode_cursor(cursor, MemoryCursor)
    columns = "select id, user_id, conversation_id, content, created_at from memory "
    if after is None:
        rows = await fetch_all(
            _MemoryRow,
            columns + "where user_id = %s order by created_at desc, id desc limit %s",
            (user_id, limit + 1),
            db=db,
        )
    else:
        rows = await fetch_all(
            _MemoryRow,
            columns + "where user_id = %s and (created_at, id) < (%s, %s) "
            "order by created_at desc, id desc limit %s",
            (user_id, after.created_at, after.id, limit + 1),
            db=db,
        )
    return to_page([_to_memory(row) for row in rows], limit, _cursor)


async def delete_owned_memory(memory_id: str, user_id: str, *, db: Executor | None = None) -> bool:
    """Removes the row and its embedding together; false when the user owns no such memory."""
    if "\x00" in memory_id:  # a text column cannot hold one
        return False
    deleted = await execute(
        "delete from memory where id = %s and user_id = %s", (memory_id, user_id), db=db
    )
    return deleted > 0


async def count_memories(user_id: str, *, db: Executor | None = None) -> int:
    row = await fetch_one(
        _CountRow, "select count(*) as total from memory where user_id = %s", (user_id,), db=db
    )
    return 0 if row is None else row.total


async def find_stored(
    user_id: str, lowered: Sequence[str], *, db: Executor | None = None
) -> set[str]:
    """The lowercased contents, of `lowered`, that the user already has: the unique index's key."""
    rows = await fetch_all(
        _ContentRow,
        "select lower(content) as content from memory where user_id = %s "
        "and lower(content) = any(%s)",
        (user_id, list(lowered)),
        db=db,
    )
    return {row.content for row in rows}


async def insert_memories(
    records: Sequence[MemoryRecord],
    embeddings: Sequence[Sequence[float]],
    *,
    db: Executor | None = None,
) -> int:
    """Stores each record with its embedding; one already stored (same user, same lowercased text)
    is skipped. Returns how many rows were written."""
    if len(records) != len(embeddings):
        raise ValueError("one embedding per memory")
    written = 0
    for record, embedding in zip(records, embeddings, strict=True):
        written += await execute(
            "insert into memory (id, user_id, conversation_id, content, embedding, created_at) "
            "values (%s, %s, %s, %s, %s::halfvec(1024), %s) on conflict do nothing",
            (
                record.id,
                record.user_id,
                record.conversation_id,
                record.content,
                _vector_text(embedding),
                record.created_at,
            ),
            db=db,
        )
    return written


async def nearest_memories(
    user_id: str, embedding: Sequence[float], *, limit: int, db: Executor | None = None
) -> list[MemoryRecord]:
    """The user's memories nearest to `embedding`, best first: an exact scan of that user's rows
    (at most `MEMORY.max_per_user`) through the `(user_id, created_at, id)` index, so every row is
    considered, whatever the other users hold."""
    rows = await fetch_all(
        _MemoryRow,
        "select id, user_id, conversation_id, content, created_at from memory "
        "where user_id = %s order by embedding <=> %s::halfvec(1024), created_at desc, id desc "
        "limit %s",
        (user_id, _vector_text(embedding), limit),
        db=db,
    )
    return [_to_memory(row) for row in rows]
