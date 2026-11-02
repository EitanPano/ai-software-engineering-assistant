"""QA's attacks on the admin's MCP server and tool-policy endpoints: hostile path segments, wrong
body types, a forged digest and concurrent writes. None may answer a 500 or write a row."""

import asyncio
import base64
import json

import httpx
import pytest

from tests.approval_support import LabBacked
from tests.fake_mcp import Servers
from tests.fake_mcp import mcp_servers as mcp_servers
from tests.source_support import admin_bearer
from tests.store import store_backed
from tests.support import error_of


@store_backed
class TestHostileInput(LabBacked):
    @pytest.mark.parametrize(
        "segment", ["x" * 5000, "%2e%2e", "a%20b", "%F0%9F%92%A5", "%00", "a%00b"]
    )
    @pytest.mark.parametrize(
        "template",
        ["/api/mcp-server/{}", "/api/mcp-server/{}/listing", "/api/tool-policy/{}"],
    )
    async def test_a_hostile_server_id_is_a_404_never_a_500(
        self, client: httpx.AsyncClient, segment: str, template: str
    ) -> None:
        res = await client.get(template.format(segment), headers=admin_bearer())

        assert res.status_code == 404
        assert error_of(res).code == "not_found"
        assert res.json()["requestId"]

    async def test_a_nul_server_id_cannot_be_patched(self, client: httpx.AsyncClient) -> None:
        res = await client.patch(
            "/api/mcp-server/a%00b", json={"enabled": False}, headers=admin_bearer()
        )

        assert res.status_code == 404
        assert error_of(res).code == "not_found"

    @pytest.mark.parametrize("id_", ["a\x00", "\x00", "a\x00b"])
    async def test_a_cursor_holding_a_nul_id_is_a_400(
        self, client: httpx.AsyncClient, id_: str
    ) -> None:
        raw = json.dumps({"created_at": "2026-01-01T00:00:00+00:00", "id": id_}).encode()
        cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=")

        res = await client.get(f"/api/mcp-server?cursor={cursor}", headers=admin_bearer())

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"

    @pytest.mark.parametrize("segment", ["%00", "a%00b", "x" * 5000, "%F0%9F%92%A5"])
    async def test_a_hostile_tool_name_is_a_404_and_writes_nothing(
        self, client: httpx.AsyncClient, segment: str
    ) -> None:
        res = await client.put(
            f"/api/tool-policy/github/{segment}", json={"effect": "ask"}, headers=admin_bearer()
        )

        assert res.status_code in (400, 404)
        after = await client.get("/api/tool-policy/github", headers=admin_bearer())
        assert all(i["toolName"] != segment for i in after.json()["items"])

    @pytest.mark.parametrize("enabled", ["true", 1, None, [], {}])
    async def test_a_non_boolean_enabled_is_a_400(
        self, client: httpx.AsyncClient, enabled: object
    ) -> None:
        res = await client.patch(
            "/api/mcp-server/github", json={"enabled": enabled}, headers=admin_bearer()
        )

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"

    @pytest.mark.parametrize("body", [None, [], "x", {"enabled": True, "extra": 1}])
    async def test_a_malformed_patch_body_is_never_a_500(
        self, client: httpx.AsyncClient, body: object
    ) -> None:
        res = await client.patch("/api/mcp-server/github", json=body, headers=admin_bearer())

        assert res.status_code < 500

    @pytest.mark.parametrize("limit", ["0", "-1", "abc", "100000"])
    async def test_a_bad_list_limit_is_never_a_500(
        self, client: httpx.AsyncClient, limit: str
    ) -> None:
        res = await client.get(f"/api/mcp-server?limit={limit}", headers=admin_bearer())

        assert res.status_code < 500


@store_backed
class TestForgedDigest(LabBacked):
    @pytest.mark.parametrize(
        "digest", ["0" * 64, "A" * 64, "0" * 63, "0" * 65, "", "g" * 64, "0" * 63 + "\n"]
    )
    async def test_a_forged_digest_changes_nothing(
        self, client: httpx.AsyncClient, digest: str
    ) -> None:
        before = await client.get("/api/mcp-server/github", headers=admin_bearer())

        res = await client.post(
            "/api/mcp-server/github/acceptance",
            json={"listingDigest": digest},
            headers=admin_bearer(),
        )

        assert res.status_code in (400, 409)
        after = await client.get("/api/mcp-server/github", headers=admin_bearer())
        assert after.json() == before.json()

    async def test_knowledge_has_nothing_to_accept(self, client: httpx.AsyncClient) -> None:
        res = await client.post(
            "/api/mcp-server/knowledge/acceptance",
            json={"listingDigest": "0" * 64},
            headers=admin_bearer(),
        )

        assert res.status_code == 409


@store_backed
class TestConcurrentWrites(LabBacked):
    async def test_parallel_puts_leave_one_row_with_one_of_the_effects(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        await servers.register_lab(default=None)
        effects = ["allow", "ask", "deny"] * 4

        answers = await asyncio.gather(
            *(
                client.put("/api/tool-policy/lab/echo", json={"effect": e}, headers=admin_bearer())
                for e in effects
            )
        )

        assert all(a.status_code == 200 for a in answers)
        doc = await client.get("/api/tool-policy/lab", headers=admin_bearer())
        echo = [i for i in doc.json()["items"] if i["toolName"] == "echo"]
        assert len(echo) == 1
        assert echo[0]["effect"] in {"allow", "ask", "deny"}

    async def test_parallel_toggles_end_in_a_valid_state(self, client: httpx.AsyncClient) -> None:
        answers = await asyncio.gather(
            *(
                client.patch(
                    "/api/mcp-server/knowledge",
                    json={"enabled": i % 2 == 0},
                    headers=admin_bearer(),
                )
                for i in range(10)
            )
        )

        assert all(a.status_code == 200 for a in answers)
        final = await client.get("/api/mcp-server/knowledge", headers=admin_bearer())
        assert final.json()["enabled"] in (True, False)
        await client.patch(
            "/api/mcp-server/knowledge", json={"enabled": True}, headers=admin_bearer()
        )
