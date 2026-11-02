"""routes.py belongs: the mcp_server module's router. Each endpoint is one `add_api_route`: the
handler, the status and response model, the error responses, the summary and the gates. Every route
is admin-only.
It does not belong: request handling or business rules (`controller.py`) or queries
(`service.py`).
"""

from fastapi import APIRouter, Depends

from app.api.mcp_server.controller import (
    accept_mcp_server_listing,
    get_mcp_server,
    get_mcp_server_listing,
    list_mcp_server,
    update_mcp_server,
)
from app.api.mcp_server.schema import McpServer, McpServerListing, McpServerPage
from app.middleware.role import require_role
from app.models.user.enums import UserRole
from app.services.utils.openapi import error_responses

router = APIRouter()

require_admin = require_role(UserRole.admin)

router.add_api_route(
    "",
    list_mcp_server,
    methods=["GET"],
    status_code=200,
    response_model=McpServerPage,
    response_description="A page of MCP servers, newest first",
    responses={**error_responses(400, 401, 403, 500)},
    summary="List MCP servers (admin)",
    tags=["mcp-server"],
    dependencies=[Depends(require_admin)],
)
router.add_api_route(
    "/{id}",
    get_mcp_server,
    methods=["GET"],
    status_code=200,
    response_model=McpServer,
    response_description="The MCP server",
    responses={**error_responses(401, 403, 404, 500)},
    summary="Get an MCP server (admin)",
    tags=["mcp-server"],
    dependencies=[Depends(require_admin)],
)
router.add_api_route(
    "/{id}",
    update_mcp_server,
    methods=["PATCH"],
    status_code=200,
    response_model=McpServer,
    response_description="The MCP server, enabled or disabled",
    responses={**error_responses(400, 401, 403, 404, 409, 500)},
    summary="Enable or disable an MCP server (admin)",
    tags=["mcp-server"],
    dependencies=[Depends(require_admin)],
)
router.add_api_route(
    "/{id}/listing",
    get_mcp_server_listing,
    methods=["GET"],
    status_code=200,
    response_model=McpServerListing,
    response_description="The server's live listing against its pin, to read before accepting",
    responses={**error_responses(401, 403, 404, 409, 500, 503)},
    summary="Read an MCP server's live listing (admin)",
    tags=["mcp-server"],
    dependencies=[Depends(require_admin)],
)
router.add_api_route(
    "/{id}/acceptance",
    accept_mcp_server_listing,
    methods=["POST"],
    status_code=200,
    response_model=McpServer,
    response_description="The MCP server, pinned to the listing that was shown, and enabled",
    responses={**error_responses(400, 401, 403, 404, 409, 500, 503)},
    summary="Accept an MCP server's listing (admin)",
    tags=["mcp-server"],
    dependencies=[Depends(require_admin)],
)
