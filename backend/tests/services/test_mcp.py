"""The MCP seam: our client against a server built by the same module, over an in-process transport.
No network, no key. The server is `build_app` (the `knowledge` server is `serve` over it)."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace

import httpx2
import pytest

from app.config.constants import MCP
from app.models.mcp_server.type import ListedTool
from app.services import mcp
from app.services.mcp import McpUnavailable, ToolFailure, build_app, call_tool, list_tools

TOKEN = "a-test-token-of-at-least-32-characters-long"
URL = "http://lab:8001/mcp"
ECHO = ListedTool(
    name="echo",
    description="Echoes the text.",
    input_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
)
calls: list[tuple[str, dict[str, object]]] = []


async def handler(name: str, arguments: dict[str, object]) -> str:
    calls.append((name, arguments))
    if name == "fail":
        raise ToolFailure("busy")
    if name == "slow":
        await asyncio.sleep(30)
    return f"echo:{arguments.get('text')}"


@pytest.fixture(autouse=True)
def forget_calls() -> None:
    calls.clear()


@pytest.fixture
async def server() -> AsyncIterator[mcp.McpApp]:
    app = build_app(
        [ECHO, replace(ECHO, name="fail"), replace(ECHO, name="slow")],
        handler,
        token=TOKEN,
        allowed_hosts=["lab:*"],
    )
    async with app.lifespan():
        mcp.use_transport(httpx2.ASGITransport(app=app))
        try:
            yield app
        finally:
            mcp.use_transport(None)


@pytest.mark.usefixtures("server")
class TestClient:
    async def test_lists_the_tools_the_server_offers(self) -> None:
        tools = await list_tools(URL, token=TOKEN)

        assert [tool.name for tool in tools] == ["echo", "fail", "slow"]
        assert tools[0] == ECHO

    async def test_calls_a_tool_and_returns_its_text(self) -> None:
        result = await call_tool(URL, "echo", {"text": "hi"}, token=TOKEN)

        assert result.text == "echo:hi"
        assert result.is_error is False
        assert calls == [("echo", {"text": "hi"})]

    async def test_a_tool_failure_is_an_error_result_with_the_fixed_code(self) -> None:
        result = await call_tool(URL, "fail", {"text": "hi"}, token=TOKEN)

        assert result.is_error is True
        assert result.text == "busy"

    async def test_an_unknown_tool_is_an_error_result(self) -> None:
        result = await call_tool(URL, "nothing", {}, token=TOKEN)

        assert result.is_error is True
        assert calls == []

    async def test_keeps_no_session_between_calls(self) -> None:
        for text in ("one", "two", "three"):
            result = await call_tool(URL, "echo", {"text": text}, token=TOKEN)
            assert result.text == f"echo:{text}"
        assert len(await list_tools(URL, token=TOKEN)) == 3

    async def test_runs_calls_concurrently(self) -> None:
        results = await asyncio.gather(
            *(call_tool(URL, "echo", {"text": str(i)}, token=TOKEN) for i in range(4))
        )

        assert sorted(result.text for result in results) == [f"echo:{i}" for i in range(4)]


@pytest.mark.usefixtures("server")
class TestAccess:
    async def test_a_wrong_token_is_unavailable_and_runs_nothing(self) -> None:
        with pytest.raises(McpUnavailable):
            await call_tool(URL, "echo", {"text": "hi"}, token="x" * 40)

        assert calls == []

    async def test_no_token_is_unavailable_and_runs_nothing(self) -> None:
        with pytest.raises(McpUnavailable):
            await list_tools(URL, token=None)
        with pytest.raises(McpUnavailable):
            await call_tool(URL, "echo", {"text": "hi"}, token=None)

        assert calls == []

    async def test_the_server_answers_401_without_the_token(self, server: mcp.McpApp) -> None:
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=server), base_url="http://lab:8001"
        ) as http:
            missing = await http.post("/mcp", json={})
            wrong = await http.post("/mcp", json={}, headers={"Authorization": "Bearer nope"})
            other_scheme = await http.post(
                "/mcp", json={}, headers={"Authorization": f"Basic {TOKEN}"}
            )

        assert [missing.status_code, wrong.status_code, other_scheme.status_code] == [401] * 3
        assert missing.headers["www-authenticate"] == "Bearer"
        assert calls == []

    async def test_health_needs_no_token(self, server: mcp.McpApp) -> None:
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=server), base_url="http://lab:8001"
        ) as http:
            res = await http.get("/health")
            missing = await http.get("/elsewhere")

        assert res.status_code == 200
        assert res.json() == {"status": "ok"}
        assert missing.status_code == 404

    async def test_a_host_the_server_does_not_serve_is_unavailable(self) -> None:
        with pytest.raises(McpUnavailable):
            await list_tools("http://elsewhere:8001/mcp", token=TOKEN)

        assert calls == []


def _refuse(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("refused", request=request)


async def _reason(token: str, transport: httpx2.AsyncBaseTransport | None = None) -> str:
    if transport is not None:
        mcp.use_transport(transport)
    with pytest.raises(McpUnavailable) as failure:
        await call_tool(URL, "echo", {}, token=token)
    return failure.value.reason


@pytest.mark.usefixtures("server")
class TestReason:
    async def test_differs_for_a_refused_token_a_server_error_and_a_refused_connection(
        self,
    ) -> None:
        refused_token = await _reason("x" * 40)  # the fixture's in-process server answers 401
        server_error = await _reason(
            TOKEN, httpx2.MockTransport(lambda _r: httpx2.Response(503, text="x"))
        )
        refused_connection = await _reason(TOKEN, httpx2.MockTransport(_refuse))

        assert (refused_token, server_error, refused_connection) == (
            "http_401",
            "http_503",
            "ConnectError",
        )

    async def test_the_controller_logs_that_reason_and_no_token_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import UTC, datetime

        from app.api.mcp_server import controller
        from app.models.mcp_server.interface import McpServerRecord
        from tests.support import recording_logger

        logger, sink = recording_logger()
        monkeypatch.setattr(controller, "log", logger)
        now = datetime.now(UTC)
        # Any server but `knowledge` is sent no token, so the fixture's server answers 401.
        lab = McpServerRecord("lab", "lab", URL, True, None, now, now)

        await controller.call_server_tool(server=lab, tool_name="echo", arguments={})
        mcp.use_transport(httpx2.MockTransport(lambda _r: httpx2.Response(503, text="x")))
        await controller.call_server_tool(server=lab, tool_name="echo", arguments={})
        mcp.use_transport(httpx2.MockTransport(_refuse))
        await controller.call_server_tool(server=lab, tool_name="echo", arguments={})

        assert len(sink.lines) == 3
        assert [line.rsplit("reason=", 1)[1] for line in sink.lines] == [
            "http_401",
            "http_503",
            "ConnectError",
        ]
        assert TOKEN not in "".join(sink.lines)

    async def test_a_refused_token_logs_one_warning_without_the_token(
        self, server: mcp.McpApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.support import recording_logger

        logger, sink = recording_logger()
        monkeypatch.setattr(mcp, "log", logger)
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=server), base_url="http://lab:8001"
        ) as http:
            await http.post("/mcp", json={}, headers={"Authorization": "Bearer presented-secret"})
            await http.post("/mcp", json={}, headers={"Authorization": f"Bearer {TOKEN}"})

        warnings = [line for line in sink.lines if line.startswith("warning")]
        assert len(warnings) == 1
        assert "/mcp" in warnings[0]
        assert "presented-secret" not in "".join(sink.lines)
        assert TOKEN not in "".join(sink.lines)


class TestFailures:
    async def test_a_connection_that_fails_is_unavailable(self) -> None:
        def refuse(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("refused", request=request)

        mcp.use_transport(httpx2.MockTransport(refuse))
        try:
            with pytest.raises(McpUnavailable):
                await list_tools(URL, token=TOKEN)
            with pytest.raises(McpUnavailable):
                await call_tool(URL, "echo", {}, token=TOKEN)
        finally:
            mcp.use_transport(None)

    async def test_a_server_error_is_unavailable(self) -> None:
        mcp.use_transport(httpx2.MockTransport(lambda _request: httpx2.Response(500, text="boom")))
        try:
            with pytest.raises(McpUnavailable):
                await list_tools(URL, token=TOKEN)
        finally:
            mcp.use_transport(None)

    async def test_an_answer_that_is_not_json_rpc_is_unavailable_and_leaves_the_caller_running(
        self,
    ) -> None:
        mcp.use_transport(
            httpx2.MockTransport(lambda _request: httpx2.Response(200, text="<html>"))
        )
        task = asyncio.current_task()
        try:
            with pytest.raises(McpUnavailable):
                await list_tools(URL, token=TOKEN)
        finally:
            mcp.use_transport(None)

        # The session's own task group failed; it must not have cancelled this task.
        assert task is not None
        assert task.cancelling() == 0
        await asyncio.sleep(0)

    @pytest.mark.usefixtures("server")
    async def test_a_call_past_its_budget_is_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mcp, "MCP", replace(MCP, call_seconds=0.3))

        with pytest.raises(McpUnavailable):
            await call_tool(URL, "slow", {"text": "hi"}, token=TOKEN)

    @pytest.mark.usefixtures("server")
    async def test_a_listing_past_its_budget_is_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def never(_request: httpx2.Request) -> httpx2.Response:
            await asyncio.sleep(30)
            return httpx2.Response(200)

        monkeypatch.setattr(mcp, "MCP", replace(MCP, list_seconds=0.3))
        mcp.use_transport(httpx2.MockTransport(never))
        try:
            with pytest.raises(McpUnavailable):
                await list_tools(URL, token=TOKEN)
        finally:
            mcp.use_transport(None)

    @pytest.mark.usefixtures("server")
    async def test_cancelling_the_caller_cancels_the_call(self) -> None:
        task = asyncio.create_task(call_tool(URL, "slow", {"text": "hi"}, token=TOKEN))
        await asyncio.sleep(0.2)

        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
