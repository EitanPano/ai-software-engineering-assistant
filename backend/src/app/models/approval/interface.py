"""interface.py belongs: the stored `approval` record, what `api/run/service.py` reads and writes
(a pause and a last decision commit rows with the run's, so the queries live beside the run's). A
frozen dataclass despite the name.
It does not belong: the wire shape (`api/approval/schema.py`) or value sets (`enums.py`).
"""

from dataclasses import dataclass
from datetime import datetime

from app.models.approval.enums import ApprovalDecision


@dataclass(frozen=True)
class ApprovalRecord:
    """One tool call waiting for a person. `arguments_digest` is the SHA-256 of the call's stored
    arguments, so a decision names what the person was shown. `decision` and `decided_at` are null
    until decided."""

    id: str
    run_id: str
    tool_call_id: str
    user_id: str
    arguments_digest: str
    decision: ApprovalDecision | None
    created_at: datetime
    decided_at: datetime | None


@dataclass(frozen=True)
class ApprovalCall:
    """An approval with the stored call it binds: the model's `tool_use` id, the server row that
    owns the name and the tool's own name, and the arguments as stored."""

    approval: ApprovalRecord
    tool_use_id: str
    mcp_server_id: str | None
    tool_name: str
    arguments: dict[str, object]
