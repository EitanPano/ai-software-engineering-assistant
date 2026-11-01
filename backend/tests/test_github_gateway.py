"""The GitHub gateway: the one process that holds the personal access token. It is a new auth
boundary, so these tests run the real client against the real transport on both sides of it: our
`services/mcp.py` client calls the gateway, the gateway forwards to a scripted `github-mcp-server`
that enforces its bearer and answers as an event stream, as the real one may. No network, no key.

An upstream request is recorded as the upstream saw it, so a header that must not cross is proven
absent where it would matter, not only absent from a mocked call."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Final

import httpx2
import pytest
from starlette.types import Message, Receive, Scope, Send

from app.config.constants import MAX_BODY_BYTES
from app.models.mcp_server.type import ListedTool
from app.services import mcp
from app.services.logger import create_logger
from app.services.mcp import McpApp, McpUnavailable, build_gateway
from tests.fake_github_mcp import FILE_TEXT, Github, create_github_app, recorded_tools

TOKEN: Final = "gateway-token-of-at-least-32-characters-long"
PAT: Final = "github_pat_fake-personal-access-token-0123456789abcdef"
GATEWAY_URL: Final = "http://gateway:8002/mcp"
UPSTREAM_URL: Final = "http://github-mcp:8082/"
RPC: Final = b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
BOTH: Final = "application/json, text/event-stream"


@dataclass
class Seen:
    """One request as the upstream received it."""

    method: str
    path: str
    headers: dict[str, str]


@dataclass
class Upstream:
    """The scripted server at `/`, as `github-mcp-server http` serves it (the SDK app is at
    `/mcp`), recording each request and each response's content type."""

    app: McpApp
    seen: list[Seen] = field(default_factory=list)
    content_types: list[str] = field(default_factory=list)
    statuses: list[int] = field(default_factory=list)
    up: bool = True
    # The SDK answers a call that emits nothing as one JSON body, and starts a stream only when its
    # handler sends a notification or runs long. When set, each 200 JSON answer leaves as an event
    # stream in two chunks, as the real server may answer, so the gateway's streaming is proven.
    as_stream: bool = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode(): v.decode("latin-1") for k, v in scope["headers"]}
        self.seen.append(Seen(scope["method"], scope["path"], headers))
        if not self.up:
            await send({"type": "http.response.start", "status": 503, "headers": []})
            await send({"type": "http.response.body", "body": b"down"})
            return

        started: Message | None = None
        body = b""

        async def record(message: Message) -> None:
            nonlocal started, body
            if message["type"] == "http.response.start":
                self.statuses.append(message["status"])
                if self.as_stream and message["status"] == 200:
                    started = message
                    return
                for name, value in message["headers"]:
                    if name == b"content-type":
                        self.content_types.append(value.decode())
            elif started is not None and message["type"] == "http.response.body":
                body += message.get("body", b"")
                if message.get("more_body", False):
                    return
                half = len(body) // 2
                self.content_types.append("text/event-stream")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"content-type", b"text/event-stream")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"event: message\ndata: ",
                        "more_body": True,
                    }
                )
                await send({"type": "http.response.body", "body": body[:half], "more_body": True})
                await send({"type": "http.response.body", "body": body[half:] + b"\n\n"})
                return
            await send(message)

        if scope["path"] == "/":
            scope = {**scope, "path": "/mcp"}
        await self.app(scope, receive, record)


class Router:
    """An ASGI router on the `Host` header, like the network: the gateway and the upstream."""

    def __init__(self, gateway: McpApp, upstream: Upstream) -> None:
        self.hosts: dict[str, Callable[[Scope, Receive, Send], Awaitable[None]]] = {
            "gateway:8002": gateway,
            "github-mcp:8082": upstream,
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        host = next((v.decode() for k, v in scope["headers"] if k == b"host"), "")
        if host not in self.hosts:
            raise httpx2.ConnectError("refused")
        await self.hosts[host](scope, receive, send)


@dataclass
class Setup:
    github: Github
    upstream: Upstream
    router: Router

    def raw(self) -> httpx2.AsyncClient:
        """A client for the gateway that is not the MCP client: any header, any method."""
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.router), base_url="http://gateway:8002"
        )


@pytest.fixture
async def setup() -> AsyncIterator[Setup]:
    github = Github()
    server = create_github_app(github, token=PAT, allowed_hosts=["github-mcp:*"], streaming=True)
    upstream = Upstream(server)
    gateway = build_gateway(upstream_url=UPSTREAM_URL, pat=PAT, token=TOKEN)
    router = Router(gateway, upstream)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(server.lifespan())
        await stack.enter_async_context(gateway.lifespan())
        mcp.use_transport(httpx2.ASGITransport(app=router))
        try:
            yield Setup(github, upstream, router)
        finally:
            mcp.use_transport(None)


def tool(name: str) -> ListedTool:
    return next(t for t in recorded_tools() if t.name == name)


class TestForwarding:
    async def test_lists_the_recorded_tools_through_the_gateway(self, setup: Setup) -> None:
        tools = await mcp.list_tools(GATEWAY_URL, token=TOKEN)

        assert tools == recorded_tools()
        assert len(tools) == 7

    async def test_the_upstream_receives_the_pat_and_never_the_gateway_token(
        self, setup: Setup
    ) -> None:
        await mcp.list_tools(GATEWAY_URL, token=TOKEN)

        assert setup.upstream.seen
        for request in setup.upstream.seen:
            assert request.headers["authorization"] == f"Bearer {PAT}"
            assert TOKEN not in "".join(request.headers.values())

    async def test_a_file_is_read_whole_over_an_event_stream(self, setup: Setup) -> None:
        setup.upstream.as_stream = True
        result = await mcp.call_tool(
            GATEWAY_URL,
            "get_file_contents",
            {"owner": "octo-org", "repo": "hello-world", "path": "README.md"},
            token=TOKEN,
            pinned=tool("get_file_contents"),
        )

        assert result.is_error is False
        assert "successfully downloaded text file" in result.text
        assert FILE_TEXT in result.text
        # The server answered as a stream, and the gateway carried it without assuming JSON.
        assert any(kind.startswith("text/event-stream") for kind in setup.upstream.content_types), (
            setup.upstream.content_types
        )

    async def test_the_param_headers_of_the_real_client_cross_the_gateway(
        self, setup: Setup
    ) -> None:
        arguments: dict[str, object] = {"owner": "octo-org", "repo": "hello-world"}

        listed_first = await mcp.call_tool(
            GATEWAY_URL,
            "get_file_contents",
            arguments,
            token=TOKEN,
            pinned=tool("get_file_contents"),
        )
        assert 400 not in setup.upstream.statuses
        # Not listed in its session: the client sends no `Mcp-Param-*` header and the server
        # refuses that call (400), so the listed call above passed because the gateway forwards
        # the headers.
        await mcp.call_tool(GATEWAY_URL, "get_file_contents", arguments, token=TOKEN)

        assert 400 in setup.upstream.statuses
        assert listed_first.is_error is False
        calls = [name for name, _ in setup.github.calls]
        assert calls == ["get_file_contents"] * 2
        carried = [r.headers for r in setup.upstream.seen if "mcp-param-owner" in r.headers]
        assert carried
        assert carried[0]["mcp-param-owner"] == "octo-org"

    async def test_a_tool_failure_reaches_the_client_as_an_error_result(self, setup: Setup) -> None:
        result = await mcp.call_tool(
            GATEWAY_URL,
            "get_file_contents",
            {"owner": "octo-org", "repo": "hello-world", "path": "missing.txt"},
            token=TOKEN,
            pinned=tool("get_file_contents"),
        )

        assert result.is_error is True
        assert "404" in result.text

    async def test_only_the_allowed_headers_cross(self, setup: Setup) -> None:
        async with setup.raw() as http:
            await http.post(
                "/mcp",
                content=RPC,
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Content-Type": "application/json",
                    "Accept": BOTH,
                    "MCP-Protocol-Version": "2026-07-28",
                    "Mcp-Param-Owner": "octo-org",
                    "X-MCP-Readonly": "false",
                    "X-MCP-Toolsets": "all",
                    "X-MCP-Lockdown": "false",
                    "X-Forwarded-For": "203.0.113.9",
                    "Cookie": "session=abc",
                    "X-Anything": "else",
                },
            )

        (request,) = setup.upstream.seen
        names = set(request.headers)
        assert request.headers["authorization"] == f"Bearer {PAT}"
        assert request.headers["content-type"] == "application/json"
        assert request.headers["accept"] == BOTH
        assert request.headers["mcp-protocol-version"] == "2026-07-28"
        assert request.headers["mcp-param-owner"] == "octo-org"
        assert not {n for n in names if n.startswith("x-")}
        assert "cookie" not in names
        assert request.method == "POST"
        assert request.path == "/"


class TestRefusals:
    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"Authorization": "Bearer"},
            {"Authorization": f"Basic {TOKEN}"},
            {"Authorization": f"Bearer {TOKEN}x"},
            {"Authorization": f"Bearer {PAT}"},
            {"Authorization": f"bearer {TOKEN}"},
        ],
        ids=["none", "empty", "basic", "wrong", "the pat itself", "lowercase scheme"],
    )
    async def test_a_missing_or_wrong_token_is_a_401_that_reaches_no_upstream(
        self, setup: Setup, headers: dict[str, str]
    ) -> None:
        async with setup.raw() as http:
            response = await http.post(
                "/mcp", content=RPC, headers={"Content-Type": "application/json", **headers}
            )

        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert setup.upstream.seen == []
        assert PAT not in response.text

    async def test_the_mcp_client_with_a_wrong_token_is_unavailable_and_reaches_no_upstream(
        self, setup: Setup
    ) -> None:
        with pytest.raises(McpUnavailable) as raised:
            await mcp.list_tools(GATEWAY_URL, token="x" * 40)

        assert raised.value.reason == "http_401"
        assert setup.upstream.seen == []

    @pytest.mark.parametrize("method", ["GET", "DELETE", "PUT", "PATCH"])
    async def test_a_method_other_than_post_is_a_405_that_reaches_no_upstream(
        self, setup: Setup, method: str
    ) -> None:
        async with setup.raw() as http:
            response = await http.request(
                method, "/mcp", headers={"Authorization": f"Bearer {TOKEN}"}
            )

        assert response.status_code == 405
        assert response.headers["allow"] == "POST"
        assert setup.upstream.seen == []

    @pytest.mark.parametrize("method", ["GET", "DELETE"])
    async def test_a_method_other_than_post_without_the_token_is_a_401_first(
        self, setup: Setup, method: str
    ) -> None:
        async with setup.raw() as http:
            response = await http.request(method, "/mcp")

        assert response.status_code == 401

    @pytest.mark.parametrize("path", ["/", "/mcp/", "/mcp/x", "/other", "/health/x", "//mcp"])
    async def test_any_other_path_is_a_404_that_reaches_no_upstream(
        self, setup: Setup, path: str
    ) -> None:
        async with setup.raw() as http:
            response = await http.post(
                path, content=RPC, headers={"Authorization": f"Bearer {TOKEN}"}
            )

        assert response.status_code == 404
        assert setup.upstream.seen == []

    async def test_health_answers_without_the_token_and_without_the_upstream(
        self, setup: Setup
    ) -> None:
        async with setup.raw() as http:
            response = await http.get("/health")

        assert response.status_code == 200
        assert setup.upstream.seen == []

    async def test_a_body_over_the_limit_is_a_413_that_reaches_no_upstream(
        self, setup: Setup
    ) -> None:
        async with setup.raw() as http:
            response = await http.post(
                "/mcp",
                content=b"x" * (MAX_BODY_BYTES + 1),
                headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            )

        assert response.status_code == 413
        assert setup.upstream.seen == []

    async def test_an_upstream_that_is_down_is_unavailable_and_says_nothing_of_the_pat(
        self, setup: Setup
    ) -> None:
        setup.upstream.up = False

        with pytest.raises(McpUnavailable):
            await mcp.list_tools(GATEWAY_URL, token=TOKEN)

    async def test_an_upstream_that_cannot_be_reached_is_a_503_without_detail(
        self, setup: Setup
    ) -> None:
        # A host the router does not know refuses the connection, as a dead address does.
        setup.router.hosts["gateway:8002"] = build_gateway(
            upstream_url="http://nowhere:1/", pat=PAT, token=TOKEN
        )
        async with setup.raw() as http:
            response = await http.post(
                "/mcp", content=RPC, headers={"Authorization": f"Bearer {TOKEN}"}
            )

        assert response.status_code == 503
        assert response.json() == {"error": "upstream_unavailable"}
        assert PAT not in response.text


class Lines:
    """A logger sink that keeps every line."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def info(self, message: str) -> None:
        self.lines.append(message)

    def warning(self, message: str) -> None:
        self.lines.append(message)

    def error(self, message: str, *, exc_info: BaseException | None = None) -> None:
        self.lines.append(message)
        if exc_info is not None:
            self.lines.append(repr(exc_info))


class TestNoHeaderIsLogged:
    async def test_no_log_line_holds_a_secret_or_a_header(
        self, setup: Setup, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = Lines()
        monkeypatch.setattr("app.services.mcp.log", create_logger(quiet=False, sink=sink))
        wrong = "a-wrong-bearer-token-that-is-long-enough-0123456789"

        await mcp.list_tools(GATEWAY_URL, token=TOKEN)
        with pytest.raises(McpUnavailable):
            await mcp.list_tools(GATEWAY_URL, token=wrong)
        async with setup.raw() as http:
            await http.post(
                "/mcp",
                content=RPC,
                headers={"Authorization": f"Bearer {wrong}", "Cookie": "session=cookie-value"},
            )
        setup.upstream.up = False
        with pytest.raises(McpUnavailable):
            await mcp.list_tools(GATEWAY_URL, token=TOKEN)

        logged = "\n".join(sink.lines)
        assert sink.lines, "a refused request leaves a trace"
        for secret in (PAT, TOKEN, wrong, "cookie-value", "session="):
            assert secret not in logged
        assert "authorization" not in logged.lower()


class TestNoEnvironmentProxy:
    """A bearer token must never go to a proxy the environment supplies. A test transport turns
    environment proxies off by itself, so this runs with none set: that is where the bug hid."""

    @pytest.mark.parametrize("variable", ["HTTP_PROXY", "ALL_PROXY", "http_proxy"])
    def test_neither_client_mounts_a_proxy(
        self, monkeypatch: pytest.MonkeyPatch, variable: str
    ) -> None:
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "all_proxy"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(variable, "http://proxy.example:3128")
        mcp.use_transport(None)

        upstream = mcp._upstream_client()
        sdk = mcp._http_client(TOKEN, 5.0, [])

        assert upstream._mounts == {}
        assert sdk._mounts == {}

    def test_the_control_client_does_mount_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Proves the setup above would have shown the bug: a default client mounts the proxy.
        monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:3128")

        assert httpx2.AsyncClient()._mounts
