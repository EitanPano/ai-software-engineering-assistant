"""The MCP seam: the only importer of the `mcp` SDK. It is our client of other servers and the
builder of the one we serve (`knowledge`), both on Streamable HTTP, never Anthropic's MCP connector:
a connector runs tool calls where the approval gate cannot intercept them (`.doc/conventions.md`).

Client: one listing or one call is one session, in a task of its own. An approval must pause a run
with no process waiting, and a held session would tie a run to one connection; the own task keeps a
failing session's task group from cancelling the caller. Every transport failure, a timeout and a
malformed answer are one `McpUnavailable`; the caller never sees the SDK's exceptions. A shutdown's
cancellation still reaches the caller.

Server: `build_app` serves hand-written definitions, not ones derived from a signature, because
`strict` tool use needs `additionalProperties: false`. It is stateless (no session to lose, any
replica answers), refuses a request without the bearer token before the SDK sees it, checks the
`Host` header against the names it is reached by (the SDK's DNS rebinding protection), and answers
`GET /health` without the token and without touching a store.

A test replaces the transport (`use_transport`) like `services/voyage.py` replaces its client, and
reaches a server with no socket.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Final

import httpx2
import mcp_types as types
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config.constants import MCP
from app.models.mcp_server.constants import SEARCH_TOOL
from app.models.mcp_server.type import ListedTool
from app.models.search.enums import ToolSearchCode
from app.models.search.type import ToolSearchFailed
from app.services.logger import log
from app.services.security.crypto import constant_time_equals

BEARER: Final = "Bearer "
type ToolCaller = Callable[[str, dict[str, object]], Awaitable[str]]

_state: dict[str, httpx2.AsyncBaseTransport] = {}


class McpUnavailable(Exception):  # noqa: N818  # named for what the caller reports
    """The server could not be reached or did not answer in time, or answered something that is
    not MCP. Safe to retry later; the cause is chained for the log. `reason` is one short word for
    the log: `http_<status>` when the server answered an error status (the SDK reports a 401 and a
    503 as the same error), otherwise the class of the leaf exception, or `timeout`."""

    def __init__(self, reason: str = "unavailable") -> None:
        super().__init__(reason)
        self.reason = reason


def _leaf(error: BaseException) -> BaseException:
    """The first exception inside a (nested) group: the SDK's task group wraps every failure."""
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return error


class ToolFailure(Exception):  # noqa: N818  # named for the error result it becomes
    """A tool's failure, as the server reports it: one fixed code, never exception text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ToolResult:
    """What a call returned: its text blocks joined, and whether the server flagged an error."""

    text: str
    is_error: bool


def use_transport(transport: httpx2.AsyncBaseTransport | None) -> None:
    """Replaces the HTTP transport (a test points it at an in-process server); `None` forgets it."""
    if transport is None:
        _state.pop("transport", None)
    else:
        _state["transport"] = transport


def _http_client(token: str | None, seconds: float, errors: list[int]) -> httpx2.AsyncClient:
    """`errors` collects the status of every error response: the SDK turns them all into one
    error, and the log needs to tell a refused token from an outage."""
    headers = {} if token is None else {"Authorization": f"{BEARER}{token}"}

    async def note(response: httpx2.Response) -> None:
        if response.status_code >= 400:
            errors.append(response.status_code)

    return httpx2.AsyncClient(
        transport=_state.get("transport"),
        headers=headers,
        timeout=httpx2.Timeout(seconds),
        event_hooks={"response": [note]},
    )


async def _session[T](
    url: str, token: str | None, seconds: float, work: Callable[[Client], Awaitable[T]]
) -> T:
    errors: list[int] = []
    try:
        async with (
            _http_client(token, seconds, errors) as http,
            Client(streamable_http_client(url, http_client=http)) as client,
        ):
            return await work(client)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        # An `ExceptionGroup` from the session's task group lands here too.
        reason = f"http_{errors[0]}" if errors else type(_leaf(error)).__name__
        raise McpUnavailable(reason) from error


async def _in_own_task[T](
    url: str, token: str | None, seconds: float, work: Callable[[Client], Awaitable[T]]
) -> T:
    """Runs one session in a task of its own, so its task group's failure cannot cancel the
    caller. A timeout ends the task; the caller's own cancellation ends it too."""
    task = asyncio.create_task(_session(url, token, seconds, work))
    try:
        return await asyncio.wait_for(task, seconds)
    except TimeoutError as error:
        raise McpUnavailable("timeout") from error


async def list_tools(url: str, *, token: str | None) -> list[ListedTool]:
    """The tools the server at `url` offers, or `McpUnavailable`."""

    async def work(client: Client) -> list[ListedTool]:
        listing = await client.list_tools()
        return [
            ListedTool(
                name=tool.name,
                description=tool.description or "",
                input_schema=dict(tool.input_schema),
            )
            for tool in listing.tools
        ]

    return await _in_own_task(url, token, MCP.list_seconds, work)


async def call_tool(
    url: str, name: str, arguments: dict[str, object], *, token: str | None
) -> ToolResult:
    """One call of `name`, or `McpUnavailable`. A tool that fails is an `is_error` result, not an
    exception: the model gets to see it."""

    async def work(client: Client) -> ToolResult:
        result = await client.call_tool(name, arguments)
        texts = [block.text for block in result.content if isinstance(block, types.TextContent)]
        return ToolResult(text="\n".join(texts), is_error=result.is_error)

    return await _in_own_task(url, token, MCP.call_seconds, work)


async def _send_json(
    send: Send, status: int, body: bytes, headers: Sequence[tuple[bytes, bytes]]
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), *headers],
        }
    )
    await send({"type": "http.response.body", "body": body})


class McpApp:
    """The ASGI app of a server: the bearer check and `/health` in front of the SDK's app."""

    def __init__(
        self,
        inner: ASGIApp,
        lifespan: Callable[[], AsyncIterator[None]],
        token: str | None,
        around: Callable[[], AbstractAsyncContextManager[None]] | None = None,
    ) -> None:
        self._inner = inner
        self._token = token
        # What the SDK's app needs while it serves (its session manager's task group); a test
        # enters it with no server.
        self.lifespan = asynccontextmanager(lifespan)
        # What the process needs around it (the store, for `knowledge`), entered first.
        self._around = around

    async def _serve_lifespan(self, receive: Receive, send: Send) -> None:
        """The ASGI lifespan: `around`, then the SDK's own, for as long as the server runs. Written
        by hand because the two must be entered and left in this one task."""
        await receive()  # lifespan.startup
        stack = AsyncExitStack()
        try:
            if self._around is not None:
                await stack.enter_async_context(self._around())
            await stack.enter_async_context(self.lifespan())
        except Exception as error:
            await send({"type": "lifespan.startup.failed", "message": type(error).__name__})
            await stack.aclose()
            raise
        await send({"type": "lifespan.startup.complete"})
        await receive()  # lifespan.shutdown
        try:
            await stack.aclose()
        except Exception as error:
            await send({"type": "lifespan.shutdown.failed", "message": type(error).__name__})
            raise
        await send({"type": "lifespan.shutdown.complete"})

    def _allowed(self, scope: Scope) -> bool:
        if self._token is None:
            return True
        presented = ""
        for name, value in scope["headers"]:
            if name == b"authorization":
                presented = value.decode("latin-1")
        if not presented.startswith(BEARER):
            return False
        return constant_time_equals(presented[len(BEARER) :], self._token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._serve_lifespan(receive, send)
            return
        if scope["type"] != "http":
            return
        if scope["path"] == "/health":
            await _send_json(send, 200, b'{"status":"ok"}', [])
        elif scope["path"] != "/mcp":
            await _send_json(send, 404, b'{"error":"not_found"}', [])
        elif not self._allowed(scope):
            # The path only, never the presented value: a mismatch after a rotation must not read
            # as an outage, and a probe of the one boundary leaves a trace.
            log.warning("mcp request refused: bad credentials", {"path": scope["path"]})
            await _send_json(
                send, 401, b'{"error":"unauthenticated"}', [(b"www-authenticate", b"Bearer")]
            )
        else:
            await self._inner(scope, receive, send)


def build_app(
    tools: Sequence[ListedTool],
    call: ToolCaller,
    *,
    token: str | None,
    allowed_hosts: Sequence[str],
    around: Callable[[], AbstractAsyncContextManager[None]] | None = None,
) -> McpApp:
    """A stateless MCP server over `tools`. `call(name, arguments)` returns the text of a result or
    raises `ToolFailure`; a name that is not listed fails as `unknown_tool` before `call` runs.
    `token` is the bearer secret (`None` serves anyone, for a test of the SDK only)."""
    by_name = {tool.name: tool for tool in tools}

    async def on_list_tools(
        ctx: ServerRequestContext[None, object], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        del ctx, params
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=tool.name, description=tool.description, input_schema=tool.input_schema
                )
                for tool in tools
            ]
        )

    async def on_call_tool(
        ctx: ServerRequestContext[None, object], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        del ctx
        try:
            if params.name not in by_name:
                raise ToolFailure("unknown_tool")
            text = await call(params.name, dict(params.arguments or {}))
        except ToolFailure as failure:
            return types.CallToolResult(
                content=[types.TextContent(text=failure.code)], is_error=True
            )
        return types.CallToolResult(content=[types.TextContent(text=text)])

    server: Server[None] = Server(
        "knowledge", on_list_tools=on_list_tools, on_call_tool=on_call_tool
    )
    starlette = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(allowed_hosts),
            allowed_origins=[],
        ),
    )

    async def lifespan() -> AsyncIterator[None]:
        async with starlette.router.lifespan_context(starlette):
            yield

    return McpApp(starlette, lifespan, token, around)


type Search = Callable[[str], Awaitable[str]]


def serve(
    search: Search,
    *,
    token: str,
    allowed_hosts: Sequence[str],
    around: Callable[[], AbstractAsyncContextManager[None]] | None = None,
) -> McpApp:
    """The `knowledge` server: one tool, `search`, over `search`. A call whose arguments are not
    exactly `{ query: string }` is `invalid_query`; any failure of the search is its fixed code, and
    anything unexpected is `search_unavailable`: exception text never leaves the process."""

    async def call(name: str, arguments: dict[str, object]) -> str:
        del name
        query = arguments.get("query")
        if set(arguments) != {"query"} or not isinstance(query, str):
            raise ToolFailure(ToolSearchCode.invalid_query.value)
        try:
            return await search(query)
        except ToolSearchFailed as failure:
            raise ToolFailure(failure.code.value) from None
        except Exception as error:
            log.error("knowledge search failed", {"reason": type(error).__name__}, error)
            raise ToolFailure(ToolSearchCode.search_unavailable.value) from None

    return build_app([SEARCH_TOOL], call, token=token, allowed_hosts=allowed_hosts, around=around)
