"""schema.py belongs: this directory's contract, the pydantic models that validate requests, type
responses and produce `openapi.json`. The leaf of the directory: routes and controller import it.
It does not belong: business rules or HTTP handling (`controller.py`) or data access
(`service.py`).

`ToolPolicy.effect` is null for a tool with no row, which denies; `effects` are the values the
server accepts for that tool, so the browser holds no rule.
"""

from typing import Annotated, Literal

from fastapi import Path

from app.services.utils.api_model import RequestModel, ResponseModel

# The wire's form of `models/tool_policy/enums.py`, inlined in the contract.
type PolicyEffectName = Literal["allow", "ask", "deny"]

# Plain assignments, not `type` statements: FastAPI reads the `Path` metadata off the annotation.
PolicyServerId = Annotated[str, Path(alias="mcpServerId", min_length=1)]
PolicyToolName = Annotated[str, Path(alias="toolName", min_length=1)]


class ToolPolicy(ResponseModel):
    tool_name: str
    effect: PolicyEffectName | None
    effects: list[PolicyEffectName]


class ToolPolicySet(ResponseModel):
    mcp_server_id: str
    items: list[ToolPolicy]


class SetToolPolicyBody(RequestModel):
    effect: PolicyEffectName
