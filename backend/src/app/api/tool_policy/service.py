"""service.py belongs: every query for the `tool_policy` table and nothing else, private to this
directory: only its `controller.py` imports it.
It does not belong: business rules or the decision itself (`controller.py`, `services/tool.py`).
"""

from dataclasses import dataclass
from datetime import datetime

from app.models.tool_policy.enums import PolicyEffect
from app.services.db import Executor, fetch_all, fetch_one


@dataclass(frozen=True)
class _EffectRow:
    effect: str


@dataclass(frozen=True)
class _NamedEffect:
    tool_name: str
    effect: str


async def list_for_server(
    mcp_server_id: str, *, db: Executor | None = None
) -> dict[str, PolicyEffect]:
    """The effect of every policy row of a server, by tool name."""
    rows = await fetch_all(
        _NamedEffect,
        "select tool_name, effect from tool_policy where mcp_server_id = %s",
        (mcp_server_id,),
        db=db,
    )
    return {row.tool_name: PolicyEffect(row.effect) for row in rows}


async def upsert_effect(
    row_id: str,
    mcp_server_id: str,
    tool_name: str,
    effect: PolicyEffect,
    now: datetime,
    *,
    db: Executor | None = None,
) -> PolicyEffect:
    """Creates the one row of (server, tool) or changes its effect, and returns the stored effect.
    `row_id` is used only on create."""
    row = await fetch_one(
        _EffectRow,
        "insert into tool_policy (id, mcp_server_id, tool_name, effect, created_at, updated_at) "
        "values (%s, %s, %s, %s, %s, %s) "
        "on conflict on constraint tool_policy_server_tool_key "
        "do update set effect = excluded.effect, updated_at = excluded.updated_at "
        "returning effect",
        (row_id, mcp_server_id, tool_name, effect, now, now),
        db=db,
    )
    if row is None:
        raise RuntimeError("tool_policy upsert returned no row")
    return PolicyEffect(row.effect)


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
