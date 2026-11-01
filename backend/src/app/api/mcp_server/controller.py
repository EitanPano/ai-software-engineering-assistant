"""controller.py belongs: the rules the agent module and the accept command call to reach the MCP
servers: list what each enabled server offers (`discover_tools`), find one by name (`find_server`),
call one of its tools (`call_server_tool`), and an admin's accept of a third party's tools
(`read_listing`, `accept_listing`), and the admin's handlers over them.
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
from typing import Annotated, assert_never

from fastapi import Query, Request
from pydantic import MISSING

from app.api.mcp_server import service
from app.api.mcp_server.schema import (
    AcceptListingBody,
    ListingTool,
    McpServer,
    McpServerId,
    McpServerListing,
    McpServerPage,
    PinStatusName,
    ToolChangeName,
    UpdateMcpServerBody,
)
from app.config.env import env
from app.middleware.auth import require_caller
from app.models.auth.type import Caller
from app.models.mcp_server.constants import GITHUB_SERVER, KNOWLEDGE_SERVER
from app.models.mcp_server.enums import PinStatus, ToolChange
from app.models.mcp_server.interface import McpServerRecord
from app.models.mcp_server.type import Discovery, ListedTool, ToolOutcome, same_definition
from app.models.run.enums import ToolCallStatus
from app.models.user.enums import UserRole
from app.services import mcp, tool
from app.services.logger import log
from app.services.mcp import McpUnavailable, ToolDefinitionChanged
from app.services.security.crypto import constant_time_equals
from app.services.utils import clock
from app.services.utils.error import AppError
from app.services.utils.pagination import PageQuery

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
    never touched. The accept handler and `infra/scripts/accept_mcp_server.py` call this."""
    await service.save_pin(server.id, tools, clock.now())


def _assert_admin(caller: Caller) -> None:
    if caller.role is not UserRole.admin:
        raise AppError("forbidden", "insufficient role")


async def find_server_by_id(server_id: str) -> McpServerRecord | None:
    """System operation: the server with this id, enabled or not."""
    return await service.find_by_id(server_id)


def known_tool_names(server: McpServerRecord) -> set[str]:
    """The tools a server is known to offer: its pin, or for `knowledge` (which has none) its last
    listing. A policy is set only for a tool known here or one that already has a row."""
    listing = (
        server.tool_definition if server.name == KNOWLEDGE_SERVER else server.pinned_tool_definition
    )
    return {t.name for t in listing or []}


def _wire_pin_status(status: PinStatus) -> PinStatusName:
    """The edge between the domain enum and the wire's literal; `match` makes mypy fail here when
    a member is added to one and not the other."""
    match status:
        case PinStatus.not_required:
            return "not_required"
        case PinStatus.unpinned:
            return "unpinned"
        case PinStatus.current:
            return "current"
        case PinStatus.changed:
            return "changed"
        case _:
            assert_never(status)


def _wire_change(change: ToolChange) -> ToolChangeName:
    match change:
        case ToolChange.added:
            return "added"
        case ToolChange.removed:
            return "removed"
        case ToolChange.changed:
            return "changed"
        case ToolChange.unchanged:
            return "unchanged"
        case _:
            assert_never(change)


def _to_wire(server: McpServerRecord) -> McpServer:
    """No URL, no token and no tool count: the row's address is the environment's business."""
    return McpServer(
        id=server.id,
        name=server.name,
        enabled=server.enabled,
        pin_status=_wire_pin_status(tool.pin_status(server)),
        created_at=clock.to_iso(server.created_at),
        updated_at=clock.to_iso(server.updated_at),
    )


async def _find_or_404(server_id: str) -> McpServerRecord:
    server = await service.find_by_id(server_id)
    if server is None:
        raise AppError("not_found", "mcp server not found")
    return server


async def _read_for_review(server: McpServerRecord) -> list[ListedTool]:
    """The live listing an admin may review or accept, or the error that says why not: `knowledge`
    has no pin (409), a server that did not answer or whose listing the store cannot hold is a 503,
    and a listing `tool.listing_problem` refuses is a 409 that names no tool."""
    if server.name == KNOWLEDGE_SERVER:
        raise AppError("conflict", "this server has no pin to review")
    live = await read_listing(server)
    if live is None:
        raise AppError("upstream_unavailable", "the server did not answer")
    problem = tool.listing_problem(live)
    if problem is not None:
        raise AppError("conflict", problem)
    return live


def _review_items(server: McpServerRecord, live: list[ListedTool]) -> list[ListingTool]:
    pinned = {t.name: t for t in server.pinned_tool_definition or []}
    shown = {t.name: t for t in live}
    items: list[ListingTool] = []
    for name, change in tool.tool_changes(server.pinned_tool_definition, live).items():
        now = shown.get(name)
        before = pinned.get(name) if change in (ToolChange.changed, ToolChange.removed) else None
        items.append(
            ListingTool(
                name=name,
                change=_wire_change(change),
                description=None if now is None else now.description,
                input_schema=None if now is None else tool.printed_schema(now.input_schema),
                pinned_description=None if before is None else before.description,
                pinned_input_schema=(
                    None if before is None else tool.printed_schema(before.input_schema)
                ),
            )
        )
    return items


async def list_mcp_server(request: Request, query: Annotated[PageQuery, Query()]) -> McpServerPage:
    _assert_admin(require_caller(request))
    page = await service.list_page(
        cursor=None if query.cursor is MISSING else query.cursor, limit=query.limit
    )
    return McpServerPage(
        items=[_to_wire(server) for server in page.items], next_cursor=page.next_cursor
    )


async def get_mcp_server(request: Request, server_id: McpServerId) -> McpServer:
    _assert_admin(require_caller(request))
    return _to_wire(await _find_or_404(server_id))


async def update_mcp_server(
    request: Request, server_id: McpServerId, body: UpdateMcpServerBody
) -> McpServer:
    caller = require_caller(request)
    _assert_admin(caller)
    server = await service.set_enabled(server_id, body.enabled, clock.now())
    if server is None:
        await _find_or_404(server_id)
        raise AppError("conflict", "a server with no accepted listing cannot be enabled")
    log.info(
        "mcp server enabled changed",
        {"account": caller.id, "server": server.name, "enabled": server.enabled},
    )
    return _to_wire(server)


async def get_mcp_server_listing(request: Request, server_id: McpServerId) -> McpServerListing:
    """Reads the server live and stores nothing, a disabled server included."""
    _assert_admin(require_caller(request))
    server = await _find_or_404(server_id)
    live = await _read_for_review(server)
    return McpServerListing(
        mcp_server_id=server.id,
        listing_digest=tool.listing_digest(live),
        items=_review_items(server, live),
    )


async def accept_mcp_server_listing(
    request: Request, server_id: McpServerId, body: AcceptListingBody
) -> McpServer:
    """Pins exactly the listing the admin was shown. The server is read live again; a listing whose
    digest differs from the one shown is a 409 that writes nothing, and what is pinned is what was
    just read, never anything the browser sent."""
    caller = require_caller(request)
    _assert_admin(caller)
    server = await _find_or_404(server_id)
    live = await _read_for_review(server)
    digest = tool.listing_digest(live)
    if not constant_time_equals(digest, body.listing_digest):
        raise AppError("conflict", "the listing changed since it was shown")
    await accept_listing(server, live)
    log.info(
        "mcp server listing accepted",
        {"account": caller.id, "server": server.name, "digest": digest, "tools": len(live)},
    )
    return _to_wire(await _find_or_404(server_id))
