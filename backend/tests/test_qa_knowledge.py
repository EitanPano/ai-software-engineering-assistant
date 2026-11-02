"""QA's adversarial pass for the agent with the `knowledge` MCP server.

Two kinds of test. The "sensor" tests flip one guard off from outside the feature source (a
monkeypatch) and prove the observation channel the real tests rely on (`lab.calls`, the Voyage
request log) does move, so the gate tests in `test_agent_knowledge.py` can fail. The rest attack
the feature: a policy row missing or `ask` on the real `knowledge` tool, an outage in the middle of
a run, NUL in names and nested inputs, odd tool names, and a per-run budget."""

from dataclasses import dataclass

import httpx
import pytest

from app.api.agent import controller as agent
from app.api.run import controller as run_controller
from app.models.conversation.type import ConversationPrefix
from app.models.run.enums import ToolCallStatus
from app.models.tool_policy.enums import PolicyEffect
from app.services.anthropic import Block
from app.services.db import execute, fetch_all
from app.services.utils.jsonb import jsonb_safe
from tests import fake_anthropic, fake_voyage
from tests.agent_support import RecordingFake, bearer, send, start_conversation
from tests.fake_mcp import KNOWLEDGE_HOST, Servers
from tests.fake_mcp import mcp_servers as mcp_servers
from tests.knowledge_support import index_fixture
from tests.store import reset_store, store_backed
from tests.test_agent import Journey, finish_of, text_of


@pytest.fixture(autouse=True)
async def environment(mcp_servers: Servers, fakes: None) -> None:
    del mcp_servers, fakes
    await reset_store()
    fake_voyage.reset()


@pytest.fixture
def servers(mcp_servers: Servers) -> Servers:
    return mcp_servers


@dataclass(frozen=True)
class _Row:
    tool_name: str
    status: str
    result: str


async def rows_of(run_id: str) -> list[_Row]:
    return await fetch_all(
        _Row,
        "select tool_name, status, result from tool_call where run_id = %s order by created_at",
        (run_id,),
    )


@dataclass(frozen=True)
class _Count:
    n: int


@store_backed
class TestSensorsCanMove:
    """If the guard is off, the channel the gate tests watch shows it."""

    async def test_an_ask_policy_reaches_the_server_when_decide_is_forced_open(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await servers.register_lab(default=PolicyEffect.ask)
        monkeypatch.setattr("app.services.tool.decide", lambda effect: "allow")

        await Journey(client).run("[[tool:lab__echo]]")

        assert servers.lab.calls == [("echo", {"text": "hi"})]
        assert fake_model.requests

    async def test_a_missing_policy_row_reaches_the_server_when_decide_is_forced_open(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await servers.register_lab(default=None)
        monkeypatch.setattr("app.services.tool.decide", lambda effect: "allow")

        await Journey(client).run("[[tool:lab__echo]]")

        assert len(servers.lab.calls) == 1
        assert fake_model.requests

    async def test_a_parallel_batch_reaches_the_server_in_full_when_the_budget_is_raised(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await servers.register_lab()
        monkeypatch.setattr("app.api.agent.controller.AGENT_TOOL_CALLS_PER_RUN", 100)

        await Journey(client).run("[[many:lab__echo]]")

        assert len(servers.lab.calls) == fake_anthropic.MANY_CALLS
        assert fake_model.requests

    async def test_searches_past_the_budget_embed_when_the_budget_is_raised(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("app.api.agent.controller.AGENT_TOOL_CALLS_PER_RUN", 100)

        await Journey(client).run("[[many:knowledge__search]]")

        assert len(fake_voyage.state.requests) == fake_anthropic.MANY_CALLS
        assert fake_model.requests

    async def test_the_cross_turn_count_is_what_stops_a_loop(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await servers.register_lab()
        monkeypatch.setattr("app.api.agent.controller.AGENT_TOOL_CALLS_PER_RUN", 3)
        monkeypatch.setattr("app.api.agent.controller.AGENT_MAX_TURNS", 6)

        async def forgot(run_id: str) -> int:
            return 0

        monkeypatch.setattr("app.api.agent.controller.count_tool_calls", forgot)

        await Journey(client).run("[[loop]][[tool:lab__echo]]")

        assert len(servers.lab.calls) == 6
        assert fake_model.requests


@store_backed
class TestKnowledgePolicy:
    async def test_no_policy_row_for_search_denies_it_and_embeds_nothing(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        await execute("delete from tool_policy")

        run_id, frames = await Journey(client).run("[[research]]")

        assert [r.status for r in await rows_of(run_id)] == ["denied", "denied"]
        assert fake_voyage.state.requests == []
        assert finish_of(frames).event["status"] == "completed"
        assert fake_model.requests

    # Plan 011 changed `ask`: it used to be denied like `deny`, now the call waits for a person
    # (`awaiting_approval`). Neither reaches the server, so neither embeds.
    @pytest.mark.parametrize(
        ("effect", "status"), [("ask", "awaiting_approval"), ("deny", "denied")]
    )
    async def test_ask_and_deny_on_search_never_embed(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, effect: str, status: str
    ) -> None:
        await execute("update tool_policy set effect = %s", (effect,))

        run_id, _ = await Journey(client).run("[[research]]")

        assert {r.status for r in await rows_of(run_id)} == {status}
        assert fake_voyage.state.requests == []
        assert fake_model.requests

    async def test_a_disabled_knowledge_row_denies_a_stored_conversations_search(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)
        await journey.run("hello")  # bound to knowledge__search
        await execute("update mcp_server set enabled = false where name = 'knowledge'")

        run_id, _ = await journey.run("[[research]]")

        assert {r.status for r in await rows_of(run_id)} == {"denied"}
        assert fake_voyage.state.requests == []
        assert fake_model.requests


@store_backed
class TestOutageMidRun:
    async def test_knowledge_going_down_between_two_searches_fails_the_second_only(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await index_fixture(client)
        original = run_controller.record_tool_call
        recorded = 0

        async def down_after_first(**kwargs: object) -> None:
            nonlocal recorded
            await original(**kwargs)  # type: ignore[arg-type]
            recorded += 1
            if recorded == 1:
                servers.take_down(KNOWLEDGE_HOST)

        monkeypatch.setattr("app.api.agent.controller.record_tool_call", down_after_first)

        run_id, frames = await Journey(client).run("[[research]]")

        stored = await rows_of(run_id)
        assert [r.status for r in stored] == ["succeeded", "failed"]
        assert stored[1].result == "the tool is unavailable"
        assert finish_of(frames).event["status"] == "completed"
        assert "503" not in text_of(frames)
        assert fake_model.requests

    async def test_a_conversation_whose_first_run_met_the_outage_keeps_no_tools_after_it(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        servers.take_down(KNOWLEDGE_HOST)
        journey = Journey(client)
        await journey.run("hello")
        servers.bring_up(KNOWLEDGE_HOST)

        await journey.run("hello again")

        assert [r.get("tools") for r in fake_model.requests] == [
            fake_model.requests[0].get("tools")
        ] * len(fake_model.requests)
        assert not fake_model.requests[-1].get("tools")


@store_backed
class TestOddNames:
    """The model chooses `name`; the policy and the `tool_call` row must survive any string."""

    PREFIX = ConversationPrefix(system_prompt="s", tool_definition=[])

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "__",
            "knowledge__",
            "knowledge__search; drop table tool_call",
            "knowledge__" + "x" * 5000,
            "KNOWLEDGE__SEARCH",
            "knowledge__search__extra",
        ],
    )
    async def test_an_odd_name_is_denied_not_raised(
        self, client: httpx.AsyncClient, name: str
    ) -> None:
        run_id = await self.call_run(client)

        await self.call(run_id, name)

        assert [row.status for row in await rows_of(run_id)] == [ToolCallStatus.denied.value]
        assert fake_voyage.state.requests == []

    @staticmethod
    async def call_run(client: httpx.AsyncClient) -> str:
        """A real run, so the loop's own `_call_tool` can write its events and its row."""
        headers = bearer()
        conversation = await start_conversation(client, headers)
        return await send(client, headers, conversation, "hello")

    async def call(self, run_id: str, name: str) -> None:
        block: Block = {
            "type": "tool_use",
            "id": "toolu_odd",
            "name": name,
            "input": {"query": "q"},
        }
        answer = await agent._call_tool(run_id, "user", block, self.PREFIX, allowed=True)
        assert isinstance(answer, dict)
        assert answer["is_error"] is True

    @pytest.mark.parametrize(
        "nested", [{"a": ["x\x00"]}, {"a\x00": 1}, {"a": {"b": [{"c": "\x00"}]}}]
    )
    def test_nul_is_found_in_any_depth_and_in_keys(self, nested: object) -> None:
        assert not jsonb_safe(nested)

    def test_an_input_without_nul_is_clean(self) -> None:
        assert jsonb_safe({"a": ["x", {"b": "ü\n\t"}], "c": None, "d": 1})

    async def test_a_prefix_that_never_offered_the_tool_denies_even_with_an_allow_row(
        self, client: httpx.AsyncClient
    ) -> None:
        run_id = await self.call_run(client)

        await self.call(run_id, "knowledge__search")

        assert [row.status for row in await rows_of(run_id)] == [ToolCallStatus.denied.value]
        assert fake_voyage.state.requests == []


@store_backed
class TestBudgetIsPerRun:
    async def test_a_second_run_of_the_conversation_gets_its_own_budget(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await servers.register_lab()
        monkeypatch.setattr("app.api.agent.controller.AGENT_TOOL_CALLS_PER_RUN", 3)
        journey = Journey(client)

        await journey.run("[[many:lab__echo]]")
        await journey.run("[[many:lab__echo]]")

        assert len(servers.lab.calls) == 6
        assert fake_model.requests

    async def test_the_stored_rows_always_equal_the_calls_asked_for(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
    ) -> None:
        await servers.register_lab()

        run_id, _ = await Journey(client).run("[[many:lab__echo]]")

        counts = await fetch_all(
            _Count, "select count(*)::int as n from tool_call where run_id = %s", (run_id,)
        )
        assert counts[0].n == fake_anthropic.MANY_CALLS
        assert fake_model.requests


@store_backed
class TestSeededRows:
    async def test_after_a_reset_search_is_allowed_once_and_knowledge_has_no_stored_listing(
        self,
    ) -> None:
        await execute("update mcp_server set tool_definition = '[]', enabled = false")
        await reset_store()

        rows = await fetch_all(
            _Row,
            "select p.tool_name, p.effect as status, s.name as result from tool_policy p "
            "join mcp_server s on s.id = p.mcp_server_id",
        )
        assert sorted((r.tool_name, r.status) for r in rows if r.result == "knowledge") == [
            ("recall", "allow"),
            ("search", "allow"),
        ]
        # 0011 seeds the seven GitHub tools beside it: reads allow, the two writes ask.
        github = {r.tool_name: r.status for r in rows if r.result == "github"}
        assert len(github) == 7
        assert {name for name, effect in github.items() if effect == "ask"} == {
            "issue_write",
            "add_issue_comment",
        }
        assert {r.result for r in rows} == {"knowledge", "github"}
        enabled = await fetch_all(
            _Row,
            "select name as tool_name, 'x' as status, coalesce(url, '') as result "
            "from mcp_server where enabled",
        )
        assert [(r.tool_name, r.result) for r in enabled] == [("knowledge", "")]
