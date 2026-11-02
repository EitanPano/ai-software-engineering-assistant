"""interface.py belongs: the stored `conversation` and `message` records, what
`api/conversation/service.py` reads and writes. A message's `blocks` are the API turn's content
blocks as JSON, stored unchanged; `text` is the concatenated text blocks, what the wire shows. A
frozen dataclass despite the name.
It does not belong: the wire shape (`api/conversation/schema.py`) or value sets (`enums.py`).
"""

from dataclasses import dataclass
from datetime import datetime

from app.models.conversation.enums import MessageRole


@dataclass(frozen=True)
class ConversationRecord:
    id: str
    user_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MessageRecord:
    id: str
    position: int
    conversation_id: str
    run_id: str | None
    role: MessageRole
    blocks: list[object]
    text: str
    created_at: datetime
