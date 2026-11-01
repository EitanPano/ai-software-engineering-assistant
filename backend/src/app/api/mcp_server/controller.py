"""controller.py belongs: the rules the agent module and the accept command call to reach the MCP
servers: list what each enabled server offers (`discover_tools`), find one by name (`find_server`),
call one of its tools (`call_server_tool`), and an admin's accept of a third party's tools
(`read_listing`, `accept_listing`). `mcp_server` has no route: no acceptance criterion asks for
one, and the `knowledge` and `github` rows ship in migrations.
It does not belong: queries (`service.py`) or the protocol (`services/mcp.py`).

Servers are listed concurrently, each in a session of its own. `knowledge`'s and `github`'s
addresses and tokens are environment variables, never a row's; any other server's address is its
row's, and it is sent no token.

The pin. `knowledge` is ours and is offered as it lists. Every other server offers only the tools an
admin accepted (`pinned_tool_definition`) whose live listing still equals the pin; while the server
is down it offers the pin itself, so an outage changes no request; with no pin it offers nothing and
is not even listed. A call lists again in its own session and calls nothing on a difference.
"""

import asyncio

from app.api.mcp_server import service
from app.config.env import env
from app.models.mcp_server.constants import GITHUB_SERVER, KNOWLEDGE_SERVER
from app.models.mcp_server.interface import McpServerRecord
from app.models.mcp_server.type import Discovery, ListedTool, ToolOutcome, same_definition
from app.models.run.enums import ToolCallStatus
from app.services import mcp
from app.services.logger import log
from app.services.mcp import McpUnavailable, ToolDefinitionChanged
from app.services.utils import clock

_UNAVAILABLE_OUTPUT = "the tool is unavailable"
# The agent's own policy text for a denied call, so the model reads one wording for every refusal.
_DENIED_OUTPUT = "this tool is not permitted"


def _endpoint(server: McpServerRecord) -> tuple[str, str | None] | None:
    """Where to reach a server, and the token to send it (`knowledge` and `github` get one)."""
    if server.name == KNOWLEDGE_SERVER:
        return env.knowledge_mcp_url, env.knowledge_mcp_token
    if server.name == GITHUB_SERVER:
        return env.github_mcp_url, env.github_mcp_token
    if server.url is None:
        return None
    return server.url, None


def _log_unavailable(server: McpServerRecord, error: McpUnavailable) -> None:
    log.warning("mcp server unavailable", {"server": server.name, "reason": error.reason})


def _log_changed(server: McpServerRecord, tool_name: str) -> None:
    """The server and the tool, never the definition: a changed description is attacker text."""
    log.warning("tool definition changed", {"server": server.name, "tool": tool_name})


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


def _offered(server: McpServerRecord, live: list[ListedTool] | None) -> list[ListedTool]:
    """What a server contributes to the request. `live` is its listing, or `None` when it did not
    answer."""
    if server.name == KNOWLEDGE_SERVER:
        return (server.tool_definition if live is None else live) or []
    pinned = server.pinned_tool_definition or []
    if live is None:
        return pinned
    # A pinned tool whose listing differs, or is gone, is not offered; one the pin lacks never is.
    # By name first: comparing every pair canonicalises each definition once per pin entry.
    seen = {tool.name: tool for tool in live}
    return [tool for tool in pinned if tool.name in seen and same_definition(tool, seen[tool.name])]


async def discover_tools() -> Discovery:
    """System operation: lists every enabled server and keeps each good listing on its row. A
    server that did not answer is named in `unavailable` and offers its last good listing (its pin,
    for a third party), if it has one, so an outage changes no request. A third party with no pin
    is skipped whole: nothing is offered and no notice is written."""
    servers = [
        server
        for server in await service.list_enabled()
        if server.name == KNOWLEDGE_SERVER or server.pinned_tool_definition is not None
    ]
    listed = await asyncio.gather(*(_list_one(server) for server in servers))
    listings: dict[str, list[ListedTool]] = {}
    unavailable: list[str] = []
    for server, tools in zip(servers, listed, strict=True):
        if tools is None:
            unavailable.append(server.name)
        else:
            await service.save_listing(server.id, tools, clock.now())
        offered = _offered(server, tools)
        if offered:
            listings[server.name] = offered
    return Discovery(listings=listings, unavailable=unavailable)


async def find_server(name: str) -> McpServerRecord | None:
    """System operation: the server of this name, enabled or not."""
    return await service.find_by_name(name)


async def call_server_tool(
    *, server: McpServerRecord, tool_name: str, arguments: dict[str, object]
) -> ToolOutcome:
    """System operation: one call of a tool. A server that cannot be reached, or that flags the
    result as an error, is a `failed` outcome, never an exception: the model gets to see it. A
    third party's tool that is not pinned, or whose live definition differs from its pin (checked
    in the call's own session), is `denied` and nothing is called."""
    endpoint = _endpoint(server)
    if endpoint is None:
        return ToolOutcome(ToolCallStatus.failed, _UNAVAILABLE_OUTPUT)
    url, token = endpoint
    pinned: ListedTool | None = None
    if server.name != KNOWLEDGE_SERVER:
        pinned = next(
            (tool for tool in server.pinned_tool_definition or [] if tool.name == tool_name), None
        )
        if pinned is None:
            log.warning("tool is not pinned", {"server": server.name, "tool": tool_name})
            return ToolOutcome(ToolCallStatus.denied, _DENIED_OUTPUT)
    try:
        result = await mcp.call_tool(url, tool_name, arguments, token=token, pinned=pinned)
    except ToolDefinitionChanged:
        _log_changed(server, tool_name)
        return ToolOutcome(ToolCallStatus.denied, _DENIED_OUTPUT)
    except McpUnavailable as error:
        _log_unavailable(server, error)
        return ToolOutcome(ToolCallStatus.failed, _UNAVAILABLE_OUTPUT)
    # NUL cannot be stored in a text column or a JSON document.
    text = result.text.replace("\x00", "")
    status = ToolCallStatus.failed if result.is_error else ToolCallStatus.succeeded
    return ToolOutcome(status, text)


async def read_listing(server: McpServerRecord) -> list[ListedTool] | None:
    """System operation: the server's live listing, whole, for an admin to read before accepting
    it, or `None` when it has no address or did not answer."""
    return await _list_one(server)


async def accept_listing(server: McpServerRecord, tools: list[ListedTool]) -> None:
    """System operation: an admin accepted exactly `tools` (what `read_listing` returned and the
    admin read). They become the pin and the last listing and the server is enabled; a policy row is
    never touched. Only `infra/scripts/accept_mcp_server.py` calls this."""
    await service.save_pin(server.id, tools, clock.now())
