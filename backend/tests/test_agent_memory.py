"""The agent with long-term memory: it recalls a person's facts through `knowledge__recall`, for
that person alone, and a deleted memory is never recalled again. The scripted model is
`tests/fake_anthropic.py` (`[[recall]]`), the servers are `tests/fake_mcp.py`: the real `knowledge`
over the test database, and `lab`."""

import json
from dataclasses import dataclass

import httpx
import pytest

from app.api.agent import controller as agent
from app.config.constants import AGENT_TOOL_CALLS_PER_RUN
from app.models.conversation.type import ConversationPrefix
from app.models.mcp_server.constants import RECALL_TOOL
from app.services import tool
from app.services.db import execute, fetch_all
from tests import fake_anthropic, fake_voyage
from tests.agent_support import RecordingFake, bearer, send, start_conversation
from tests.approval_support import LabBacked, settle
from tests.fake_mcp import KNOWLEDGE_HOST, Servers
from tests.fake_mcp import mcp_servers as mcp_servers
from tests.memory_support import FACT, remember
from tests.store import store_backed
from tests.test_agent import Journey, finish_of, text_of


@dataclass(frozen=True)
class _Call:
    tool_use_id: str
    mcp_server_id: str | None
    tool_name: str
    arguments: dict[str, object]
    result: str
    status: str


async def calls_of(run_id: str) -> list[_Call]:
    return await fetch_all(
        _Call,
        "select tool_use_id, mcp_server_id, tool_name, arguments, result, status "
        "from tool_call where run_id = %s order by created_at, tool_use_id",
        (run_id,),
    )


def journey_of(client: httpx.AsyncClient, user_id: str) -> Journey:
    """A journey that signs in as `user_id`, so a test can store memories for that person."""
    journey = Journey(client)
    journey.headers = bearer(user_id)
    return journey


@dataclass(frozen=True)
class _Snapshot:
    messages: list[object]
    tool_calls: list[object]
    events: list[object]


async def snapshot(conversation_id: str) -> _Snapshot:
    """Every stored trace of what a conversation read: its turns, its tool calls and its events."""

    @dataclass(frozen=True)
    class _Json:
        document: object

    async def one(query: str) -> list[object]:
        rows = await fetch_all(_Json, query, (conversation_id,))
        return [row.document for row in rows]

    return _Snapshot(
        messages=await one(
            "select to_jsonb(m) - 'created_at' as document from message m "
            "where conversation_id = %s order by position"
        ),
        tool_calls=await one(
            "select to_jsonb(t) - 'created_at' - 'updated_at' as document from tool_call t "
            "where run_id in (select id from run where conversation_id = %s) "
            "order by t.tool_use_id"
        ),
        events=await one(
            "select to_jsonb(e) - 'created_at' as document from run_event e "
            "where run_id in (select id from run where conversation_id = %s) "
            "order by e.run_id, e.sequence"
        ),
    )


@store_backed
@pytest.mark.usefixtures("fakes")
class TestRecall(LabBacked):
    async def test_a_new_conversation_recalls_a_fact_only_in_a_tool_result(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        await remember("user-a", FACT)
        journey = journey_of(client, "user-a")

        run_id, frames = await journey.run("[[recall]]")

        assert text_of(frames) == f"From memory: {FACT}"
        assert finish_of(frames).event["status"] == "completed"
        (stored,) = await calls_of(run_id)
        assert (stored.mcp_server_id, stored.tool_name, stored.status) == (
            "knowledge",
            "recall",
            "succeeded",
        )
        assert stored.arguments == {"query": fake_anthropic.RECALL_QUERY}
        for request in fake_model.requests:
            assert FACT not in json.dumps(request["system"])
            assert FACT not in json.dumps(request.get("tools"))
            for message in request["messages"]:  # type: ignore[attr-defined]
                for block in message["content"]:
                    if FACT in json.dumps(block):
                        assert block["type"] == "tool_result"
        assert FACT in json.dumps(fake_model.requests[-1]["messages"])

    async def test_a_conversation_frozen_without_the_tool_is_offered_nothing_new(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await remember("user-a", FACT)
        servers.take_down(KNOWLEDGE_HOST)
        journey = journey_of(client, "user-a")
        await journey.run("hello")
        servers.bring_up(KNOWLEDGE_HOST)
        fake_voyage.state.requests.clear()

        run_id, frames = await journey.run("[[recall]]")

        assert text_of(frames) == fake_anthropic.NOT_RECALLABLE
        assert await calls_of(run_id) == []
        assert fake_voyage.state.requests == []

    async def test_a_recall_spends_the_runs_tool_call_budget(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = journey_of(client, "user-a")

        run_id, _ = await journey.run("[[many:knowledge__recall]]")

        statuses = [call.status for call in await calls_of(run_id)]
        assert statuses.count("succeeded") == AGENT_TOOL_CALLS_PER_RUN
        assert statuses.count("denied") == fake_anthropic.MANY_CALLS - AGENT_TOOL_CALLS_PER_RUN

    async def test_at_deny_nothing_reaches_the_server(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        await remember("user-a", FACT)
        await execute("update tool_policy set effect = 'deny' where id = 'knowledge-recall'")
        fake_voyage.state.requests.clear()
        journey = journey_of(client, "user-a")

        run_id, frames = await journey.run("[[recall]]")

        assert [call.status for call in await calls_of(run_id)] == ["denied"]
        assert fake_voyage.state.requests == []
        assert text_of(frames) == fake_anthropic.NOTHING_REMEMBERED

    async def test_search_answers_as_before(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        run_id, frames = await journey_of(client, "user-a").run("[[research]]")

        assert [call.tool_name for call in await calls_of(run_id)] == ["search", "search"]
        assert text_of(frames) == fake_anthropic.NO_ANSWER


@store_backed
@pytest.mark.usefixtures("fakes")
class TestOwnerOnly(LabBacked):
    async def test_a_second_person_recalls_none_of_the_firsts_through_the_loop(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        await remember("user-a", FACT)

        _, frames = await journey_of(client, "user-b").run("[[recall]]")

        assert text_of(frames) == fake_anthropic.NOTHING_REMEMBERED
        assert FACT not in json.dumps(fake_model.requests)

    async def test_the_caller_is_the_runs_owner_on_a_call_approved_and_resumed(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        await remember("user-a", FACT)
        await execute("update tool_policy set effect = 'ask' where id = 'knowledge-recall'")
        journey = journey_of(client, "user-a")
        run_id, paused = await journey.run("[[recall]]")
        assert paused[-1].event["type"] == "approval_requested"

        frames = await settle(journey, run_id)

        assert text_of(frames) == f"From memory: {FACT}"

    async def test_github_and_a_third_party_server_receive_no_caller(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab()
        await servers.accept_github()
        journey = journey_of(client, "user-a")

        await journey.run("[[tool:lab__echo]]")
        await journey.run("[[tool:github__issue_read]]")

        assert servers.lab.callers == [None]
        assert servers.github.callers == [None]

    async def test_an_input_naming_a_user_fails_its_schema_before_any_server(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> None:
        conversation = await start_conversation(client, bearer("user-b"))
        run_id = await send(client, bearer("user-b"), conversation, "hello")
        prefix = ConversationPrefix(
            system_prompt="s", tool_definition=list(tool.definitions({"knowledge": [RECALL_TOOL]}))
        )
        block: dict[str, object] = {
            "type": "tool_use",
            "id": "toolu_user",
            "name": "knowledge__recall",
            "input": {"query": "q", "user_id": "user-a"},
        }
        reached = servers.reached(KNOWLEDGE_HOST)
        fake_voyage.state.requests.clear()

        answer = await agent._call_tool(run_id, "user-b", block, prefix, allowed=True)

        assert isinstance(answer, dict)
        assert answer["is_error"] is True
        assert [call.status for call in await calls_of(run_id)] == ["failed"]
        assert servers.reached(KNOWLEDGE_HOST) == reached
        assert fake_voyage.state.requests == []


@store_backed
@pytest.mark.usefixtures("fakes")
class TestDeleted(LabBacked):
    async def test_a_deleted_memory_is_never_recalled_and_what_a_conversation_read_stays(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        memory_id = await remember("user-a", FACT)
        journey = journey_of(client, "user-a")
        run_id, frames = await journey.run("[[recall]]")
        assert text_of(frames) == f"From memory: {FACT}"
        before = await snapshot(journey.conversation)

        res = await client.delete(f"/api/memory/{memory_id}", headers=journey.headers)
        again, later = await journey.run("[[recall]]")

        assert res.status_code == 204
        assert text_of(later) == fake_anthropic.NOTHING_REMEMBERED
        assert finish_of(later).event["status"] == "completed"
        after = await snapshot(journey.conversation)
        assert after.messages[: len(before.messages)] == before.messages
        assert [c for c in after.tool_calls if c in before.tool_calls] == before.tool_calls
        assert [e for e in before.events if e in after.events] == before.events
        assert FACT in (await calls_of(run_id))[0].result
        assert again != run_id
        # The conversation that read it still carries it, and its next request was accepted.
        assert FACT in json.dumps(fake_model.requests[-1]["messages"])

    async def test_a_new_conversation_recalls_nothing_after_a_delete(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        memory_id = await remember("user-a", FACT)
        journey = journey_of(client, "user-a")
        await client.delete(f"/api/memory/{memory_id}", headers=journey.headers)

        _, frames = await journey.run("[[recall]]")

        assert text_of(frames) == fake_anthropic.NOTHING_REMEMBERED
