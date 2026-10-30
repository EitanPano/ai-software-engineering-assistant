"""schema.py belongs: this directory's contract, the pydantic models that validate requests, type
responses and produce `openapi.json`. The leaf of the directory: routes and controller import it.
It does not belong: business rules or HTTP handling (`controller.py`) or data access
(`service.py`).
"""

from typing import Annotated, Literal

from fastapi import Path
from pydantic import StringConstraints

from app.api.run.schema import Run
from app.models.conversation.constants import MESSAGE_LIMITS
from app.services.utils.api_model import RequestModel, ResponseModel, Timestamp
from app.services.utils.pagination import Page

type MessageRoleName = Literal["user", "assistant"]

# A plain assignment, not a `type` statement: FastAPI reads the `Path` metadata off the annotation.
ConversationId = Annotated[str, Path(alias="id", min_length=1)]

type MessageContent = Annotated[
    str,
    StringConstraints(min_length=MESSAGE_LIMITS.content.min, max_length=MESSAGE_LIMITS.content.max),
]


class Conversation(ResponseModel):
    id: str
    title: str | None
    created_at: Timestamp
    updated_at: Timestamp


class ConversationDetail(Conversation):
    latest_run: Run | None


class ConversationPage(Page[Conversation]):
    """The list endpoint's page; the concrete name is the contract component."""


class Message(ResponseModel):
    id: str
    role: MessageRoleName
    text: str
    run_id: str | None
    created_at: Timestamp


class MessagePage(Page[Message]):
    """The message list's page; the concrete name is the contract component."""


class SendMessageBody(RequestModel):
    content: MessageContent


class SentMessage(ResponseModel):
    message: Message
    run: Run
