"""`tests/seed_changed_server.py`: the row the e2e journey reviews, read through the API."""

from dataclasses import dataclass

import httpx
import pytest

from app.services.db import fetch_one
from tests.seed_changed_server import OLDER_DESCRIPTION, assert_server_name, seed
from tests.source_support import admin_bearer
from tests.store import store_backed
from tests.test_agent import StoreBacked


@dataclass(frozen=True)
class _Pin:
    pinned_tool_definition: list[dict[str, object]]


@store_backed
class TestSeed(StoreBacked):
    async def test_writes_a_disabled_changed_server_with_an_ask_policy(
        self, client: httpx.AsyncClient
    ) -> None:
        await seed("http://127.0.0.1:8101", "journey-one")

        one = await client.get("/api/mcp-server/journey-one", headers=admin_bearer())
        policy = await client.get("/api/tool-policy/journey-one", headers=admin_bearer())

        assert one.json()["pinStatus"] == "changed"
        assert one.json()["enabled"] is False
        assert policy.json()["items"] == [
            {"toolName": "note", "effect": "ask", "effects": ["allow", "ask", "deny"]}
        ]

    async def test_the_pin_is_the_older_description(self) -> None:
        await seed("http://127.0.0.1:8101", "journey-two")

        row = await fetch_one(
            _Pin,
            "select pinned_tool_definition from mcp_server where name = 'journey-two'",
        )
        assert row is not None
        assert row.pinned_tool_definition[0]["description"] == OLDER_DESCRIPTION

    async def test_seeding_twice_leaves_one_row(self, client: httpx.AsyncClient) -> None:
        await seed("http://127.0.0.1:8101", "journey-three")
        await seed("http://127.0.0.1:8101", "journey-three")

        policy = await client.get("/api/tool-policy/journey-three", headers=admin_bearer())

        assert len(policy.json()["items"]) == 1


class TestName:
    @pytest.mark.parametrize("name", ["knowledge", "github", "", "A", "a__b", "a b", "../x"])
    def test_refuses_a_reserved_or_odd_name(self, name: str) -> None:
        with pytest.raises(ValueError, match="new"):
            assert_server_name(name)

    def test_accepts_a_journey_name(self) -> None:
        assert_server_name("journey-1a2b")
