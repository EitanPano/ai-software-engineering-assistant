"""service.py belongs: every query for the `tool_policy` table and nothing else, private to this
directory: only its `controller.py` imports it.
It does not belong: business rules or the decision itself (`controller.py`, `services/tool.py`).
"""

from dataclasses import dataclass

from app.models.tool_policy.enums import PolicyEffect
from app.services.db import Executor, fetch_one


@dataclass(frozen=True)
class _EffectRow:
    effect: str


async def find_effect(
    mcp_server_id: str, tool_name: str, *, db: Executor | None = None
) -> PolicyEffect | None:
    """The effect of the policy row for the tool, or `None` when there is none."""
    row = await fetch_one(
        _EffectRow,
        "select effect from tool_policy where mcp_server_id = %s and tool_name = %s",
        (mcp_server_id, tool_name),
        db=db,
    )
    return None if row is None else PolicyEffect(row.effect)
