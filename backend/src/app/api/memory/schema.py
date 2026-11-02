"""schema.py belongs: this directory's contract, the pydantic models that validate requests, type
responses and produce `openapi.json`, and `MemoryExtraction`, the shape the extraction side call is
asked for (off the wire, so not a contract component). The leaf of the directory: routes and
controller import it.
It does not belong: business rules or HTTP handling (`controller.py`) or data access
(`service.py`).
"""

from typing import Annotated

from fastapi import Path

from app.services.utils.api_model import ResponseModel, Timestamp
from app.services.utils.pagination import Page

# A plain assignment, not a `type` statement: FastAPI reads the `Path` metadata off the annotation.
MemoryId = Annotated[str, Path(alias="id", min_length=1)]


class Memory(ResponseModel):
    id: str
    content: str
    conversation_id: str
    created_at: Timestamp


class MemoryPage(Page[Memory]):
    """The list endpoint's page; the concrete name is the contract component."""


class MemoryExtraction(ResponseModel):
    """What the extraction side call returns: the durable facts one message states. Never on the
    wire; `parse_turn` validates the model's text against it."""

    facts: list[str]
