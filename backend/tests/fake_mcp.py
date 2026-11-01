"""MCP servers for the agent suites, reached in process through `services/mcp.py`'s transport seam.

`mcp_servers` serves three servers behind one host router: the real `knowledge` server
(`app.knowledge_main.create_app`, on the host `KNOWLEDGE_MCP_URL` defaults to), `lab`, a server of
scripted tools built with the same `build_app`, and the scripted `github-mcp-server`
(`tests/fake_github_mcp.py`) on the host `GITHUB_MCP_URL` defaults to, enforcing the bearer
`GITHUB_MCP_TOKEN` (the tests' environment sets it). A host that is not served answers 503, which
the client reports as unavailable, so `take_down` makes a server "down" without a socket.
`register_lab` writes the `mcp_server` and `tool_policy` rows that make the loop offer and allow
`lab`'s tools, and the pin: `lab` is a third party, so it offers nothing until its tools are
pinned. `accept_github` pins the seeded `github` row, as `accept_mcp_server` does.
`reset_store` restores the seeded rows afterwards.
"""

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Final

import httpx2
import pytest
from psycopg.types.json import Jsonb
from starlette.types import Receive, Scope, Send

from app.config.env import env
from app.knowledge_main import create_app
from app.models.mcp_server.type import ListedTool
from app.models.tool_policy.enums import PolicyEffect
from app.services import mcp
from app.services.db import execute
from app.services.mcp import McpApp, ToolFailure, build_app
from tests.fake_github_mcp import Github, create_github_app

LAB_URL: Final = "http://lab:9000/mcp"
LAB_HOST: Final = "lab:9000"
KNOWLEDGE_HOST: Final = httpx2.URL(env.knowledge_mcp_url).netloc.decode()
GITHUB_HOST: Final = httpx2.URL(env.github_mcp_url).netloc.decode()


def pin_document(tools: Sequence[ListedTool]) -> Jsonb:
    """A listing as the `mcp_server` columns store it."""
    return Jsonb(
        [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
    )


def _schema(*, required: bool) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"] if required else [],
        "additionalProperties": False,
    }


def _tool(name: str, *, required: bool = True) -> ListedTool:
    return ListedTool(
        name=name, description=f"{name} tool", input_schema=_schema(required=required)
    )


LAB_TOOLS: Final = (
    _tool("echo"),
    _tool("boom"),
    _tool("first"),
    _tool("second"),
    _tool("lookup"),
    _tool("loose", required=False),
)


@dataclass
class Lab:
    """What `lab`'s tools were asked to do, and the parallel calls' meeting."""

    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    started: dict[str, asyncio.Event] = field(default_factory=dict)

    async def call(self, name: str, arguments: dict[str, object]) -> str:
        self.calls.append((name, arguments))
        if name == "boom":
            raise RuntimeError("secret internal detail")
        if name in {"first", "second"}:
            other = "second" if name == "first" else "first"
            self.started.setdefault(name, asyncio.Event()).set()
            # Each waits for the other: serial execution would never get past here.
            await asyncio.wait_for(self.started.setdefault(other, asyncio.Event()).wait(), 5)
            return f"{name} done"
        if name == "loose":
            return "ran"
        if name == "fail":
            raise ToolFailure("busy")
        return f"echo:{arguments.get('text')}"


class Hosts:
    """An ASGI router on the `Host` header: the servers that are up."""

    def __init__(self) -> None:
        self.apps: dict[str, McpApp] = {}
        self.down: set[str] = set()
        self.requests: list[str] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        host = next((v.decode() for k, v in scope["headers"] if k == b"host"), "")
        self.requests.append(host)
        app = None if host in self.down else self.apps.get(host)
        if app is None:
            await send({"type": "http.response.start", "status": 503, "headers": []})
            await send({"type": "http.response.body", "body": b"down"})
            return
        await app(scope, receive, send)


@dataclass
class Servers:
    hosts: Hosts
    lab: Lab
    github: Github

    async def accept_github(
        self, tools: Sequence[ListedTool] | None = None, *, enabled: bool = True
    ) -> None:
        """What `accept_mcp_server github` does: pins `tools` (the scripted server's own, by
        default), keeps them as the last listing and enables the seeded row."""
        accepted = list(self.github.tools if tools is None else tools)
        await execute(
            "update mcp_server set pinned_tool_definition = %s, tool_definition = %s, "
            "enabled = %s where name = 'github'",
            (pin_document(accepted), pin_document(accepted), enabled),
        )

    def take_down(self, host: str) -> None:
        self.hosts.down.add(host)

    def bring_up(self, host: str) -> None:
        self.hosts.down.discard(host)

    def reached(self, host: str) -> int:
        """How many requests the host received."""
        return self.hosts.requests.count(host)

    async def register_lab(
        self,
        effects: Mapping[str, PolicyEffect] | None = None,
        *,
        enabled: bool = True,
        default: PolicyEffect | None = PolicyEffect.allow,
        pinned: bool = True,
    ) -> None:
        """`lab` as an `mcp_server` row with a policy row per tool: `effects` by tool name, else
        `default` (`None` writes no row, which is a deny). `pinned` is whether an admin accepted its
        tools; an unpinned third party offers nothing."""
        await execute(
            "insert into mcp_server (id, name, url, enabled, pinned_tool_definition, created_at, "
            "updated_at) values ('lab', 'lab', %s, %s, %s, now(), now())",
            (LAB_URL, enabled, pin_document(LAB_TOOLS) if pinned else None),
        )
        for tool in LAB_TOOLS:
            effect = (effects or {}).get(tool.name, default)
            if effect is not None:
                await execute(
                    "insert into tool_policy (id, mcp_server_id, tool_name, effect, created_at, "
                    "updated_at) values (%s, 'lab', %s, %s, now(), now())",
                    (f"lab-{tool.name}", tool.name, effect),
                )


@pytest.fixture
async def mcp_servers() -> AsyncIterator[Servers]:
    """`knowledge` (real) and `lab` (scripted) in process, with the client's transport pointed at
    them."""
    lab = Lab()
    github = Github()
    hosts = Hosts()
    async with AsyncExitStack() as stack:
        knowledge = create_app()
        await stack.enter_async_context(knowledge.lifespan())
        hosts.apps[KNOWLEDGE_HOST] = knowledge
        lab_app = build_app(LAB_TOOLS, lab.call, token=None, allowed_hosts=[LAB_HOST])
        await stack.enter_async_context(lab_app.lifespan())
        hosts.apps[LAB_HOST] = lab_app
        github_app = create_github_app(
            github, token=env.github_mcp_token, allowed_hosts=[GITHUB_HOST]
        )
        await stack.enter_async_context(github_app.lifespan())
        hosts.apps[GITHUB_HOST] = github_app
        mcp.use_transport(httpx2.ASGITransport(app=hosts))
        try:
            yield Servers(hosts=hosts, lab=lab, github=github)
        finally:
            mcp.use_transport(None)
