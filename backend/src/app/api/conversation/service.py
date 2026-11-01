"""service.py belongs: every query for the `conversation` and `message` tables and nothing else,
private to this directory: only its `controller.py` imports it.
It does not belong: business rules, error mapping or events (`controller.py`).
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Final

from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict

from app.models.conversation.enums import MessageRole
from app.models.conversation.interface import ConversationRecord, MessageRecord
from app.models.conversation.type import ConversationPrefix
from app.services.db import Executor, execute, fetch_all, fetch_one, get_db
from app.services.utils.pagination import Slice, decode_cursor, encode_cursor, to_page


@dataclass(frozen=True)
class _ConversationRow:
    id: str
    user_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class _PrefixRow:
    system_prompt: str | None
    tool_definition: list[object] | None


@dataclass(frozen=True)
class _MessageRow:
    id: str
    position: int
    conversation_id: str
    run_id: str | None
    role: str
    blocks: list[object]
    text: str
    created_at: datetime


def _to_conversation(row: _ConversationRow) -> ConversationRecord:
    return ConversationRecord(
        id=row.id,
        user_id=row.user_id,
        title=row.title,
        created_at=row.created_at.astimezone(UTC),
        updated_at=row.updated_at.astimezone(UTC),
    )


def _to_message(row: _MessageRow) -> MessageRecord:
    return MessageRecord(
        id=row.id,
        position=row.position,
        conversation_id=row.conversation_id,
        run_id=row.run_id,
        role=MessageRole(row.role),
        blocks=row.blocks,
        text=row.text,
        created_at=row.created_at.astimezone(UTC),
    )


_ISO: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T.+")


def _iso_text(value: object) -> object:
    if isinstance(value, str) and _ISO.fullmatch(value):
        return datetime.fromisoformat(value)
    raise ValueError("must be an ISO 8601 timestamp")


class ConversationCursor(BaseModel):
    """The sort key of the conversation list: (updated_at, id), newest first."""

    model_config = ConfigDict(strict=True)

    updated_at: Annotated[AwareDatetime, BeforeValidator(_iso_text)]
    id: str


class MessageCursor(BaseModel):
    """The sort key of the message list: the insertion position, newest first."""

    model_config = ConfigDict(strict=True)

    position: int


def _conversation_cursor(record: ConversationRecord) -> str:
    return encode_cursor({"updated_at": record.updated_at.isoformat(), "id": record.id})


def _message_cursor(record: MessageRecord) -> str:
    return encode_cursor({"position": record.position})


type Tx = Executor
"""The connection a transaction holds, named here so the controller never imports the db seam."""


async def with_transaction[T](work: Callable[[Executor], Awaitable[T]]) -> T:
    """Runs `work` in one transaction; the controller passes the handle to each query."""
    async with get_db() as connection, connection.transaction():
        return await work(connection)


async def insert_conversation(
    record: ConversationRecord, *, db: Executor | None = None
) -> ConversationRecord:
    row = await fetch_one(
        _ConversationRow,
        """
        insert into conversation (id, user_id, title, created_at, updated_at)
        values (%s, %s, %s, %s, %s)
        returning id, user_id, title, created_at, updated_at""",
        (record.id, record.user_id, record.title, record.created_at, record.updated_at),
        db=db,
    )
    if row is None:
        raise RuntimeError("conversation insert returned no row")
    return _to_conversation(row)


async def find_owned_conversation(
    conversation_id: str, user_id: str, *, db: Executor | None = None
) -> ConversationRecord | None:
    row = await fetch_one(
        _ConversationRow,
        "select id, user_id, title, created_at, updated_at from conversation "
        "where id = %s and user_id = %s",
        (conversation_id, user_id),
        db=db,
    )
    return None if row is None else _to_conversation(row)


async def list_conversations(
    user_id: str, *, cursor: str | None, limit: int, db: Executor | None = None
) -> Slice[ConversationRecord]:
    after = None if cursor is None else decode_cursor(cursor, ConversationCursor)
    if after is None:
        rows = await fetch_all(
            _ConversationRow,
            "select id, user_id, title, created_at, updated_at from conversation "
            "where user_id = %s order by updated_at desc, id desc limit %s",
            (user_id, limit + 1),
            db=db,
        )
    else:
        rows = await fetch_all(
            _ConversationRow,
            "select id, user_id, title, created_at, updated_at from conversation "
            "where user_id = %s and (updated_at, id) < (%s, %s) "
            "order by updated_at desc, id desc limit %s",
            (user_id, after.updated_at, after.id, limit + 1),
            db=db,
        )
    return to_page([_to_conversation(row) for row in rows], limit, _conversation_cursor)


async def freeze_prefix(
    conversation_id: str,
    system_prompt: str,
    tool_definition: list[dict[str, object]],
    *,
    db: Executor | None = None,
) -> None:
    """Stores the prompt and tools once: the conditional update changes nothing when they are
    already stored, so the first request's bytes win however many runs race."""
    await execute(
        "update conversation set system_prompt = %s, tool_definition = %s "
        "where id = %s and system_prompt is null",
        (system_prompt, Jsonb(tool_definition), conversation_id),
        db=db,
    )


async def find_prefix(
    conversation_id: str, *, db: Executor | None = None
) -> ConversationPrefix | None:
    """What the conversation is bound to, or `None` before its first run."""
    row = await fetch_one(
        _PrefixRow,
        "select system_prompt, tool_definition from conversation where id = %s",
        (conversation_id,),
        db=db,
    )
    if row is None or row.system_prompt is None:
        return None
    definitions = [entry for entry in row.tool_definition or [] if isinstance(entry, dict)]
    return ConversationPrefix(system_prompt=row.system_prompt, tool_definition=definitions)


async def touch_conversation(
    conversation_id: str, title: str | None, now: datetime, *, db: Executor | None = None
) -> None:
    """Activity: moves the conversation to the top of the list and names it after its first
    message (an existing title is kept)."""
    async with get_db(db) as connection:
        await connection.execute(
            "update conversation set title = coalesce(title, %s), updated_at = %s where id = %s",
            (title, now, conversation_id),
        )


async def insert_message(record: MessageRecord, *, db: Executor | None = None) -> MessageRecord:
    row = await fetch_one(
        _MessageRow,
        """
        insert into message (id, conversation_id, run_id, role, blocks, text, created_at)
        values (%s, %s, %s, %s, %s, %s, %s)
        returning id, position, conversation_id, run_id, role, blocks, text, created_at""",
        (
            record.id,
            record.conversation_id,
            record.run_id,
            record.role,
            Jsonb(record.blocks),
            record.text,
            record.created_at,
        ),
        db=db,
    )
    if row is None:
        raise RuntimeError("message insert returned no row")
    return _to_message(row)


async def list_messages(
    conversation_id: str, *, cursor: str | None, limit: int, db: Executor | None = None
) -> Slice[MessageRecord]:
    """What the wire shows: the user's and the assistant's turns that hold text, newest first."""
    after = None if cursor is None else decode_cursor(cursor, MessageCursor)
    rows = await fetch_all(
        _MessageRow,
        "select id, position, conversation_id, run_id, role, blocks, text, created_at "
        "from message where conversation_id = %s and role in ('user', 'assistant') "
        "and text <> '' and (%s::bigint is null or position < %s::bigint) "
        "order by position desc limit %s",
        (
            conversation_id,
            None if after is None else after.position,
            None if after is None else after.position,
            limit + 1,
        ),
        db=db,
    )
    return to_page([_to_message(row) for row in rows], limit, _message_cursor)


@dataclass(frozen=True)
class _CountRow:
    total: int


async def count_assistant_turns(
    conversation_id: str, run_id: str, *, db: Executor | None = None
) -> int:
    """How many assistant turns the run has stored: its model calls that finished. The
    conversation narrows the scan to the index on `(conversation_id, position)`."""
    row = await fetch_one(
        _CountRow,
        "select count(*) as total from message "
        "where conversation_id = %s and run_id = %s and role = 'assistant'",
        (conversation_id, run_id),
        db=db,
    )
    return 0 if row is None else row.total


async def list_all_messages(
    conversation_id: str, *, db: Executor | None = None
) -> list[MessageRecord]:
    """The whole history, oldest first, every turn: what the next request is built from."""
    rows = await fetch_all(
        _MessageRow,
        "select id, position, conversation_id, run_id, role, blocks, text, created_at "
        "from message where conversation_id = %s order by position",
        (conversation_id,),
        db=db,
    )
    return [_to_message(row) for row in rows]
