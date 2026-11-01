"""routes.py belongs: the tool_policy module's router. Each endpoint is one `add_api_route`: the
handler, the status and response model, the error responses, the summary and the gates. Every route
is admin-only.
It does not belong: request handling or business rules (`controller.py`) or queries
(`service.py`).
"""

from fastapi import APIRouter, Depends

from app.api.tool_policy.controller import get_tool_policy, set_tool_policy
from app.api.tool_policy.schema import ToolPolicy, ToolPolicySet
from app.middleware.role import require_role
from app.models.user.enums import UserRole
from app.services.utils.openapi import error_responses

router = APIRouter()

require_admin = require_role(UserRole.admin)

router.add_api_route(
    "/{mcpServerId}",
    get_tool_policy,
    methods=["GET"],
    status_code=200,
    response_model=ToolPolicySet,
    response_description="The policy of every tool the server is known to offer",
    responses={**error_responses(401, 403, 404, 500)},
    summary="Read an MCP server's tool policy (admin)",
    tags=["tool-policy"],
    dependencies=[Depends(require_admin)],
)
router.add_api_route(
    "/{mcpServerId}/{toolName}",
    set_tool_policy,
    methods=["PUT"],
    status_code=200,
    response_model=ToolPolicy,
    response_description="The tool's policy, created or changed",
    responses={**error_responses(400, 401, 403, 404, 500)},
    summary="Set a tool's policy (admin)",
    tags=["tool-policy"],
    dependencies=[Depends(require_admin)],
)
