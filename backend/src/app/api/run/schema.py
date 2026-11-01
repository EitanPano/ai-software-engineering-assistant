"""schema.py belongs: the run's contract, the pydantic models that validate requests, type
responses and produce `openapi.json`. The leaf of the directory; `RunEvent` is the item type of the
SSE stream, which `app/openapi.py` moves from `itemSchema` to `schema` so the generated client
types the stream.
It does not belong: business rules or HTTP handling (`controller.py`) or data access
(`service.py`).
"""

from typing import Annotated, Literal

from fastapi import Path
from pydantic import Field, RootModel

from app.services.utils.api_model import ResponseModel, Timestamp

type RunStatusName = Literal["queued", "running", "completed", "failed"]
type RunErrorCodeName = Literal[
    "refused", "truncated", "turn_limit", "upstream_unavailable", "interrupted", "internal"
]
type ToolCallStatusName = Literal["succeeded", "failed", "denied"]

# A plain assignment, not a `type` statement: FastAPI reads the `Path` metadata off the annotation.
RunId = Annotated[str, Path(alias="id", min_length=1)]

# The `Last-Event-ID` header: the sequence of the last event the client holds. Lax, as a header
# arrives as text.
type EventSequence = Annotated[int, Field(ge=0)]


class Run(ResponseModel):
    id: str
    status: RunStatusName
    error_code: RunErrorCodeName | None
    created_at: Timestamp


class RunStartedEvent(ResponseModel):
    type: Literal["run_started"] = "run_started"
    sequence: int
    created_at: Timestamp


class TextDeltaEvent(ResponseModel):
    type: Literal["text_delta"] = "text_delta"
    sequence: int
    created_at: Timestamp
    text: str


class ToolCallStartedEvent(ResponseModel):
    type: Literal["tool_call_started"] = "tool_call_started"
    sequence: int
    created_at: Timestamp
    tool_use_id: str
    name: str
    input: dict[str, object]


class ToolCallFinishedEvent(ResponseModel):
    type: Literal["tool_call_finished"] = "tool_call_finished"
    sequence: int
    created_at: Timestamp
    tool_use_id: str
    status: ToolCallStatusName
    output: str


class McpServerUnavailableEvent(ResponseModel):
    type: Literal["mcp_server_unavailable"] = "mcp_server_unavailable"
    sequence: int
    created_at: Timestamp
    name: str


class RunFinishedEvent(ResponseModel):
    type: Literal["run_finished"] = "run_finished"
    sequence: int
    created_at: Timestamp
    status: Literal["completed", "failed"]
    error_code: RunErrorCodeName | None


class RunEvent(
    RootModel[
        Annotated[
            RunStartedEvent
            | TextDeltaEvent
            | ToolCallStartedEvent
            | ToolCallFinishedEvent
            | McpServerUnavailableEvent
            | RunFinishedEvent,
            Field(discriminator="type"),
        ]
    ]
):
    """One event of the stream, a union on `type`; the concrete name is the contract component."""
