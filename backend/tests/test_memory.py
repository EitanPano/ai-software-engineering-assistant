"""Long-term memory: the request rules, the routes, the extraction after a completed run and the
caller binding of the `recall` tool. The scripted model is `tests/fake_anthropic.py` (`[[fact:...]]`
for what extraction finds), Voyage is `tests/fake_voyage.py`, and the servers are
`tests/fake_mcp.py`."""

import json
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest
from pydantic import ValidationError

from app.api.conversation.controller import read_user_text
from app.api.memory import controller as memory_controller
from app.api.memory.controller import extract_memory, recall_for_tool
from app.api.memory.schema import Memory, MemoryExtraction, MemoryPage
from app.config.constants import MEMORY
from app.models.memory.enums import ToolRecallCode
from app.models.memory.type import ToolRecallFailed
from app.models.tool_policy.enums import PolicyEffect
from app.services import mcp
from app.services.event import RUN_COMPLETED, drain, subscribe
from app.services.utils import clock
from app.services.utils.pagination import encode_cursor
from app.services.voyage import EmbeddingUnavailable
from tests import fake_voyage
from tests.agent_support import RecordingFake, bearer, stream
from tests.approval_support import LabBacked, settle
from tests.fake_mcp import Servers
from tests.fake_mcp import mcp_servers as mcp_servers
from tests.knowledge_support import KNOWLEDGE_URL, TOKEN
from tests.knowledge_support import knowledge as knowledge
from tests.memory_support import FACT, Stored, owner_of, remember, stored_memories
from tests.source_support import admin_bearer
from tests.store import store_backed
from tests.support import error_of, recording_logger
from tests.test_agent import Journey, finish_of


class TestRequestSchema:
    """The request rules of `GET /api/memory` and `DELETE /api/memory/{id}`, before any store."""

    async def test_the_list_needs_a_token(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/memory")

        assert res.status_code == 401
        assert error_of(res).code == "unauthenticated"
        assert res.json()["requestId"]

    async def test_the_delete_needs_a_token(self, client: httpx.AsyncClient) -> None:
        res = await client.delete("/api/memory/some-id")

        assert res.status_code == 401
        assert error_of(res).code == "unauthenticated"

    @pytest.mark.parametrize("limit", ["0", "101", "abc"])
    async def test_the_list_rejects_a_limit_outside_1_to_100(
        self, client: httpx.AsyncClient, limit: str
    ) -> None:
        res = await client.get(f"/api/memory?limit={limit}", headers=bearer())

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"
        assert res.json()["requestId"]

    async def test_the_list_rejects_a_bad_cursor(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/memory?cursor=nope!", headers=bearer())

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"

    async def test_the_list_rejects_a_cursor_whose_id_holds_a_nul(
        self, client: httpx.AsyncClient
    ) -> None:
        cursor = encode_cursor({"created_at": "2026-11-02T00:00:00+00:00", "id": "a\x00b"})

        res = await client.get(f"/api/memory?cursor={cursor}", headers=bearer())

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"


class TestWireShape:
    def test_a_memory_holds_four_fields_and_no_embedding(self) -> None:
        memory = Memory(
            id="m", content="c", conversation_id="k", created_at="2026-11-02T00:00:00.000Z"
        )

        assert set(memory.model_dump(by_alias=True)) == {
            "id",
            "content",
            "conversationId",
            "createdAt",
        }

    def test_a_page_holds_items_and_a_next_cursor(self) -> None:
        assert set(MemoryPage(items=[], next_cursor=None).model_dump(by_alias=True)) == {
            "items",
            "nextCursor",
        }

    def test_an_extraction_holds_a_list_of_facts(self) -> None:
        assert MemoryExtraction.model_validate({"facts": ["a"]}).facts == ["a"]
        with pytest.raises(ValidationError):
            MemoryExtraction.model_validate({"facts": "a"})
        with pytest.raises(ValidationError):
            MemoryExtraction.model_validate({})


def side_requests(fake: RecordingFake) -> list[dict[str, object]]:
    return [request for request in fake.requests if not request.get("stream")]


@store_backed
@pytest.mark.usefixtures("fakes")
class TestRoutes(LabBacked):
    async def test_lists_the_callers_memories_newest_first_with_no_embedding(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer("user-a")
        start = clock.now()
        first = await remember("user-a", "First fact.", created_at=start)
        second = await remember("user-a", "Second fact.", created_at=start + timedelta(seconds=1))
        await remember("user-b", "Someone else's fact.")

        res = await client.get("/api/memory", headers=headers)

        assert res.status_code == 200
        assert [item["id"] for item in res.json()["items"]] == [second, first]
        assert res.json()["nextCursor"] is None
        assert set(res.json()["items"][0]) == {"id", "content", "conversationId", "createdAt"}
        assert res.json()["items"][0]["conversationId"] == "conversation-1"

    async def test_pages_by_cursor(self, client: httpx.AsyncClient) -> None:
        headers = bearer("user-a")
        start = clock.now()
        ids = [
            await remember("user-a", f"Fact {n}.", created_at=start + timedelta(seconds=n))
            for n in range(3)
        ]

        page = await client.get("/api/memory?limit=2", headers=headers)
        rest = await client.get(
            f"/api/memory?limit=2&cursor={page.json()['nextCursor']}", headers=headers
        )

        assert [item["id"] for item in page.json()["items"]] == [ids[2], ids[1]]
        assert [item["id"] for item in rest.json()["items"]] == [ids[0]]
        assert rest.json()["nextCursor"] is None

    async def test_an_empty_list_is_a_page_with_no_items(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/memory", headers=bearer())

        assert res.status_code == 200
        assert res.json() == {"items": [], "nextCursor": None}

    async def test_deletes_the_row_and_its_embedding(self, client: httpx.AsyncClient) -> None:
        memory_id = await remember("user-a", FACT)

        res = await client.delete(f"/api/memory/{memory_id}", headers=bearer("user-a"))

        assert res.status_code == 204
        assert res.content == b""
        assert await stored_memories() == []

    async def test_another_users_memory_is_a_404_and_stays(self, client: httpx.AsyncClient) -> None:
        memory_id = await remember("user-a", FACT)

        res = await client.delete(f"/api/memory/{memory_id}", headers=bearer("user-b"))

        assert res.status_code == 404
        assert error_of(res).code == "not_found"
        assert res.json()["requestId"]
        assert len(await stored_memories()) == 1

    async def test_an_admin_does_not_reach_another_users_memory(
        self, client: httpx.AsyncClient
    ) -> None:
        memory_id = await remember("user-a", FACT)

        res = await client.delete(f"/api/memory/{memory_id}", headers=admin_bearer())

        assert res.status_code == 404
        assert len(await stored_memories()) == 1

    async def test_an_unknown_id_is_a_404(self, client: httpx.AsyncClient) -> None:
        res = await client.delete("/api/memory/nothing", headers=bearer())

        assert res.status_code == 404
        assert error_of(res).code == "not_found"


@store_backed
@pytest.mark.usefixtures("fakes")
class TestExtraction(LabBacked):
    async def test_a_stated_fact_is_stored_once_with_owner_conversation_and_embedding(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)
        run_id, frames = await journey.run(
            f"I keep deploy notes in ops/RUNBOOK.md. [[fact:{FACT}]]"
        )
        assert finish_of(frames).event["status"] == "completed"

        await extract_memory(run_id=run_id)
        await extract_memory(run_id=run_id)

        assert await stored_memories() == [
            Stored(await owner_of(run_id), journey.conversation, FACT, True)
        ]

    async def test_the_side_call_holds_that_runs_user_message_alone(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)
        await journey.run("An earlier question.")
        text = f"I keep deploy notes in ops/RUNBOOK.md. [[fact:{FACT}]]"
        run_id, _ = await journey.run(text)

        await extract_memory(run_id=run_id)

        request = side_requests(fake_model)[-1]
        assert request["messages"] == [{"role": "user", "content": text}]
        assert "scripted" not in str(request)
        assert "earlier question" not in str(request)

    async def test_a_message_with_no_fact_stores_nothing(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        run_id, _ = await Journey(client).run("How do I run the tests?")

        await extract_memory(run_id=run_id)

        assert await stored_memories() == []
        assert len(side_requests(fake_model)) == 1

    async def test_a_completed_run_publishes_run_completed_and_a_failed_one_does_not(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        seen: list[str] = []
        unsubscribe = subscribe(RUN_COMPLETED, lambda payload: seen.append(payload["run_id"]))
        try:
            journey = Journey(client)
            done, _ = await journey.run("hello")
            await Journey(client).run("[[refuse]]")
            await drain()
        finally:
            unsubscribe()

        assert seen == [done]

    async def test_a_resumed_run_publishes_run_completed_once_it_completes(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, mcp_servers: Servers
    ) -> None:
        await mcp_servers.register_lab({"echo": PolicyEffect.ask})
        seen: list[str] = []
        unsubscribe = subscribe(RUN_COMPLETED, lambda payload: seen.append(payload["run_id"]))
        try:
            journey = Journey(client)
            run_id, paused = await journey.run("[[tool:lab__echo]]")
            await drain()
            assert seen == []
            await settle(journey, run_id)
            await drain()
        finally:
            unsubscribe()

        assert [frame.event["type"] for frame in paused][-1] == "approval_requested"
        assert seen == [run_id]

    async def test_a_repeated_fact_and_a_key_shaped_one_are_not_stored(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)
        first, _ = await journey.run(f"[[fact:{FACT}]]")
        again, _ = await journey.run(f"[[fact:{FACT.upper()}]] [[fact:{FACT}]]")
        key, _ = await journey.run(
            "[[fact:The person's key is sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789.]]"
        )

        for run_id in (first, again, key):
            await extract_memory(run_id=run_id)

        assert [row.content for row in await stored_memories()] == [FACT]

    async def test_stores_at_most_the_limit_and_drops_long_and_nul_facts(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_id, _ = await Journey(client).run("hello")
        facts = [
            "x" * (MEMORY.fact_max_chars + 1),
            "A fact with a NUL\x00 in it.",
            *(f"Fact number {n}." for n in range(MEMORY.extract_limit + 3)),
        ]

        async def found(*args: object, **kwargs: object) -> MemoryExtraction:
            del args, kwargs
            return MemoryExtraction(facts=facts)

        monkeypatch.setattr(memory_controller, "parse_turn", found)

        await extract_memory(run_id=run_id)

        # The first `extract_limit` facts are read: the long one, the NUL one and three good ones.
        stored = sorted(row.content for row in await stored_memories())
        assert stored == ["Fact number 0.", "Fact number 1.", "Fact number 2."]

    async def test_keeps_only_the_room_a_person_has_left(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_id, _ = await Journey(client).run("hello")
        await remember(await owner_of(run_id), "An older fact.")
        monkeypatch.setattr(memory_controller, "MEMORY", replace(MEMORY, max_per_user=2))

        async def found(*args: object, **kwargs: object) -> MemoryExtraction:
            del args, kwargs
            return MemoryExtraction(facts=["New fact A.", "New fact B.", "New fact C."])

        monkeypatch.setattr(memory_controller, "parse_turn", found)

        await extract_memory(run_id=run_id)

        assert sorted(row.content for row in await stored_memories()) == [
            "An older fact.",
            "New fact A.",
        ]

    async def test_a_store_failure_on_a_later_fact_stores_none(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_id, _ = await Journey(client).run("hello")

        async def found(*args: object, **kwargs: object) -> MemoryExtraction:
            del args, kwargs
            return MemoryExtraction(facts=["First fact.", "Second fact."])

        async def embeddings(texts: object) -> list[list[float]]:
            del texts
            return [[0.1] * 1024, [0.1] * 3]  # the second does not fit halfvec(1024)

        monkeypatch.setattr(memory_controller, "parse_turn", found)
        monkeypatch.setattr(memory_controller, "embed_documents", embeddings)

        await extract_memory(run_id=run_id)

        assert await stored_memories() == []

    async def test_the_user_message_is_read_from_its_own_conversation_only(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)
        run_id, _ = await journey.run("What is my question?")

        assert await read_user_text(conversation_id=journey.conversation, run_id=run_id) == (
            "What is my question?"
        )
        assert await read_user_text(conversation_id="another", run_id=run_id) is None

    async def test_a_person_at_the_limit_costs_no_paid_call(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        journey = Journey(client)
        run_id, _ = await journey.run(f"[[fact:{FACT}]]")
        await remember(await owner_of(run_id), "An older fact.")
        monkeypatch.setattr(memory_controller, "MEMORY", replace(MEMORY, max_per_user=1))

        await extract_memory(run_id=run_id)

        assert side_requests(fake_model) == []
        assert [row.content for row in await stored_memories()] == ["An older fact."]

    @pytest.mark.parametrize(
        "marker", ["[[extract_refused]]", "[[extract_invalid]]", "[[extract_cut]]"]
    )
    async def test_a_failed_side_call_touches_nothing_and_logs_no_content(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        monkeypatch: pytest.MonkeyPatch,
        marker: str,
    ) -> None:
        logger, sink = recording_logger()
        monkeypatch.setattr(memory_controller, "log", logger)
        journey = Journey(client)
        run_id, frames = await journey.run(f"my PRIVATE-77 note {marker} [[fact:{FACT}]]")

        await extract_memory(run_id=run_id)

        assert await stored_memories() == []
        assert await stream(client, journey.headers, run_id) == frames
        assert finish_of(frames).event["status"] == "completed"
        assert "PRIVATE-77" not in "\n".join(sink.lines)
        assert sink.lines

    async def test_voyage_down_stores_nothing_and_logs_no_content(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger, sink = recording_logger()
        monkeypatch.setattr(memory_controller, "log", logger)
        run_id, _ = await Journey(client).run(f"my PRIVATE-77 note [[fact:{FACT}]]")

        async def down(texts: object) -> list[list[float]]:
            del texts
            raise EmbeddingUnavailable

        monkeypatch.setattr(memory_controller, "embed_documents", down)

        await extract_memory(run_id=run_id)

        assert await stored_memories() == []
        assert "PRIVATE-77" not in "\n".join(sink.lines)
        assert sink.lines


@store_backed
@pytest.mark.usefixtures("fakes", "knowledge")
class TestCallerBinding(LabBacked):
    async def recall_as(self, user_id: str | None, query: str = FACT) -> mcp.ToolResult:
        return await mcp.call_tool(
            KNOWLEDGE_URL, "recall", {"query": query}, token=TOKEN, user_id=user_id
        )

    async def test_a_person_recalls_their_own_memories(self) -> None:
        await remember("user-a", FACT)

        result = await self.recall_as("user-a")

        assert result.is_error is False
        assert [m["content"] for m in json.loads(result.text)["memories"]] == [FACT]

    async def test_a_second_person_recalls_none_of_the_firsts(self) -> None:
        await remember("user-a", FACT)

        result = await self.recall_as("user-b")

        assert result.is_error is False
        assert json.loads(result.text) == {"memories": []}

    async def test_no_meta_is_no_caller_with_no_embedding_and_no_read(self) -> None:
        await remember("user-a", FACT)
        fake_voyage.state.requests.clear()

        result = await self.recall_as(None)

        assert (result.is_error, result.text) == (True, "no_caller")
        assert fake_voyage.state.requests == []

    async def test_the_rule_refuses_a_missing_caller_before_anything(self) -> None:
        fake_voyage.state.requests.clear()

        with pytest.raises(ToolRecallFailed) as failure:
            await recall_for_tool(query=FACT, user_id=None)

        assert failure.value.code is ToolRecallCode.no_caller
        assert fake_voyage.state.requests == []

    async def test_an_argument_naming_a_user_is_invalid_query(self) -> None:
        fake_voyage.state.requests.clear()

        result = await mcp.call_tool(
            KNOWLEDGE_URL,
            "recall",
            {"query": FACT, "user_id": "user-a"},
            token=TOKEN,
            user_id="user-b",
        )

        assert (result.is_error, result.text) == (True, "invalid_query")
        assert fake_voyage.state.requests == []
