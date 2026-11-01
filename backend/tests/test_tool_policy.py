"""The admin's tool-policy endpoints: the request-schema rule, then reading and setting a server's
policy on the real store, with `lab` and the scripted `github-mcp-server` in process."""

import uuid
from dataclasses import dataclass

import httpx
import pytest
from fastapi import Depends
from pydantic import ValidationError

from app.api.tool_policy import controller as tool_policy
from app.api.tool_policy.schema import SetToolPolicyBody
from app.middleware.auth import require_auth
from app.models.mcp_server.type import ListedTool
from app.models.tool_policy.constants import GITHUB_ALLOWABLE_TOOLS
from app.models.tool_policy.enums import PolicyEffect
from app.models.user.enums import UserRole
from app.server import create_app
from app.services.db import fetch_all, fetch_one
from app.services.security.jwt import AccessClaims, sign_access
from tests.approval_support import LabBacked, settle
from tests.fake_github_mcp import recorded_tools
from tests.fake_mcp import LAB_TOOLS, Servers
from tests.fake_mcp import mcp_servers as mcp_servers
from tests.source_support import admin_bearer, member_bearer
from tests.store import store_backed
from tests.support import error_of, http_client, recording_logger
from tests.test_agent import Journey
from tests.test_agent_knowledge import calls_of


class TestSetToolPolicyBody:
    """The request-schema rules of `PUT /api/tool-policy/{mcpServerId}/{toolName}`."""

    @pytest.mark.parametrize("effect", ["allow", "ask", "deny"])
    def test_accepts_each_effect(self, effect: str) -> None:
        assert SetToolPolicyBody.model_validate({"effect": effect}).effect == effect

    @pytest.mark.parametrize("effect", ["", "Allow", "permit", "never", None, 1, True])
    def test_rejects_an_effect_outside_the_set(self, effect: object) -> None:
        with pytest.raises(ValidationError):
            SetToolPolicyBody.model_validate({"effect": effect})

    def test_requires_the_effect(self) -> None:
        with pytest.raises(ValidationError):
            SetToolPolicyBody.model_validate({})


class TestBadEffectOverHttp:
    async def test_a_bad_effect_is_a_400(self, client: httpx.AsyncClient) -> None:
        res = await client.put(
            "/api/tool-policy/github/issue_write",
            json={"effect": "permit"},
            headers=admin_bearer(),
        )

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"
        assert res.json()["requestId"]


@dataclass(frozen=True)
class _Row:
    effect: str


async def effect_row(server: str, name: str) -> str | None:
    row = await fetch_one(
        _Row,
        "select effect from tool_policy where mcp_server_id = %s and tool_name = %s",
        (server, name),
    )
    return None if row is None else row.effect


async def row_count(server: str, name: str) -> int:
    return len(
        await fetch_all(
            _Row,
            "select effect from tool_policy where mcp_server_id = %s and tool_name = %s",
            (server, name),
        )
    )


def code_of(res: httpx.Response) -> str:
    assert res.json()["requestId"]
    return error_of(res).code


def admin_as(account: str) -> dict[str, str]:
    claims = AccessClaims(sub=account, role=UserRole.admin, sid=str(uuid.uuid4()))
    return {"Authorization": f"Bearer {sign_access(claims).token}"}


async def put(client: httpx.AsyncClient, server: str, name: str, effect: str) -> httpx.Response:
    return await client.put(
        f"/api/tool-policy/{server}/{name}", json={"effect": effect}, headers=admin_bearer()
    )


@store_backed
class TestRead(LabBacked):
    async def test_names_the_seeded_github_rows_with_what_each_may_be_set_to(
        self, client: httpx.AsyncClient
    ) -> None:
        res = await client.get("/api/tool-policy/github", headers=admin_bearer())

        assert res.status_code == 200
        body = res.json()
        assert body["mcpServerId"] == "github"
        names = [item["toolName"] for item in body["items"]]
        assert names == sorted(t.name for t in recorded_tools())
        items = {item["toolName"]: item for item in body["items"]}
        assert items["issue_read"] == {
            "toolName": "issue_read",
            "effect": "allow",
            "effects": ["allow", "ask", "deny"],
        }
        assert items["issue_write"]["effect"] == "ask"
        assert items["issue_write"]["effects"] == ["ask", "deny"]
        assert items["add_issue_comment"]["effects"] == ["ask", "deny"]

    async def test_a_pinned_tool_with_no_row_is_named_with_a_null_effect(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.register_lab(default=None)

        res = await client.get("/api/tool-policy/lab", headers=admin_bearer())

        items = res.json()["items"]
        assert [i["toolName"] for i in items] == sorted(t.name for t in LAB_TOOLS)
        assert all(i["effect"] is None for i in items)
        assert all(i["effects"] == ["allow", "ask", "deny"] for i in items)

    async def test_a_pinned_github_name_it_has_never_seen_offers_ask_and_deny(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        extra = ListedTool(name="a_future_tool", description="d", input_schema={"type": "object"})
        await servers.accept_github([*recorded_tools(), extra])

        res = await client.get("/api/tool-policy/github", headers=admin_bearer())

        item = next(i for i in res.json()["items"] if i["toolName"] == "a_future_tool")
        assert item == {"toolName": "a_future_tool", "effect": None, "effects": ["ask", "deny"]}

    async def test_knowledge_has_its_search_policy(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/tool-policy/knowledge", headers=admin_bearer())

        assert res.json()["items"] == [
            {"toolName": "search", "effect": "allow", "effects": ["allow", "ask", "deny"]}
        ]

    async def test_an_unknown_server_is_a_404(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/tool-policy/nothing", headers=admin_bearer())

        assert res.status_code == 404
        assert code_of(res) == "not_found"


@store_backed
@pytest.mark.usefixtures("fake_model")
class TestSet(LabBacked):
    async def test_creates_the_one_row_of_a_tool_with_none(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.register_lab(default=None)

        res = await put(client, "lab", "echo", "ask")

        assert res.status_code == 200
        assert res.json() == {
            "toolName": "echo",
            "effect": "ask",
            "effects": ["allow", "ask", "deny"],
        }
        assert await effect_row("lab", "echo") == "ask"

    async def test_changes_the_row_and_leaves_exactly_one(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.register_lab({"echo": PolicyEffect.ask})

        first = await put(client, "lab", "echo", "deny")
        second = await put(client, "lab", "echo", "allow")

        assert (first.json()["effect"], second.json()["effect"]) == ("deny", "allow")
        assert await row_count("lab", "echo") == 1
        assert await effect_row("lab", "echo") == "allow"

    @pytest.mark.parametrize(
        ("effect", "status", "called"),
        [
            ("allow", "succeeded", True),
            ("ask", "awaiting_approval", False),
            ("deny", "denied", False),
        ],
    )
    async def test_takes_effect_on_the_next_call_with_no_restart(
        self,
        client: httpx.AsyncClient,
        servers: Servers,
        effect: str,
        status: str,
        called: bool,
    ) -> None:
        await servers.register_lab(default=None)
        await put(client, "lab", "echo", effect)

        run_id, _ = await Journey(client).run("[[tool:lab__echo]]")

        (call,) = await calls_of(run_id)
        assert call.status == status
        assert bool(servers.lab.calls) is called

    async def test_a_held_call_denies_at_the_resume_after_a_deny(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.register_lab({"echo": PolicyEffect.ask})
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")
        await put(client, "lab", "echo", "deny")

        frames = await settle(journey, run_id)

        assert servers.lab.calls == []
        assert frames[4].event["status"] == "denied"

    async def test_an_unknown_server_or_tool_is_a_404_whatever_the_effect(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.register_lab()

        no_server = await put(client, "nothing", "echo", "deny")
        no_tool = await put(client, "lab", "ghost", "deny")
        no_github_tool = await put(client, "github", "never_heard_of", "allow")

        for res in (no_server, no_tool, no_github_tool):
            assert res.status_code == 404
            assert code_of(res) == "not_found"
        assert await effect_row("lab", "ghost") is None
        assert await effect_row("github", "never_heard_of") is None

    async def test_a_pinned_tool_with_no_row_is_known(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        extra = ListedTool(name="a_future_tool", description="d", input_schema={"type": "object"})
        await servers.accept_github([*recorded_tools(), extra])

        res = await put(client, "github", "a_future_tool", "ask")

        assert res.status_code == 200
        assert await effect_row("github", "a_future_tool") == "ask"


@store_backed
class TestEffects(LabBacked):
    @pytest.mark.parametrize("name", ["issue_write", "add_issue_comment"])
    async def test_allow_on_a_github_write_is_a_400_that_writes_nothing(
        self, client: httpx.AsyncClient, name: str
    ) -> None:
        before = await effect_row("github", name)

        res = await put(client, "github", name, "allow")

        assert res.status_code == 400
        assert code_of(res) == "validation_failed"
        assert await effect_row("github", name) == before == "ask"

    async def test_a_name_it_has_never_seen_is_capped_the_same_way(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        extra = ListedTool(name="a_future_tool", description="d", input_schema={"type": "object"})
        await servers.accept_github([*recorded_tools(), extra])

        res = await put(client, "github", "a_future_tool", "allow")

        assert res.status_code == 400
        assert await effect_row("github", "a_future_tool") is None

    @pytest.mark.parametrize("name", sorted(GITHUB_ALLOWABLE_TOOLS))
    async def test_each_of_the_five_reads_may_be_allow(
        self, client: httpx.AsyncClient, name: str
    ) -> None:
        await put(client, "github", name, "deny")

        res = await put(client, "github", name, "allow")

        assert res.status_code == 200
        assert await effect_row("github", name) == "allow"

    async def test_a_write_may_be_ask_or_deny(self, client: httpx.AsyncClient) -> None:
        deny = await put(client, "github", "issue_write", "deny")
        ask = await put(client, "github", "issue_write", "ask")

        assert (deny.status_code, ask.status_code) == (200, 200)

    async def test_another_server_has_no_cap(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.register_lab({"echo": PolicyEffect.ask})

        res = await put(client, "lab", "echo", "allow")

        assert res.status_code == 200


@store_backed
class TestLogs(LabBacked):
    async def test_a_write_logs_the_account_server_and_tool_and_no_definition(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, servers: Servers
    ) -> None:
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.tool_policy.controller.log", logger)
        await servers.register_lab(default=None)
        account = str(uuid.uuid4())

        await client.put(
            "/api/tool-policy/lab/echo", json={"effect": "ask"}, headers=admin_as(account)
        )

        (line,) = [entry for entry in sink.lines if account in entry]
        assert "lab" in line
        assert "echo" in line
        assert "echo tool" not in "\n".join(sink.lines)


ENDPOINTS = [
    ("GET", "/api/tool-policy/github", None),
    ("PUT", "/api/tool-policy/github/issue_read", {"effect": "deny"}),
]


class TestAccess:
    @pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
    async def test_no_token_is_a_401(
        self, client: httpx.AsyncClient, method: str, path: str, body: object
    ) -> None:
        res = await client.request(method, path, json=body)

        assert res.status_code == 401
        assert code_of(res) == "unauthenticated"

    @pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
    async def test_a_user_is_a_403(
        self, client: httpx.AsyncClient, method: str, path: str, body: object
    ) -> None:
        res = await client.request(method, path, json=body, headers=member_bearer())

        assert res.status_code == 403
        assert code_of(res) == "forbidden"

    async def test_the_handlers_refuse_a_user_even_without_the_route_gate(self) -> None:
        probe = create_app()
        gate = [Depends(require_auth)]
        probe.add_api_route(
            "/p/{mcpServerId}", tool_policy.get_tool_policy, methods=["GET"], dependencies=gate
        )
        probe.add_api_route(
            "/p/{mcpServerId}/{toolName}",
            tool_policy.set_tool_policy,
            methods=["PUT"],
            dependencies=gate,
        )

        async with http_client(probe) as client:
            got = await client.get("/p/github", headers=member_bearer())
            set_ = await client.put(
                "/p/github/issue_read", json={"effect": "deny"}, headers=member_bearer()
            )

        assert (got.status_code, set_.status_code) == (403, 403)
