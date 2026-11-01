"""controller.py belongs: the rule the agent module calls to read what a tool may do, and the
admin's two handlers (read a server's policy, set one tool's). The decision itself is `decide` in
`services/tool.py`: only `allow` runs.
It does not belong: queries (`service.py`).
"""

import uuid
from typing import assert_never

from fastapi import Request

from app.api.mcp_server.controller import find_server_by_id, known_tool_names
from app.api.tool_policy import service
from app.api.tool_policy.schema import (
    PolicyEffectName,
    PolicyServerId,
    PolicyToolName,
    SetToolPolicyBody,
    ToolPolicy,
    ToolPolicySet,
)
from app.middleware.auth import require_caller
from app.models.auth.type import Caller
from app.models.mcp_server.interface import McpServerRecord
from app.models.tool_policy.enums import PolicyEffect
from app.models.user.enums import UserRole
from app.services import tool
from app.services.logger import log
from app.services.utils import clock
from app.services.utils.error import AppError


async def find_effect(*, mcp_server_id: str, tool_name: str) -> PolicyEffect | None:
    """System operation: the effect of the policy row for a tool, read at each call so a stored
    definition never outranks it. `None` is no row, which is a deny."""
    return await service.find_effect(mcp_server_id, tool_name)


def _assert_admin(caller: Caller) -> None:
    if caller.role is not UserRole.admin:
        raise AppError("forbidden", "insufficient role")


def _wire_effect(effect: PolicyEffect) -> PolicyEffectName:
    """The edge between the domain enum and the wire's literal."""
    match effect:
        case PolicyEffect.allow:
            return "allow"
        case PolicyEffect.ask:
            return "ask"
        case PolicyEffect.deny:
            return "deny"
        case _:
            assert_never(effect)


def _domain_effect(effect: PolicyEffectName) -> PolicyEffect:
    return PolicyEffect(effect)


def _to_wire(server: McpServerRecord, tool_name: str, effect: PolicyEffect | None) -> ToolPolicy:
    return ToolPolicy(
        tool_name=tool_name,
        effect=None if effect is None else _wire_effect(effect),
        effects=[_wire_effect(e) for e in tool.effects_for(server.name, tool_name)],
    )


async def _server_or_404(server_id: str) -> McpServerRecord:
    server = await find_server_by_id(server_id)
    if server is None:
        raise AppError("not_found", "mcp server not found")
    return server


async def get_tool_policy(request: Request, mcp_server_id: PolicyServerId) -> ToolPolicySet:
    """Every tool the server is known to offer (its pin, or `knowledge`'s last listing) and every
    tool with a row; a tool with no row has `effect` null, which denies."""
    _assert_admin(require_caller(request))
    server = await _server_or_404(mcp_server_id)
    rows = await service.list_for_server(server.id)
    names = sorted(known_tool_names(server) | rows.keys())
    return ToolPolicySet(
        mcp_server_id=server.id,
        items=[_to_wire(server, name, rows.get(name)) for name in names],
    )


async def set_tool_policy(
    request: Request,
    mcp_server_id: PolicyServerId,
    tool_name: PolicyToolName,
    body: SetToolPolicyBody,
) -> ToolPolicy:
    """Creates or changes the one row. An unknown server or tool is a 404, checked before the
    effect is: a known tool's effect outside `effects_for` is a 400 that writes nothing."""
    caller = require_caller(request)
    _assert_admin(caller)
    server = await _server_or_404(mcp_server_id)
    rows = await service.list_for_server(server.id)
    if tool_name not in known_tool_names(server) and tool_name not in rows:
        raise AppError("not_found", "tool not found")
    effect = _domain_effect(body.effect)
    if effect not in tool.effects_for(server.name, tool_name):
        raise AppError(
            "validation_failed",
            "invalid body",
            [{"path": "effect", "message": "this tool cannot be set to that effect"}],
        )
    stored = await service.upsert_effect(
        str(uuid.uuid4()), server.id, tool_name, effect, clock.now()
    )
    log.info(
        "tool policy set",
        {"account": caller.id, "server": server.name, "tool": tool_name, "effect": stored.value},
    )
    return _to_wire(server, tool_name, stored)
