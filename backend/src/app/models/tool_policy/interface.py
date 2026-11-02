"""interface.py belongs: the stored `tool_policy` record, what `api/tool_policy/service.py` reads. A
frozen dataclass despite the name. There is one row per (server, tool); no row means deny.
It does not belong: value sets (`enums.py`).
"""

from dataclasses import dataclass
from datetime import datetime

from app.models.tool_policy.enums import PolicyEffect


@dataclass(frozen=True)
class ToolPolicyRecord:
    id: str
    mcp_server_id: str
    tool_name: str
    effect: PolicyEffect
    created_at: datetime
    updated_at: datetime
