"""The `knowledge` MCP server: what its `search` tool returns and refuses, how it is bounded, and
who may call it. It runs the real server (`create_app`) in process on the scripted Voyage and the
test database; the agent that calls it is `tests/test_agent_knowledge.py`."""

import asyncio
import json
from dataclasses import replace

import httpx
import httpx2
import pytest

from app.api.search import controller as search_controller
from app.config.constants import KNOWLEDGE
from app.models.mcp_server.constants import SEARCH_TOOL
from app.models.search.interface import SearchHitRecord, SearchOutcome
from app.services import mcp
from app.services.mcp import McpApp, McpUnavailable
from app.services.security import crypto
from app.services.utils.error import AppError
from tests import fake_voyage
from tests.fixture_repository import (
    EXPECTED_KEYWORD,
    KEYWORD_QUERY,
    LIMITER_PATH,
    SEMANTIC_QUERY,
)
from tests.knowledge_support import (
    KNOWLEDGE_URL,
    TOKEN,
    call_search,
    hits_of,
    index_fixture,
    listed_tools,
)
from tests.knowledge_support import (
    knowledge as knowledge,
)
from tests.store import reset_store, store_backed
from tests.support import recording_logger


@pytest.fixture
async def empty_store() -> None:
    await reset_store()


def a_hit(n: int, content: str) -> SearchHitRecord:
    return SearchHitRecord(
        chunk_id=f"chunk-{n}",
        source_id="source",
        url="https://github.com/octocat/Hello-World",
        ref="main",
        path=f"src/file_{n}.py",
        symbol=f"symbol_{n}",
        start_line=n,
        end_line=n + 9,
        content=content,
        score=0.5,
        semantic_rank=n,
        full_text_rank=None,
        trigram_rank=None,
        cosine=0.9,
    )


class TestDefinition:
    @pytest.mark.usefixtures("knowledge")
    async def test_offers_one_strict_tool_with_the_schema_we_wrote(self) -> None:
        tools = await listed_tools()

        assert tools == [SEARCH_TOOL]
        schema = tools[0].input_schema
        assert schema["additionalProperties"] is False
        assert schema["required"] == ["query"]

    def test_the_schema_has_no_limit_and_no_length_keyword(self) -> None:
        """`strict` refuses `minimum` and `maxLength`, and the tool takes no `limit`: the server
        bounds an answer, not the model."""
        text = json.dumps(SEARCH_TOOL.input_schema)

        for keyword in ("limit", "minimum", "maximum", "minLength", "maxLength"):
            assert keyword not in text


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes", "knowledge")
class TestOutput:
    async def test_returns_whole_hits_best_first_with_the_documented_fields_only(
        self, client: httpx.AsyncClient
    ) -> None:
        await index_fixture(client)

        result = await call_search(KEYWORD_QUERY)

        document = json.loads(result.text)
        assert set(document) == {"hits", "incomplete", "omitted"}
        assert document["incomplete"] is False
        assert document["omitted"] == 0
        hits = hits_of(result)
        assert hits[0]["path"] == LIMITER_PATH
        assert hits[0]["symbol"] == EXPECTED_KEYWORD.symbol
        assert (hits[0]["startLine"], hits[0]["endLine"]) == (
            EXPECTED_KEYWORD.start_line,
            EXPECTED_KEYWORD.end_line,
        )
        for hit in hits:
            assert set(hit) == {"url", "ref", "path", "symbol", "startLine", "endLine", "content"}

    async def test_carries_no_cosine_score_rank_or_id(self, client: httpx.AsyncClient) -> None:
        await index_fixture(client)

        result = await call_search(SEMANTIC_QUERY)

        for forbidden in ("cosine", "score", "rank", "chunkId", "sourceId"):
            assert forbidden not in result.text.replace("semantic_rank", "")
        assert len(hits_of(result)) >= 1

    async def test_no_hits_is_a_success_not_an_error(self) -> None:
        result = await call_search(SEMANTIC_QUERY)

        assert result.is_error is False
        assert json.loads(result.text) == {"hits": [], "incomplete": False, "omitted": 0}

    async def test_keeps_whole_hits_within_the_output_bound_and_counts_the_rest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hits = [a_hit(n, "x" * 1000) for n in range(1, 6)]

        async def search(*, text: str, limit: int) -> SearchOutcome:
            del text, limit
            return SearchOutcome(hits=hits, incomplete=True)

        monkeypatch.setattr(search_controller, "search_knowledge_base", search)
        monkeypatch.setattr(
            search_controller, "KNOWLEDGE", replace(KNOWLEDGE, output_max_chars=2500)
        )

        result = await call_search("anything")

        document = json.loads(result.text)
        assert len(result.text) <= 2500
        assert len(document["hits"]) == 2
        assert document["omitted"] == 3
        assert document["incomplete"] is True
        assert [hit["path"] for hit in document["hits"]] == ["src/file_1.py", "src/file_2.py"]
        assert all(len(hit["content"]) == 1000 for hit in document["hits"])

    async def test_a_first_hit_that_does_not_fit_is_omitted_whole(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def search(*, text: str, limit: int) -> SearchOutcome:
            del text, limit
            return SearchOutcome(hits=[a_hit(1, "y" * 5000)], incomplete=False)

        monkeypatch.setattr(search_controller, "search_knowledge_base", search)
        monkeypatch.setattr(
            search_controller, "KNOWLEDGE", replace(KNOWLEDGE, output_max_chars=1000)
        )

        result = await call_search("anything")

        assert json.loads(result.text) == {"hits": [], "incomplete": False, "omitted": 1}

    async def test_asks_for_the_hit_limit_and_the_trimmed_query(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked: list[tuple[str, int]] = []

        async def search(*, text: str, limit: int) -> SearchOutcome:
            asked.append((text, limit))
            return SearchOutcome(hits=[], incomplete=False)

        monkeypatch.setattr(search_controller, "search_knowledge_base", search)

        await call_search("  find the limiter \n")

        assert asked == [("find the limiter", KNOWLEDGE.hit_limit)]

    @pytest.mark.parametrize("query", ["", "   ", "a\x00b", "x" * 501])
    async def test_a_bad_query_is_invalid_query_and_embeds_nothing(self, query: str) -> None:
        result = await call_search(query)

        assert (result.is_error, result.text) == (True, "invalid_query")
        assert fake_voyage.state.requests == []

    @pytest.mark.parametrize(
        "arguments",
        [{}, {"query": 5}, {"query": None}, {"query": "ok", "limit": 3}, {"q": "ok"}],
    )
    async def test_arguments_that_are_not_exactly_a_query_string_are_invalid_query(
        self, arguments: dict[str, object]
    ) -> None:
        result = await mcp.call_tool(KNOWLEDGE_URL, "search", arguments, token=TOKEN)

        assert (result.is_error, result.text) == (True, "invalid_query")
        assert fake_voyage.state.requests == []

    async def test_a_tool_it_does_not_offer_is_an_error(self) -> None:
        result = await mcp.call_tool(KNOWLEDGE_URL, "read", {"path": "a"}, token=TOKEN)

        assert (result.is_error, result.text) == (True, "unknown_tool")

    async def test_voyage_down_is_search_unavailable(self) -> None:
        result = await call_search("anything [[fail:knowledge-down]]")

        assert (result.is_error, result.text) == (True, "search_unavailable")

    async def test_an_unexpected_failure_is_search_unavailable_without_its_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def broken(*, text: str, limit: int) -> SearchOutcome:
            del text, limit
            raise RuntimeError("secret internal detail from the database")

        monkeypatch.setattr(search_controller, "search_knowledge_base", broken)

        result = await call_search("anything")

        assert (result.is_error, result.text) == (True, "search_unavailable")
        assert "secret" not in result.text

    async def test_an_app_error_from_the_search_is_search_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def down(*, text: str, limit: int) -> SearchOutcome:
            del text, limit
            raise AppError("upstream_unavailable", "search is unavailable")

        monkeypatch.setattr(search_controller, "search_knowledge_base", down)

        result = await call_search("anything")

        assert (result.is_error, result.text) == (True, "search_unavailable")

    async def test_logs_lengths_and_counts_never_the_query(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await index_fixture(client)
        logger, sink = recording_logger()
        monkeypatch.setattr(search_controller, "log", logger)

        await call_search(KEYWORD_QUERY)

        assert sink.lines
        assert KEYWORD_QUERY not in "\n".join(sink.lines)
        assert any("queryLength" in line for line in sink.lines)


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes", "knowledge")
class TestBounds:
    async def test_past_the_concurrent_slots_a_search_waits_then_is_busy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        release = asyncio.Event()
        entered = asyncio.Event()

        async def slow(*, text: str, limit: int) -> SearchOutcome:
            del text, limit
            entered.set()
            await release.wait()
            return SearchOutcome(hits=[], incomplete=False)

        monkeypatch.setattr(search_controller, "search_knowledge_base", slow)
        monkeypatch.setattr(
            search_controller,
            "KNOWLEDGE",
            replace(KNOWLEDGE, concurrent_searches=1, slot_wait_seconds=0.2),
        )
        first = asyncio.create_task(call_search("one"))
        await entered.wait()

        refused = await call_search("two")
        release.set()
        completed = await first

        assert (refused.is_error, refused.text) == (True, "busy")
        assert completed.is_error is False

    async def test_a_search_waits_for_a_slot_and_then_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        release = asyncio.Event()
        entered = asyncio.Event()
        calls = 0

        async def slow(*, text: str, limit: int) -> SearchOutcome:
            nonlocal calls
            del text, limit
            calls += 1
            entered.set()
            await release.wait()
            return SearchOutcome(hits=[], incomplete=False)

        monkeypatch.setattr(search_controller, "search_knowledge_base", slow)
        monkeypatch.setattr(
            search_controller,
            "KNOWLEDGE",
            replace(KNOWLEDGE, concurrent_searches=1, slot_wait_seconds=5.0),
        )
        first = asyncio.create_task(call_search("one"))
        await entered.wait()
        second = asyncio.create_task(call_search("two"))
        await asyncio.sleep(0.2)
        assert calls == 1  # the second waits

        release.set()
        results = await asyncio.gather(first, second)

        assert [result.is_error for result in results] == [False, False]
        assert calls == 2

    async def test_a_failed_search_gives_its_slot_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outcomes: list[bool] = [True, False]

        async def flaky(*, text: str, limit: int) -> SearchOutcome:
            del text, limit
            if outcomes.pop(0):
                raise RuntimeError("down")
            return SearchOutcome(hits=[], incomplete=False)

        monkeypatch.setattr(search_controller, "search_knowledge_base", flaky)
        monkeypatch.setattr(
            search_controller,
            "KNOWLEDGE",
            replace(KNOWLEDGE, concurrent_searches=1, slot_wait_seconds=0.2),
        )

        failed = await call_search("one")
        recovered = await call_search("two")

        assert failed.text == "search_unavailable"
        assert recovered.is_error is False

    def test_the_slots_sit_below_the_servers_own_pool(self) -> None:
        assert KNOWLEDGE.concurrent_searches == 4
        assert KNOWLEDGE.concurrent_searches < 10
        assert KNOWLEDGE.hit_limit == 10


@pytest.mark.usefixtures("knowledge")
class TestAccess:
    """The bearer token: no token or a wrong one is a 401 that embeds nothing and reaches no
    store."""

    @pytest.fixture(autouse=True)
    def no_embedding_yet(self) -> None:
        fake_voyage.reset()

    @pytest.fixture
    async def http(self, knowledge: McpApp) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=knowledge), base_url="http://knowledge:8001"
        )

    @pytest.mark.parametrize("header", [None, "Bearer nope", "Bearer ", "Basic x", "x"])
    async def test_a_missing_or_wrong_token_is_a_401(
        self, http: httpx2.AsyncClient, header: str | None
    ) -> None:
        headers = {} if header is None else {"Authorization": header}

        res = await http.post("/mcp", json={}, headers=headers)

        assert res.status_code == 401
        assert fake_voyage.state.requests == []

    async def test_the_tools_refuse_a_caller_without_the_token(self) -> None:
        with pytest.raises(McpUnavailable):
            await call_search("anything", token=None)
        with pytest.raises(McpUnavailable):
            await call_search("anything", token="wrong-" + TOKEN)

        assert fake_voyage.state.requests == []

    async def test_compares_the_token_in_constant_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compared: list[tuple[str, str]] = []
        equals = crypto.constant_time_equals

        def spy(left: str, right: str) -> bool:
            compared.append((left, right))
            return equals(left, right)

        monkeypatch.setattr("app.services.mcp.constant_time_equals", spy)

        with pytest.raises(McpUnavailable):
            await call_search("anything", token="wrong-" + TOKEN)

        assert compared
        assert all(right == TOKEN for _, right in compared)

    async def test_health_answers_without_a_token(self, http: httpx2.AsyncClient) -> None:
        res = await http.get("/health")

        assert res.status_code == 200
        assert fake_voyage.state.requests == []

    async def test_a_host_other_than_its_own_is_refused(self, http: httpx2.AsyncClient) -> None:
        res = await http.post(
            "/mcp",
            json={},
            headers={"Authorization": f"Bearer {TOKEN}", "Host": "evil.example:8001"},
        )

        assert res.status_code == 421

    async def test_the_api_reaches_it_by_its_compose_name(self) -> None:
        mcp_host = httpx2.URL(KNOWLEDGE_URL).host
        assert mcp_host == "knowledge"
        assert len(await listed_tools()) == 1
