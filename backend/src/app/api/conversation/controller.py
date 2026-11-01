"""controller.py belongs: this directory's business logic and its HTTP handlers, one handler per
endpoint, and the rules the agent module calls (read the history, append the turns of a model
call).
It does not belong: gates (`routes.py`), queries (`service.py`) or schemas (`schema.py`).
"""

import uuid
from typing import Annotated, assert_never

from fastapi import Query, Request
from pydantic import MISSING

from app.api.conversation import service
from app.api.conversation.schema import (
    Conversation,
    ConversationDetail,
    ConversationId,
    ConversationPage,
    Message,
    MessagePage,
    MessageRoleName,
    SendMessageBody,
    SentMessage,
)
from app.api.run.controller import create_run, finish_run, get_latest_run, to_wire_run
from app.config.constants import CONVERSATION_TITLE_MAX_CHARS
from app.middleware.auth import require_caller
from app.models.conversation.enums import MessageRole
from app.models.conversation.interface import ConversationRecord, MessageRecord
from app.models.conversation.type import ConversationPrefix, HistoryTurn, NewTurn
from app.models.run.enums import RunErrorCode, RunStatus
from app.services.event import RUN_CREATED, publish
from app.services.logger import log
from app.services.utils import clock
from app.services.utils.error import AppError
from app.services.utils.pagination import PageQuery


def _to_conversation(record: ConversationRecord) -> Conversation:
    return Conversation(
        id=record.id,
        title=record.title,
        created_at=clock.to_iso(record.created_at),
        updated_at=clock.to_iso(record.updated_at),
    )


def _wire_role(role: MessageRole) -> MessageRoleName:
    match role:
        case MessageRole.user:
            return "user"
        case MessageRole.assistant:
            return "assistant"
        case MessageRole.tool_result:
            # Listed messages never include one: the query filters them out.
            raise ValueError("a tool_result turn has no wire role")
        case _:
            assert_never(role)


def _to_message(record: MessageRecord) -> Message:
    return Message(
        id=record.id,
        role=_wire_role(record.role),
        text=record.text,
        run_id=record.run_id,
        created_at=clock.to_iso(record.created_at),
    )


async def _require_owned(request: Request, conversation_id: str) -> ConversationRecord:
    """The caller's conversation; another user's is a 404, so its existence is not revealed."""
    caller = require_caller(request)
    record = await service.find_owned_conversation(conversation_id, caller.id)
    if record is None:
        raise AppError("not_found", "conversation not found")
    return record


async def create_conversation(request: Request) -> Conversation:
    caller = require_caller(request)
    now = clock.now()
    record = await service.insert_conversation(
        ConversationRecord(
            id=str(uuid.uuid4()), user_id=caller.id, title=None, created_at=now, updated_at=now
        )
    )
    return _to_conversation(record)


async def list_conversation(
    request: Request, query: Annotated[PageQuery, Query()]
) -> ConversationPage:
    caller = require_caller(request)
    page = await service.list_conversations(
        caller.id,
        cursor=None if query.cursor is MISSING else query.cursor,
        limit=query.limit,
    )
    return ConversationPage(
        items=[_to_conversation(record) for record in page.items], next_cursor=page.next_cursor
    )


async def get_conversation(request: Request, conversation_id: ConversationId) -> ConversationDetail:
    record = await _require_owned(request, conversation_id)
    latest = await get_latest_run(record.id)
    base = _to_conversation(record)
    return ConversationDetail(
        id=base.id,
        title=base.title,
        created_at=base.created_at,
        updated_at=base.updated_at,
        latest_run=None if latest is None else to_wire_run(latest),
    )


async def list_message(
    request: Request, conversation_id: ConversationId, query: Annotated[PageQuery, Query()]
) -> MessagePage:
    record = await _require_owned(request, conversation_id)
    page = await service.list_messages(
        record.id,
        cursor=None if query.cursor is MISSING else query.cursor,
        limit=query.limit,
    )
    return MessagePage(
        items=[_to_message(message) for message in page.items], next_cursor=page.next_cursor
    )


def _title_of(content: str) -> str:
    return " ".join(content.split())[:CONVERSATION_TITLE_MAX_CHARS]


async def send_message(
    request: Request, conversation_id: ConversationId, body: SendMessageBody
) -> SentMessage:
    """Claims the conversation's one active run, stores the message, and hands the run to the
    agent through `RUN_CREATED`. The message is stored after the claim, so a second send during a
    run fails before it writes anything."""
    conversation = await _require_owned(request, conversation_id)
    caller = require_caller(request)
    run = await create_run(conversation.id, caller.id)
    now = clock.now()
    message = MessageRecord(
        id=str(uuid.uuid4()),
        position=0,
        conversation_id=conversation.id,
        run_id=run.id,
        role=MessageRole.user,
        blocks=[{"type": "text", "text": body.content}],
        text=body.content,
        created_at=now,
    )

    async def store(db: service.Tx) -> MessageRecord:
        stored = await service.insert_message(message, db=db)
        await service.touch_conversation(
            conversation.id, _title_of(body.content) or None, now, db=db
        )
        return stored

    try:
        stored = await service.with_transaction(store)
    except Exception:
        # The run was claimed: without this it would hold the conversation's one active slot.
        await _release_claim(run.id)
        raise
    await publish(RUN_CREATED, {"run_id": run.id})
    return SentMessage(message=_to_message(stored), run=to_wire_run(run))


async def _release_claim(run_id: str) -> None:
    try:
        await finish_run(run_id, RunStatus.failed, RunErrorCode.internal)
    except Exception as error:
        log.error("could not release a run claim", {"runId": run_id}, error)


async def read_history(conversation_id: str) -> list[HistoryTurn]:
    """System operation: every stored turn, oldest first, as the API turns to send. A
    `tool_result` turn is a user turn."""
    records = await service.list_all_messages(conversation_id)
    return [
        HistoryTurn(
            role="assistant" if record.role is MessageRole.assistant else "user",
            content=record.blocks,
        )
        for record in records
    ]


async def freeze_prefix(
    conversation_id: str, *, system_prompt: str, tools: list[dict[str, object]]
) -> ConversationPrefix:
    """System operation: binds the conversation to a system prompt and tool list, once, at its
    first run, and returns what is stored. A thinking block is bound to both and to every earlier
    message, so every later request replays exactly these bytes, whatever the servers list then;
    a conversation that already has them keeps them."""
    await service.freeze_prefix(conversation_id, system_prompt, tools)
    prefix = await service.find_prefix(conversation_id)
    if prefix is None:
        raise RuntimeError("conversation prefix was not stored")
    return prefix


async def read_prefix(conversation_id: str) -> ConversationPrefix:
    """System operation: the prompt and tools a conversation was bound to at its first run, with no
    freezing. A resume replays them unchanged (a thinking block is bound to both); it lists no
    server, so it has nothing to freeze."""
    prefix = await service.find_prefix(conversation_id)
    if prefix is None:
        raise RuntimeError("conversation has no stored prefix")
    return prefix


async def count_assistant_turns(conversation_id: str, run_id: str) -> int:
    """System operation: the assistant turns a run has stored in its conversation, which is how
    many of its `AGENT_MAX_TURNS` it has spent."""
    return await service.count_assistant_turns(conversation_id, run_id)


async def append_turns(conversation_id: str, run_id: str, turns: list[NewTurn]) -> None:
    """System operation: stores the turns of one model call together (an assistant turn, and the
    `tool_result` turn answering its tool calls), in one transaction, so a stored `tool_use`
    always has its result."""
    now = clock.now()

    async def store(db: service.Tx) -> None:
        for turn in turns:
            await service.insert_message(
                MessageRecord(
                    id=str(uuid.uuid4()),
                    position=0,
                    conversation_id=conversation_id,
                    run_id=run_id,
                    role=MessageRole(turn.role),
                    blocks=turn.blocks,
                    text=turn.text,
                    created_at=now,
                ),
                db=db,
            )
        await service.touch_conversation(conversation_id, None, now, db=db)

    await service.with_transaction(store)
