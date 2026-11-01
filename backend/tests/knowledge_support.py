"""Helpers for the `knowledge` suites: the real server (`app.knowledge_main.create_app`) reached in
process under its Compose name, a caller of its `search` tool, and the fixture repository indexed
through the scripted GitHub and Voyage."""

import json
from collections.abc import AsyncIterator
from typing import Final

import httpx
import httpx2
import pytest

from app.api.source.controller import index_source
from app.config.env import env
from app.knowledge_main import create_app
from app.models.mcp_server.type import ListedTool
from app.services import mcp
from app.services.mcp import McpApp, ToolResult
from tests.source_support import admin_bearer, connect

KNOWLEDGE_URL: Final = "http://knowledge:8001/mcp"
TOKEN: Final = env.knowledge_mcp_token

type Wire = dict[str, object]


@pytest.fixture
async def knowledge() -> AsyncIterator[McpApp]:
    """The `knowledge` server, serving in process. Its store is the test database; the caller
    (`mcp.call_tool`) reaches it through the seam, with no socket."""
    app = create_app()
    async with app.lifespan():
        mcp.use_transport(httpx2.ASGITransport(app=app))
        try:
            yield app
        finally:
            mcp.use_transport(None)


async def call_search(query: str, *, token: str | None = TOKEN) -> ToolResult:
    return await mcp.call_tool(KNOWLEDGE_URL, "search", {"query": query}, token=token)


async def listed_tools() -> list[ListedTool]:
    return await mcp.list_tools(KNOWLEDGE_URL, token=TOKEN)


def hits_of(result: ToolResult) -> list[Wire]:
    """The `hits` of a successful result's JSON."""
    assert result.is_error is False, result.text
    document = json.loads(result.text)
    assert isinstance(document, dict)
    hits = document["hits"]
    assert isinstance(hits, list)
    return hits


async def index_fixture(client: httpx.AsyncClient) -> str:
    """Connects and indexes the fixture repository (the `fakes` fixture must be active)."""
    res = await connect(client, admin_bearer())
    assert res.status_code == 201, res.text
    source_id = str(res.json()["id"])
    await index_source(source_id)
    return source_id
