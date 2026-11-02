"""`python -m app.infra.scripts.accept_mcp_server <name>`: the admin's act that pins a third-party
server's tools. It prints the live listing whole, its digest and what changed from the pin, takes a
yes, then stores exactly what it printed and enables the row. Anything else writes nothing."""

import json
from dataclasses import dataclass, replace

import httpx
import pytest

from app.infra.scripts.accept_mcp_server import main
from app.models.mcp_server.type import ListedTool
from app.services import tool
from app.services.db import execute, fetch_one
from tests.agent_support import RecordingFake
from tests.approval_support import LabBacked
from tests.fake_github_mcp import recorded_tools
from tests.fake_mcp import GITHUB_HOST, LAB_TOOLS, Servers
from tests.fake_mcp import mcp_servers as mcp_servers
from tests.rewrite_app import Rewrite
from tests.store import store_backed
from tests.support import recording_logger
from tests.test_agent import Journey

pytestmark = store_backed


@dataclass(frozen=True)
class _Row:
    enabled: bool
    tool_definition: list[dict[str, object]] | None
    pinned_tool_definition: list[dict[str, object]] | None


async def row(name: str = "github") -> _Row:
    found = await fetch_one(
        _Row,
        "select enabled, tool_definition, pinned_tool_definition from mcp_server where name = %s",
        (name,),
    )
    assert found is not None
    return found


def document(tools: list[ListedTool]) -> list[dict[str, object]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


class Run:
    """One run of the script with a scripted answer, keeping what it printed."""

    def __init__(self, answer: str = "yes") -> None:
        self.answer = answer
        self.printed: list[str] = []
        self.asked = 0
        self.logs = recording_logger()

    def reply(self) -> str:
        self.asked += 1
        return self.answer

    async def __call__(self, argv: list[str]) -> int:
        return await main(
            argv, logger=self.logs[0], read_answer=self.reply, write=self.printed.append
        )

    @property
    def output(self) -> str:
        return "\n".join(self.printed)


class TestAccept(LabBacked):
    async def test_stores_exactly_what_it_printed_and_enables_the_row(
        self, servers: Servers
    ) -> None:
        run = Run()

        assert await run(["github"]) == 0

        stored = await row()
        assert stored.enabled is True
        assert stored.pinned_tool_definition == document(recorded_tools())
        assert stored.tool_definition == document(recorded_tools())
        # The listing as printed: every tool whole, so the admin read what is stored.
        for entry in document(recorded_tools()):
            assert json.dumps(entry, indent=2, sort_keys=True) in run.output
        assert tool.listing_digest(recorded_tools()) in run.output
        assert run.asked == 1

    async def test_a_new_conversation_then_offers_the_tools(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
    ) -> None:
        await Run()(["github"])

        await Journey(client).run("hello")

        names = [d["name"] for d in fake_model.requests[0]["tools"]]  # type: ignore[attr-defined]
        assert "github__add_issue_comment" in names
        assert "knowledge__search" in names

    async def test_prints_what_changed_from_the_pin(self, servers: Servers) -> None:
        await Run()(["github"])
        servers.github.tools[:] = [
            replace(t, description="Reworded.") if t.name == "issue_read" else t
            for t in servers.github.tools
            if t.name != "list_issues"
        ]
        servers.github.tools.append(ListedTool("search_code", "Searches code.", {"type": "object"}))
        run = Run()

        assert await run(["github"]) == 0

        assert "changed: issue_read" in run.output
        assert "removed: list_issues" in run.output
        assert "added: search_code" in run.output
        stored = await row()
        assert stored.pinned_tool_definition == document(servers.github.tools)

    async def test_says_it_is_the_first_pin_when_there_is_none(self, servers: Servers) -> None:
        run = Run()

        await run(["github"])

        assert "no earlier pin" in run.output

    async def test_says_nothing_changed_when_the_pin_is_current(self, servers: Servers) -> None:
        await Run()(["github"])
        run = Run()

        assert await run(["github"]) == 0

        assert "unchanged" in run.output

    async def test_a_server_with_an_address_of_its_own_is_accepted_too(
        self, servers: Servers
    ) -> None:
        await servers.register_lab(pinned=False)
        run = Run()

        assert await run(["lab"]) == 0

        assert (await row("lab")).pinned_tool_definition == document(list(LAB_TOOLS))


class TestRefusals(LabBacked):
    @pytest.mark.parametrize("answer", ["no", "", "y", "Yes please", "yes!", "  "])
    async def test_anything_but_a_yes_exits_1_and_writes_nothing(
        self, servers: Servers, answer: str
    ) -> None:
        run = Run(answer)

        assert await run(["github"]) == 1

        stored = await row()
        assert (stored.enabled, stored.pinned_tool_definition, stored.tool_definition) == (
            False,
            None,
            None,
        )
        # The listing was shown first: the person said no to something they read.
        assert tool.listing_digest(recorded_tools()) in run.output

    async def test_a_yes_with_spaces_around_it_counts(self, servers: Servers) -> None:
        assert await Run("  yes \n")(["github"]) == 0

    async def test_an_unknown_name_exits_1_and_asks_nothing(self, servers: Servers) -> None:
        run = Run()

        assert await run(["nothing"]) == 1

        assert run.asked == 0

    async def test_knowledge_exits_1_and_writes_nothing(self, servers: Servers) -> None:
        before = await row("knowledge")
        run = Run()

        assert await run(["knowledge"]) == 1

        assert run.asked == 0
        assert await row("knowledge") == before

    async def test_a_server_that_does_not_answer_exits_1_and_writes_nothing(
        self, servers: Servers
    ) -> None:
        servers.take_down(GITHUB_HOST)
        run = Run()

        assert await run(["github"]) == 1

        stored = await row()
        assert (stored.enabled, stored.pinned_tool_definition) == (False, None)
        assert run.asked == 0

    async def test_an_empty_listing_is_not_accepted(self, servers: Servers) -> None:
        servers.github.tools[:] = []
        run = Run()

        assert await run(["github"]) == 1

        assert (await row()).pinned_tool_definition is None

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
    async def test_what_the_store_cannot_hold_exits_1_and_writes_nothing(
        self, servers: Servers, schema: dict[str, object], swaps: dict[bytes, bytes]
    ) -> None:
        servers.github.tools[:] = [ListedTool(name="odd", description="d", input_schema=schema)]
        servers.hosts.apps[GITHUB_HOST] = Rewrite(servers.hosts.apps[GITHUB_HOST], swaps)  # type: ignore[assignment]
        run = Run()

        assert await run(["github"]) == 1

        assert (run.asked, run.printed) == (0, [])
        assert (await row()).pinned_tool_definition is None

    async def test_a_tool_name_with_terminal_escapes_is_refused_before_anything_is_printed(
        self, servers: Servers
    ) -> None:
        hostile = "x\x1b[2J\x1b[Hunchanged from the pin"
        servers.github.tools[:] = [replace(servers.github.tools[0], name=hostile)]
        run = Run()

        assert await run(["github"]) == 1

        assert run.asked == 0
        assert run.printed == []
        assert "\x1b" not in "".join(run.printed)
        stored = await row()
        assert (stored.enabled, stored.pinned_tool_definition) == (False, None)

    async def test_a_name_outside_the_apis_character_set_is_refused(self, servers: Servers) -> None:
        servers.github.tools[:] = [replace(servers.github.tools[0], name="has space.dot")]
        run = Run()

        assert await run(["github"]) == 1

        assert (run.asked, run.printed) == (0, [])
        assert (await row()).pinned_tool_definition is None

    async def test_a_name_listed_twice_is_refused(self, servers: Servers) -> None:
        first = servers.github.tools[0]
        servers.github.tools[:] = [first, replace(first, description="a second, different one")]
        run = Run()

        assert await run(["github"]) == 1

        assert (run.asked, run.printed) == (0, [])
        assert (await row()).pinned_tool_definition is None

    @pytest.mark.parametrize("argv", [[], ["github", "extra"], ["--force"], ["-h"]])
    async def test_the_wrong_arguments_exit_1(self, servers: Servers, argv: list[str]) -> None:
        run = Run()

        assert await run(argv) == 1

        assert run.asked == 0
        assert (await row()).pinned_tool_definition is None

    async def test_a_policy_row_is_never_edited(self, servers: Servers) -> None:
        await execute("update tool_policy set effect = 'deny' where id = 'github-issue_read'")

        await Run()(["github"])

        effect = await fetch_one(
            _Effect, "select effect from tool_policy where id = 'github-issue_read'"
        )
        assert effect is not None
        assert effect.effect == "deny"


@dataclass(frozen=True)
class _Effect:
    effect: str
