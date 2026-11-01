"""type.py belongs: the shapes of an approval that several layers share and that are not stored
records: a call the loop holds for a person, and what a decision answered.
It does not belong: stored records (`interface.py`) or value sets (`enums.py`).
"""

from dataclasses import dataclass
from datetime import datetime

from app.models.approval.enums import ApprovalDecision


@dataclass(frozen=True)
class HeldCall:
    """A tool call that passed every gate and waits for a person: the model's `tool_use` id, the
    server row that owns the name and the tool's own name, and the arguments the person reads."""

    tool_use_id: str
    mcp_server_id: str | None
    tool_name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class DecidedApproval:
    """What a decision recorded. `resumes` is true for the decision that left nothing undecided
    and so flipped the run back to running: exactly one decision of a pause says so."""

    id: str
    run_id: str
    tool_use_id: str
    decision: ApprovalDecision
    decided_at: datetime
    resumes: bool
