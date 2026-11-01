"""The admin's MCP server endpoints: the request-schema rules, then each endpoint's behaviour on
the real store with `knowledge`, `lab` and the scripted `github-mcp-server` in process."""

import json
import uuid
from dataclasses import dataclass, replace

import httpx
import pytest
from fastapi import Depends, FastAPI
from pydantic import ValidationError

from app.api.mcp_server import controller as mcp_server
from app.api.mcp_server.schema import AcceptListingBody, UpdateMcpServerBody
from app.middleware.auth import require_auth
from app.models.mcp_server.type import ListedTool
from app.models.tool_policy.enums import PolicyEffect
from app.models.user.enums import UserRole
from app.server import create_app
from app.services import tool
from app.services.db import execute, fetch_one
from app.services.security.jwt import AccessClaims, sign_access
from tests.agent_support import RecordingFake
from tests.approval_support import LabBacked, settle
from tests.fake_github_mcp import recorded_tools
from tests.fake_mcp import GITHUB_HOST, KNOWLEDGE_HOST, LAB_HOST, Servers, pin_document
from tests.fake_mcp import mcp_servers as mcp_servers
from tests.rewrite_app import Rewrite
from tests.source_support import admin_bearer, member_bearer
from tests.store import store_backed
from tests.support import error_of, http_client, recording_logger
from tests.test_agent import Journey, finish_of
from tests.test_agent_knowledge import calls_of

DIGEST = "a" * 64
READ = "[[tool:github__issue_read]]"


class TestAcceptListingBody:
    """The request-schema rules of `POST /api/mcp-server/{id}/acceptance`."""

    def test_accepts_a_sha256_in_lowercase_hex(self) -> None:
        body = AcceptListingBody.model_validate({"listingDigest": DIGEST})

        assert body.listing_digest == DIGEST

    @pytest.mark.parametrize(
        "digest",
        ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, " " + "a" * 63, "a" * 63 + "\n", None, 1],
    )
    def test_rejects_anything_but_64_lowercase_hex(self, digest: object) -> None:
        with pytest.raises(ValidationError):
            AcceptListingBody.model_validate({"listingDigest": digest})

    def test_requires_the_digest(self) -> None:
        with pytest.raises(ValidationError):
            AcceptListingBody.model_validate({})


class TestUpdateMcpServerBody:
    """The request-schema rules of `PATCH /api/mcp-server/{id}`."""

    @pytest.mark.parametrize("enabled", [True, False])
    def test_accepts_a_boolean(self, enabled: bool) -> None:
        assert UpdateMcpServerBody.model_validate({"enabled": enabled}).enabled is enabled

    @pytest.mark.parametrize("enabled", ["true", "yes", 1, 0, None, []])
    def test_rejects_anything_but_a_boolean(self, enabled: object) -> None:
        with pytest.raises(ValidationError):
            UpdateMcpServerBody.model_validate({"enabled": enabled})

    def test_requires_enabled(self) -> None:
        with pytest.raises(ValidationError):
            UpdateMcpServerBody.model_validate({})


class TestListQuery:
    """The list's `cursor` and `limit` are validated before any data is read."""

    @pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=x"])
    async def test_a_bad_limit_is_a_400(self, client: httpx.AsyncClient, query: str) -> None:
        res = await client.get(f"/api/mcp-server?{query}", headers=admin_bearer())

        assert res.status_code == 400, query
        assert error_of(res).code == "validation_failed"
        assert res.json()["requestId"]

    @store_backed
    @pytest.mark.parametrize("cursor", ["not-a-cursor!", "e30", "bm9wZQ", "%00"])
    async def test_a_malformed_cursor_is_a_400(
        self, client: httpx.AsyncClient, cursor: str
    ) -> None:
        res = await client.get(f"/api/mcp-server?cursor={cursor}", headers=admin_bearer())

        assert res.status_code == 400, cursor
        assert error_of(res).code == "validation_failed"
        assert res.json()["requestId"]


@dataclass(frozen=True)
class _Stored:
    enabled: bool
    tool_definition: list[dict[str, object]] | None
    pinned_tool_definition: list[dict[str, object]] | None
    updated_at: object


async def stored(name: str = "github") -> _Stored:
    row = await fetch_one(
        _Stored,
        "select enabled, tool_definition, pinned_tool_definition, updated_at "
        "from mcp_server where name = %s",
        (name,),
    )
    assert row is not None
    return row


def document(tools: list[ListedTool]) -> list[dict[str, object]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def edited(tools: list[ListedTool], name: str, **changes: object) -> list[ListedTool]:
    return [replace(t, **changes) if t.name == name else t for t in tools]  # type: ignore[arg-type]


def with_default(name: str, default: object) -> ListedTool:
    return ListedTool(
        name=name,
        description="d",
        input_schema={"type": "object", "properties": {"n": {"default": default}}},
    )


def admin_as(account: str) -> dict[str, str]:
    claims = AccessClaims(sub=account, role=UserRole.admin, sid=str(uuid.uuid4()))
    return {"Authorization": f"Bearer {sign_access(claims).token}"}


async def accept(
    client: httpx.AsyncClient, name: str = "github", digest: str | None = None
) -> httpx.Response:
    headers = admin_bearer()
    if digest is None:
        digest = (await client.get(f"/api/mcp-server/{name}/listing", headers=headers)).json()[
            "listingDigest"
        ]
    return await client.post(
        f"/api/mcp-server/{name}/acceptance", json={"listingDigest": digest}, headers=headers
    )


def code_of(res: httpx.Response) -> str:
    assert res.json()["requestId"]
    return error_of(res).code


@store_backed
class TestRead(LabBacked):
    async def test_lists_the_seeded_servers_newest_first_with_their_status(
        self, client: httpx.AsyncClient
    ) -> None:
        res = await client.get("/api/mcp-server", headers=admin_bearer())

        assert res.status_code == 200
        page = res.json()
        by_name = {item["name"]: item for item in page["items"]}
        assert set(by_name) == {"knowledge", "github"}
        assert by_name["knowledge"]["pinStatus"] == "not_required"
        assert by_name["knowledge"]["enabled"] is True
        assert by_name["github"]["pinStatus"] == "unpinned"
        assert by_name["github"]["enabled"] is False
        assert page["nextCursor"] is None
        for item in page["items"]:
            assert set(item) == {"id", "name", "enabled", "pinStatus", "createdAt", "updatedAt"}

    async def test_pages_with_a_cursor(self, client: httpx.AsyncClient) -> None:
        first = await client.get("/api/mcp-server?limit=1", headers=admin_bearer())
        second = await client.get(
            f"/api/mcp-server?limit=1&cursor={first.json()['nextCursor']}", headers=admin_bearer()
        )

        assert len(first.json()["items"]) == len(second.json()["items"]) == 1
        assert first.json()["items"][0]["id"] != second.json()["items"][0]["id"]
        assert second.json()["nextCursor"] is None

    async def test_no_url_and_no_token_reach_the_wire(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.register_lab()

        res = await client.get("/api/mcp-server", headers=admin_bearer())

        assert "http://lab" not in res.text
        assert "url" not in res.text.lower()
        assert "token" not in res.text.lower()
        assert "toolCount" not in res.text

    async def test_a_pin_equal_to_the_listing_is_current(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.accept_github()

        res = await client.get("/api/mcp-server/github", headers=admin_bearer())

        assert res.status_code == 200
        assert res.json()["pinStatus"] == "current"

    async def test_a_last_listing_that_differs_is_changed(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.accept_github()
        later = edited(recorded_tools(), "issue_read", description="now it says more")
        await execute(
            "update mcp_server set tool_definition = %s where name = 'github'",
            (pin_document(later),),
        )

        res = await client.get("/api/mcp-server/github", headers=admin_bearer())

        assert res.json()["pinStatus"] == "changed"

    async def test_zero_against_false_reads_changed_where_python_calls_them_equal(
        self, client: httpx.AsyncClient
    ) -> None:
        await execute(
            "update mcp_server set pinned_tool_definition = %s, tool_definition = %s "
            "where name = 'github'",
            (pin_document([with_default("t", 0)]), pin_document([with_default("t", False)])),
        )

        res = await client.get("/api/mcp-server/github", headers=admin_bearer())

        assert res.json()["pinStatus"] == "changed"

    async def test_list_and_detail_answer_while_every_server_is_down(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.accept_github()
        await servers.register_lab()
        for host in (KNOWLEDGE_HOST, GITHUB_HOST, LAB_HOST):
            servers.take_down(host)
        before = len(servers.hosts.requests)

        listed = await client.get("/api/mcp-server", headers=admin_bearer())
        one = await client.get("/api/mcp-server/github", headers=admin_bearer())

        assert listed.status_code == one.status_code == 200
        assert {i["name"] for i in listed.json()["items"]} == {"knowledge", "github", "lab"}
        assert len(servers.hosts.requests) == before

    async def test_an_unknown_server_is_a_404(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/mcp-server/nothing", headers=admin_bearer())

        assert res.status_code == 404
        assert code_of(res) == "not_found"


@store_backed
class TestListing(LabBacked):
    async def test_returns_the_live_listing_whole_sorted_with_every_header_intact(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        res = await client.get("/api/mcp-server/github/listing", headers=admin_bearer())

        assert res.status_code == 200
        body = res.json()
        live = servers.github.tools
        assert body["mcpServerId"] == "github"
        assert body["listingDigest"] == tool.listing_digest(live)
        assert [i["name"] for i in body["items"]] == sorted(t.name for t in live)
        assert len(body["items"]) == 7
        by_name = {t.name: t for t in live}
        for item in body["items"]:
            source = by_name[item["name"]]
            assert item["change"] == "added"
            assert item["description"] == source.description
            assert isinstance(item["inputSchema"], str)
            assert json.loads(item["inputSchema"]) == source.input_schema
            assert item["pinnedDescription"] is None
            assert item["pinnedInputSchema"] is None
        assert any("x-mcp-header" in item["inputSchema"] for item in body["items"])

    async def test_each_tools_change_and_both_versions_of_a_changed_one(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        pinned = recorded_tools()
        await servers.accept_github(pinned)
        live = edited(pinned, "issue_read", description="The new words.")
        live = [t for t in live if t.name != "list_issues"]
        live.append(ListedTool(name="brand_new", description="n", input_schema={"type": "object"}))
        servers.github.tools[:] = live

        res = await client.get("/api/mcp-server/github/listing", headers=admin_bearer())

        items = {i["name"]: i for i in res.json()["items"]}
        assert items["brand_new"]["change"] == "added"
        assert items["list_issues"]["change"] == "removed"
        assert items["issue_read"]["change"] == "changed"
        assert items["get_file_contents"]["change"] == "unchanged"
        old = next(t for t in pinned if t.name == "issue_read")
        assert items["issue_read"]["description"] == "The new words."
        assert items["issue_read"]["pinnedDescription"] == old.description
        assert json.loads(items["issue_read"]["pinnedInputSchema"]) == old.input_schema
        removed = items["list_issues"]
        assert removed["description"] is None
        assert removed["inputSchema"] is None
        assert removed["pinnedDescription"] is not None
        assert items["get_file_contents"]["pinnedDescription"] is None
        assert items["get_file_contents"]["pinnedInputSchema"] is None
        assert [i["name"] for i in res.json()["items"]] == sorted(items)

    async def test_one_and_one_point_zero_print_differently(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.accept_github([with_default("t", 1)])
        servers.github.tools[:] = [with_default("t", 1.0)]

        res = await client.get("/api/mcp-server/github/listing", headers=admin_bearer())

        (item,) = res.json()["items"]
        assert item["change"] == "changed"
        assert item["inputSchema"] != item["pinnedInputSchema"]
        assert '"default": 1.0' in item["inputSchema"]
        assert '"default": 1\n' in item["pinnedInputSchema"]

    async def test_a_number_past_two_to_the_fifty_third_keeps_every_digit(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        servers.github.tools[:] = [with_default("t", 9007199254740993)]

        res = await client.get("/api/mcp-server/github/listing", headers=admin_bearer())

        assert "9007199254740993" in res.json()["items"][0]["inputSchema"]

    async def test_reads_a_disabled_server_and_stores_nothing(
        self, client: httpx.AsyncClient
    ) -> None:
        before = await stored()

        res = await client.get("/api/mcp-server/github/listing", headers=admin_bearer())

        assert res.status_code == 200
        assert before.enabled is False
        assert await stored() == before

    async def test_a_server_that_does_not_answer_is_a_503(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        servers.take_down(GITHUB_HOST)

        res = await client.get("/api/mcp-server/github/listing", headers=admin_bearer())

        assert res.status_code == 503
        assert code_of(res) == "upstream_unavailable"

    async def test_knowledge_has_no_review(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/mcp-server/knowledge/listing", headers=admin_bearer())

        assert res.status_code == 409
        assert code_of(res) == "conflict"

    async def test_an_unknown_server_is_a_404(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/mcp-server/nothing/listing", headers=admin_bearer())

        assert res.status_code == 404
        assert code_of(res) == "not_found"


@store_backed
class TestAccept(LabBacked):
    async def test_pins_exactly_the_listing_shown_enables_the_row_and_reads_current(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        res = await accept(client)

        assert res.status_code == 200
        assert res.json()["pinStatus"] == "current"
        assert res.json()["enabled"] is True
        row = await stored()
        assert row.pinned_tool_definition == json.loads(json.dumps(document(servers.github.tools)))
        assert row.tool_definition == row.pinned_tool_definition
        await Journey(client).run("hello")
        names = [d["name"] for d in fake_model.requests[0]["tools"]]  # type: ignore[attr-defined]
        assert "github__issue_read" in names

    async def test_a_stale_digest_is_a_409_and_writes_nothing(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        shown = (await client.get("/api/mcp-server/github/listing", headers=admin_bearer())).json()[
            "listingDigest"
        ]
        servers.github.tools[:] = edited(servers.github.tools, "issue_read", description="swapped")
        before = await stored()

        res = await accept(client, digest=shown)

        assert res.status_code == 409
        assert code_of(res) == "conflict"
        assert await stored() == before

    async def test_a_server_that_does_not_answer_changes_nothing(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        before = await stored()
        servers.take_down(GITHUB_HOST)

        res = await accept(client, digest=DIGEST)

        assert res.status_code == 503
        assert code_of(res) == "upstream_unavailable"
        assert await stored() == before

    async def test_knowledge_is_a_409(self, client: httpx.AsyncClient) -> None:
        before = await stored("knowledge")

        res = await accept(client, "knowledge", DIGEST)

        assert res.status_code == 409
        assert await stored("knowledge") == before

    async def test_an_unknown_server_is_a_404(self, client: httpx.AsyncClient) -> None:
        res = await accept(client, "nothing", DIGEST)

        assert res.status_code == 404
        assert code_of(res) == "not_found"

    async def test_a_malformed_digest_is_a_400(self, client: httpx.AsyncClient) -> None:
        res = await accept(client, "github", "NOT-A-DIGEST")

        assert res.status_code == 400
        assert code_of(res) == "validation_failed"

    async def test_logs_the_account_server_and_digest_and_no_definition(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, servers: Servers
    ) -> None:
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.mcp_server.controller.log", logger)
        account = str(uuid.uuid4())
        digest = (
            await client.get("/api/mcp-server/github/listing", headers=admin_bearer())
        ).json()["listingDigest"]

        res = await client.post(
            "/api/mcp-server/github/acceptance",
            json={"listingDigest": digest},
            headers=admin_as(account),
        )

        assert res.status_code == 200
        (line,) = [entry for entry in sink.lines if "accepted" in entry]
        assert account in line
        assert "github" in line
        assert digest in line
        for tool_listed in servers.github.tools:
            assert tool_listed.description not in "\n".join(sink.lines)


@store_backed
class TestRefusedListing(LabBacked):
    @pytest.fixture(autouse=True)
    async def logs(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.mcp_server.controller.log", logger)
        monkeypatch.setattr("app.services.mcp.log", logger)
        return sink.lines

    @pytest.mark.parametrize(
        "tools",
        [
            [],
            [with_default("dup", 1), with_default("dup", 2)],
            [with_default("has space", 1)],
            [with_default("x\x1b[2Jhidden", 1)],
            [with_default("a__b.c", 1)],
        ],
        ids=["empty", "repeated", "space", "escape", "dot"],
    )
    async def test_a_refused_listing_is_a_409_at_the_review_and_the_accept_with_nothing_on_the_wire(
        self, client: httpx.AsyncClient, servers: Servers, tools: list[ListedTool]
    ) -> None:
        servers.github.tools[:] = tools
        before = await stored()

        review = await client.get("/api/mcp-server/github/listing", headers=admin_bearer())
        accepted = await accept(client, digest=DIGEST)

        for res in (review, accepted):
            assert res.status_code == 409
            assert code_of(res) == "conflict"
            assert "\x1b" not in res.text
            assert "hidden" not in res.text
            assert "dup" not in res.text
        assert await stored() == before

    @pytest.mark.parametrize(
        ("schema", "swaps"),
        [
            ({"type": "object", "title": "a\x00b"}, {}),
            ({"type": "object", "default": "@@"}, {b'"@@"': b"NaN"}),
            ({"type": "object", "default": "@@"}, {b'"@@"': b"Infinity"}),
            ({"type": "object", "default": "@@"}, {b'"@@"': b"1e400"}),
        ],
        ids=["nul", "nan", "infinity", "overflow"],
    )
    async def test_what_the_store_cannot_hold_is_a_503_at_the_review_and_the_accept(
        self,
        client: httpx.AsyncClient,
        servers: Servers,
        logs: list[str],
        schema: dict[str, object],
        swaps: dict[bytes, bytes],
    ) -> None:
        servers.github.tools[:] = [
            ListedTool(name="odd", description="d", input_schema=schema),
        ]
        servers.hosts.apps[GITHUB_HOST] = Rewrite(servers.hosts.apps[GITHUB_HOST], swaps)  # type: ignore[assignment]
        before = await stored()

        review = await client.get("/api/mcp-server/github/listing", headers=admin_bearer())
        accepted = await accept(client, digest=DIGEST)

        for res in (review, accepted):
            assert res.status_code == 503
            assert code_of(res) == "upstream_unavailable"
        assert await stored() == before
        assert any("unstorable_listing" in line for line in logs)


@store_backed
@pytest.mark.usefixtures("fake_model")
class TestEnabled(LabBacked):
    async def test_disabling_drops_the_server_from_the_next_run(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.accept_github()

        res = await client.patch(
            "/api/mcp-server/github", json={"enabled": False}, headers=admin_bearer()
        )
        await Journey(client).run("hello")

        assert res.status_code == 200
        assert res.json()["enabled"] is False
        assert (await stored()).enabled is False
        names = [d["name"] for d in fake_model.requests[0]["tools"]]  # type: ignore[attr-defined]
        assert names == ["knowledge__search"]

    async def test_a_frozen_conversations_call_is_denied_with_no_server_call(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.accept_github()
        journey = Journey(client)
        await journey.run("hello")
        await client.patch(
            "/api/mcp-server/github", json={"enabled": False}, headers=admin_bearer()
        )

        run_id, frames = await journey.run(READ)

        (call,) = await calls_of(run_id)
        assert call.status == "denied"
        assert servers.github.calls == []
        assert finish_of(frames).event["status"] == "completed"

    async def test_a_held_approval_denies_at_the_resume_once_the_server_is_disabled(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.register_lab({"echo": PolicyEffect.ask})
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")

        res = await client.patch(
            "/api/mcp-server/lab", json={"enabled": False}, headers=admin_bearer()
        )
        frames = await settle(journey, run_id)

        assert res.status_code == 200
        assert servers.lab.calls == []
        assert frames[4].event["status"] == "denied"

    async def test_enabling_a_third_party_with_no_pin_is_a_409(
        self, client: httpx.AsyncClient
    ) -> None:
        res = await client.patch(
            "/api/mcp-server/github", json={"enabled": True}, headers=admin_bearer()
        )

        assert res.status_code == 409
        assert code_of(res) == "conflict"
        assert (await stored()).enabled is False

    async def test_enabling_a_pinned_server_takes_effect_on_the_next_run(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.accept_github(enabled=False)

        res = await client.patch(
            "/api/mcp-server/github", json={"enabled": True}, headers=admin_bearer()
        )
        await Journey(client).run("hello")

        assert res.status_code == 200
        assert res.json()["enabled"] is True
        names = [d["name"] for d in fake_model.requests[0]["tools"]]  # type: ignore[attr-defined]
        assert "github__issue_read" in names

    async def test_knowledge_can_be_turned_off_and_on(self, client: httpx.AsyncClient) -> None:
        off = await client.patch(
            "/api/mcp-server/knowledge", json={"enabled": False}, headers=admin_bearer()
        )
        on = await client.patch(
            "/api/mcp-server/knowledge", json={"enabled": True}, headers=admin_bearer()
        )

        assert (off.json()["enabled"], on.json()["enabled"]) == (False, True)

    async def test_an_unknown_server_is_a_404_and_a_bad_body_a_400(
        self, client: httpx.AsyncClient
    ) -> None:
        missing = await client.patch(
            "/api/mcp-server/nothing", json={"enabled": True}, headers=admin_bearer()
        )
        bad = await client.patch(
            "/api/mcp-server/github", json={"enabled": "yes"}, headers=admin_bearer()
        )

        assert (missing.status_code, code_of(missing)) == (404, "not_found")
        assert (bad.status_code, code_of(bad)) == (400, "validation_failed")

    async def test_logs_the_account_and_the_server(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.mcp_server.controller.log", logger)
        account = str(uuid.uuid4())

        await client.patch(
            "/api/mcp-server/knowledge", json={"enabled": False}, headers=admin_as(account)
        )

        (line,) = [entry for entry in sink.lines if account in entry]
        assert "knowledge" in line


ENDPOINTS = [
    ("GET", "/api/mcp-server", None),
    ("GET", "/api/mcp-server/github", None),
    ("PATCH", "/api/mcp-server/github", {"enabled": True}),
    ("GET", "/api/mcp-server/github/listing", None),
    ("POST", "/api/mcp-server/github/acceptance", {"listingDigest": DIGEST}),
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
        probe.add_api_route("/s", mcp_server.list_mcp_server, methods=["GET"], dependencies=gate)
        probe.add_api_route(
            "/s/{id}", mcp_server.get_mcp_server, methods=["GET"], dependencies=gate
        )
        probe.add_api_route(
            "/s/{id}", mcp_server.update_mcp_server, methods=["PATCH"], dependencies=gate
        )
        probe.add_api_route(
            "/s/{id}/listing", mcp_server.get_mcp_server_listing, methods=["GET"], dependencies=gate
        )
        probe.add_api_route(
            "/s/{id}/acceptance",
            mcp_server.accept_mcp_server_listing,
            methods=["POST"],
            dependencies=gate,
        )
        assert isinstance(probe, FastAPI)

        async with http_client(probe) as client:
            answers = [
                await client.get("/s", headers=member_bearer()),
                await client.get("/s/github", headers=member_bearer()),
                await client.patch("/s/github", json={"enabled": True}, headers=member_bearer()),
                await client.get("/s/github/listing", headers=member_bearer()),
                await client.post(
                    "/s/github/acceptance", json={"listingDigest": DIGEST}, headers=member_bearer()
                ),
            ]

        assert [a.status_code for a in answers] == [403] * 5
