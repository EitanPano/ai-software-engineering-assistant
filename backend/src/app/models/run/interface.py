"""interface.py belongs: the stored `run` and `run_event` records, what `api/run/service.py` reads
and writes. Timestamps are timezone-aware `datetime`; a frozen dataclass despite the name.
It does not belong: the wire shape (`api/run/schema.py`) or value sets (`enums.py`).
"""

from dataclasses import dataclass
from datetime import datetime

from app.models.run.enums import RunErrorCode, RunEventType, RunStatus, ToolCallStatus


@dataclass(frozen=True)
class RunRecord:
    id: str
    conversation_id: str
    user_id: str
    status: RunStatus
    error_code: RunErrorCode | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ToolCallRecord:
    """One tool call of a run, as the loop saw it. `mcp_server_id` and `tool_name` are the server
    row that owns the name and the tool's own name; when no server row owns the name, the id is null
    and `tool_name` is the name as the model used it. `result` is the text the model got back."""

    id: str
    run_id: str
    tool_use_id: str
    mcp_server_id: str | None
    tool_name: str
    arguments: dict[str, object]
    result: str
    status: ToolCallStatus
    created_at: datetime


@dataclass(frozen=True)
class PendingTurn:
    """What a paused run keeps in `run.pending_turn`: the assistant turn's `response.content` whole
    and the `tool_result` blocks already known, in the model's order. The resume appends both as
    two turns; until then neither is in `message`, so history never holds an unanswered
    `tool_use`."""

    content: list[dict[str, object]]
    results: list[dict[str, object]]


@dataclass(frozen=True)
class RunEventRecord:
    run_id: str
    sequence: int
    type: RunEventType
    payload: dict[str, object]
    created_at: datetime
