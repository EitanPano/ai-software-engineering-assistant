"""controller.py belongs: the rules the agent module calls to reach the MCP servers: list what each
enabled server offers (`discover_tools`), find one by name (`find_server`) and call one of its
tools (`call_server_tool`). `mcp_server` has no route: no acceptance criterion asks for one, and
the `knowledge` row ships in the migration.
It does not belong: queries (`service.py`) or the protocol (`services/mcp.py`).

Servers are listed concurrently, each in a session of its own. `knowledge`'s address and token are
environment variables, never a row's; any other server's address is its row's, and it is sent no
token.
"""

import asyncio

from app.api.mcp_server import service
from app.config.env import env
from app.models.mcp_server.constants import KNOWLEDGE_SERVER
from app.models.mcp_server.interface import McpServerRecord
from app.models.mcp_server.type import Discovery, ListedTool, ToolOutcome
from app.models.run.enums import ToolCallStatus
from app.services import mcp
from app.services.logger import log
from app.services.mcp import McpUnavailable
from app.services.utils import clock

_UNAVAILABLE_OUTPUT = "the tool is unavailable"


def _endpoint(server: McpServerRecord) -> tuple[str, str | None] | None:
    """Where to reach a server, and the token to send it (only `knowledge` gets one)."""
    if server.name == KNOWLEDGE_SERVER:
        return env.knowledge_mcp_url, env.knowledge_mcp_token
    if server.url is None:
        return None
    return server.url, None


def _log_unavailable(server: McpServerRecord, error: McpUnavailable) -> None:
    log.warning("mcp server unavailable", {"server": server.name, "reason": error.reason})


async def _list_one(server: McpServerRecord) -> list[ListedTool] | None:
    """The server's current listing, or `None` when it did not answer."""
    endpoint = _endpoint(server)
    if endpoint is None:
        return None
    url, token = endpoint
    try:
        return await mcp.list_tools(url, token=token)
    except McpUnavailable as error:
        _log_unavailable(server, error)
        return None


async def discover_tools() -> Discovery:
    """System operation: lists every enabled server and keeps each good listing on its row. A
    server that did not answer is named in `unavailable` and offers its last good listing, if it
    has one, so an outage changes no request."""
    servers = await service.list_enabled()
    listed = await asyncio.gather(*(_list_one(server) for server in servers))
    listings: dict[str, list[ListedTool]] = {}
    unavailable: list[str] = []
    for server, tools in zip(servers, listed, strict=True):
        if tools is None:
            unavailable.append(server.name)
            if server.tool_definition:
                listings[server.name] = server.tool_definition
            continue
        await service.save_listing(server.id, tools, clock.now())
        if tools:
            listings[server.name] = tools
    return Discovery(listings=listings, unavailable=unavailable)


async def find_server(name: str) -> McpServerRecord | None:
    """System operation: the server of this name, enabled or not."""
    return await service.find_by_name(name)


async def call_server_tool(
    *, server: McpServerRecord, tool_name: str, arguments: dict[str, object]
) -> ToolOutcome:
    """System operation: one call of a tool. A server that cannot be reached, or that flags the
    result as an error, is a `failed` outcome, never an exception: the model gets to see it."""
    endpoint = _endpoint(server)
    if endpoint is None:
        return ToolOutcome(ToolCallStatus.failed, _UNAVAILABLE_OUTPUT)
    url, token = endpoint
    try:
        result = await mcp.call_tool(url, tool_name, arguments, token=token)
    except McpUnavailable as error:
        _log_unavailable(server, error)
        return ToolOutcome(ToolCallStatus.failed, _UNAVAILABLE_OUTPUT)
    # NUL cannot be stored in a text column or a JSON document.
    text = result.text.replace("\x00", "")
    status = ToolCallStatus.failed if result.is_error else ToolCallStatus.succeeded
    return ToolOutcome(status, text)
