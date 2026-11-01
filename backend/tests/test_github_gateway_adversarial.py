"""QA attacks on the GitHub gateway and the pin: what a caller or a changed listing could try."""

from dataclasses import replace

import pytest

from app.services import tool
from tests.services.test_tool import listed, offered, server
from tests.test_github_gateway import (  # noqa: F401
    PAT,
    RPC,
    TOKEN,
    Setup,
    setup,
)


class TestGatewayAttacks:
    async def test_a_query_string_never_reaches_the_upstream(self, setup: Setup) -> None:  # noqa: F811
        async with setup.raw() as http:
            response = await http.post(
                "/mcp?toolsets=all&readonly=false&x-mcp-readonly=false",
                content=RPC,
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )

        assert response.status_code == 200
        assert [seen.path for seen in setup.upstream.seen] == ["/"]

    @pytest.mark.parametrize("method", ["HEAD", "OPTIONS", "TRACE"])
    async def test_other_methods_never_reach_the_upstream(
        self,
        setup: Setup,  # noqa: F811
        method: str,
    ) -> None:
        async with setup.raw() as http:
            response = await http.request(
                method, "/mcp", headers={"Authorization": f"Bearer {TOKEN}"}
            )

        assert response.status_code in {405, 404}
        assert setup.upstream.seen == []

    @pytest.mark.parametrize(
        "header",
        [
            f"Bearer  {TOKEN}",
            f"Bearer {TOKEN} ",
            f"Bearer {TOKEN}\t",
            f"Bearer {TOKEN[:-1]}",
            "Bearer " + "A" * 100_000,
            f"Bearer {PAT}",
        ],
        ids=["double space", "trailing space", "trailing tab", "short", "huge", "the pat"],
    )
    async def test_a_malformed_bearer_is_a_401_that_reaches_no_upstream(
        self,
        setup: Setup,  # noqa: F811
        header: str,
    ) -> None:
        async with setup.raw() as http:
            response = await http.post(
                "/mcp",
                content=RPC,
                headers={"Authorization": header, "Content-Type": "application/json"},
            )

        assert response.status_code == 401
        assert setup.upstream.seen == []
        assert PAT not in response.text

    async def test_a_caller_cannot_widen_the_upstream_by_header(self, setup: Setup) -> None:  # noqa: F811
        async with setup.raw() as http:
            await http.post(
                "/mcp",
                content=RPC,
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "X-MCP-Toolsets": "all",
                    "X-MCP-Readonly": "false",
                    "X-MCP-Tools": "delete_file",
                    "X-Forwarded-For": "10.0.0.1",
                    "Cookie": "a=b",
                },
            )

        names = set(setup.upstream.seen[0].headers)
        assert not {n for n in names if n.startswith("x-")}
        assert "cookie" not in names
        assert setup.upstream.seen[0].headers["authorization"] == f"Bearer {PAT}"

    async def test_an_empty_body_is_not_a_crash_and_never_leaks_the_pat(
        self,
        setup: Setup,  # noqa: F811
    ) -> None:
        async with setup.raw() as http:
            response = await http.post(
                "/mcp", content=b"", headers={"Authorization": f"Bearer {TOKEN}"}
            )

        assert response.status_code < 500 or response.status_code == 503
        assert PAT not in response.text


class TestPinEdges:
    def test_a_name_in_another_case_is_not_the_pinned_tool(self) -> None:
        pin = listed("issue_write")

        assert not tool.pin_holds(server(pinned=[pin], listing=[pin]), "Issue_Write", offered(pin))

    def test_an_empty_pin_holds_nothing(self) -> None:
        pin = listed("issue_write")

        assert not tool.pin_holds(server(pinned=[], listing=[pin]), "issue_write", offered(pin))

    def test_an_added_property_in_the_schema_denies(self) -> None:
        pin = listed("echo")
        wider = replace(
            pin,
            input_schema={
                **pin.input_schema,
                "properties": {"text": {"type": "string"}, "owner": {"type": "string"}},
            },
        )

        assert not tool.pin_holds(server(pinned=[pin], listing=[wider]), "echo", offered(pin))

    def test_a_description_that_differs_by_one_space_denies(self) -> None:
        pin = listed("echo")
        spaced = replace(pin, description=pin.description + " ")

        assert not tool.pin_holds(server(pinned=[pin], listing=[spaced]), "echo", offered(pin))

    def test_a_description_with_a_hidden_character_denies(self) -> None:
        pin = listed("echo")
        hidden = replace(pin, description=pin.description + "​")

        assert not tool.pin_holds(server(pinned=[pin], listing=[hidden]), "echo", offered(pin))

    def test_the_digest_and_changes_agree_on_an_empty_listing(self) -> None:
        pin = [listed("a")]

        assert tool.listing_changes(pin, []) == ["removed: a"]
        assert tool.listing_changes(None, []) == []
        assert len(tool.listing_digest([])) == 64

    def test_the_digest_ignores_listing_order_and_sees_a_schema_change(self) -> None:
        a, b = listed("a"), listed("b")

        assert tool.listing_digest([a, b]) == tool.listing_digest([b, a])
        assert tool.listing_digest([a, b]) != tool.listing_digest(
            [a, replace(b, description="other")]
        )
