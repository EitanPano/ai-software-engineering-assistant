"""Hybrid search: the request's rules and access, the three acceptance queries on the fixture
repository, the fusion, the `ready`-only filter, `incomplete`, and a Voyage that is down.

The ranking is proved on scripted vectors (`tests/fake_voyage.py`): this shows the fusion and the
filters work, not that the real model relates a paraphrase to its chunk (`tests/live_retrieval.py`).
"""

import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, replace

import httpx
import httpx2
import pytest
from pydantic import BaseModel, ValidationError

from app.api.search.controller import search_knowledge_base
from app.api.search.schema import SearchQuery
from app.api.source import service
from app.api.source.controller import index_source, search_ready_chunks
from app.config.constants import SEARCH
from app.models.search.interface import SearchOutcome
from app.models.source.enums import SourceStatus
from app.models.source.interface import ChunkRecord, DocumentRecord, SourceRecord
from app.services import voyage
from app.services.db import get_db
from app.services.utils import clock
from tests import fake_voyage
from tests.fixture_repository import (
    DOTTED_QUERY,
    EXPECTED_DOTTED,
    EXPECTED_KEYWORD,
    EXPECTED_LONG_LINE,
    EXPECTED_SEMANTIC,
    KEYWORD_QUERY,
    LONG_LINE_QUERY,
    OVERSIZED_SYMBOL,
    SEMANTIC_QUERY,
    ExpectedChunk,
)
from tests.limiter_source import LIMITER_SOURCE
from tests.source_support import admin_bearer, connect, member_bearer, stored_chunks
from tests.store import reset_store, store_backed
from tests.support import error_of, recording_logger

type Wire = dict[str, object]


def parsed(**fields: str) -> BaseModel:
    return SearchQuery.model_validate(fields)


def rejected(**fields: str) -> str:
    with pytest.raises(ValidationError) as failure:
        parsed(**fields)

    return str(failure.value.errors()[0]["loc"][0])


class TestValidation:
    def test_accepts_a_query_and_defaults_the_limit_to_10(self) -> None:
        query = parsed(q="check_limit")

        assert query.model_dump() == {"q": "check_limit", "limit": 10}

    def test_trims_the_query(self) -> None:
        assert parsed(q="  check_limit \n").model_dump()["q"] == "check_limit"

    def test_accepts_500_characters_and_a_limit_from_1_to_20(self) -> None:
        assert parsed(q="x" * 500, limit="20").model_dump()["limit"] == 20
        assert parsed(q="x", limit="1").model_dump()["limit"] == 1

    def test_counts_characters_not_bytes(self) -> None:
        assert parsed(q="\U0001f600" * 500).model_dump()["q"] == "\U0001f600" * 500

    @pytest.mark.parametrize("q", ["", "   ", "\t\n"])
    def test_rejects_an_empty_or_blank_query(self, q: str) -> None:
        assert rejected(q=q) == "q"

    def test_rejects_a_query_over_500_characters_after_trimming(self) -> None:
        assert rejected(q="x" * 501) == "q"
        assert parsed(q=" " + "x" * 500 + " ").model_dump()["q"] == "x" * 500

    @pytest.mark.parametrize("q", ["a\x00b", "\x00", "ab\x00"])
    def test_rejects_a_query_holding_a_nul(self, q: str) -> None:
        assert rejected(q=q) == "q"

    def test_rejects_a_missing_query(self) -> None:
        assert rejected() == "q"

    @pytest.mark.parametrize("limit", ["0", "-1", "21", "1.5", "ten", ""])
    def test_rejects_a_limit_outside_1_to_20(self, limit: str) -> None:
        assert rejected(q="x", limit=limit) == "limit"


@pytest.mark.usefixtures("fakes")
class TestValidationOverHttp:
    @pytest.mark.parametrize(
        ("query", "path"),
        [
            ("", "q"),
            ("?q=", "q"),
            ("?q=%20%20", "q"),
            ("?q=a%00b", "q"),
            (f"?q={'x' * 501}", "q"),
            ("?q=x&limit=0", "limit"),
            ("?q=x&limit=21", "limit"),
            ("?q=x&limit=ten", "limit"),
        ],
    )
    async def test_a_bad_request_is_a_400_and_voyage_is_not_called(
        self, client: httpx.AsyncClient, query: str, path: str
    ) -> None:
        res = await client.get(f"/api/search{query}", headers=member_bearer())

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"
        assert next(detail.path for detail in error_of(res).details) == path
        assert res.json()["requestId"]
        assert fake_voyage.state.requests == []


@pytest.fixture
async def empty_store() -> AsyncIterator[None]:
    await reset_store()
    yield
    await reset_store()


@pytest.mark.usefixtures("fakes")
class TestAccess:
    async def test_no_token_is_a_401(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/search?q=check_limit")

        assert res.status_code == 401
        assert error_of(res).code == "unauthenticated"
        assert res.json()["requestId"]
        assert fake_voyage.state.requests == []

    async def test_a_bad_request_without_a_token_is_still_a_401(
        self, client: httpx.AsyncClient
    ) -> None:
        res = await client.get("/api/search?q=")

        assert res.status_code == 401

    async def test_both_roles_are_let_through_the_gate(self, client: httpx.AsyncClient) -> None:
        """A malformed query reaches validation, so the gate let the caller in without a role."""
        for headers in (member_bearer(), admin_bearer()):
            res = await client.get("/api/search?q=", headers=headers)

            assert res.status_code == 400

    @store_backed
    @pytest.mark.usefixtures("empty_store")
    async def test_both_roles_get_a_200(self, client: httpx.AsyncClient) -> None:
        for headers in (member_bearer(), admin_bearer()):
            res = await client.get("/api/search?q=check_limit", headers=headers)

            assert res.status_code == 200, res.text
            assert res.json() == {"items": [], "incomplete": False}
        assert [body["input_type"] for body in fake_voyage.state.requests] == ["query"] * 2


async def indexed_fixture(client: httpx.AsyncClient) -> str:
    res = await connect(client, admin_bearer())
    assert res.status_code == 201, res.text
    source_id = str(res.json()["id"])
    await index_source(source_id)
    # Every chunk is a candidate of the semantic search, so a chunk scripted to be last in it has
    # a rank and not a cut-off.
    assert len(await stored_chunks(source_id)) <= SEARCH.candidates
    return source_id


async def search_wire(client: httpx.AsyncClient, q: str, limit: int = 10) -> list[Wire]:
    res = await client.get("/api/search", params={"q": q, "limit": limit}, headers=member_bearer())
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert isinstance(items, list)
    return items


def rank(hit: Wire, name: str) -> int | None:
    value = hit[name]
    assert value is None or isinstance(value, int)
    return value


def number(hit: Wire, name: str) -> int:
    value = rank(hit, name)
    assert value is not None, name
    return value


def top_five_is(hits: list[Wire], expected: ExpectedChunk) -> Wire:
    """The hit for `expected` in the top 5, found by its path, symbol and lines."""
    found = [
        (position, hit)
        for position, hit in enumerate(hits[:5])
        if (hit["path"], hit["symbol"], hit["startLine"], hit["endLine"])
        == (expected.path, expected.symbol, expected.start_line, expected.end_line)
    ]
    assert len(found) == 1, [(h["path"], h["symbol"], h["startLine"], h["endLine"]) for h in hits]
    return found[0][1]


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestAc03:
    async def test_finds_an_exact_identifier_only_keyword_search_matches(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)

        hit = top_five_is(await search_wire(client, KEYWORD_QUERY), EXPECTED_KEYWORD)

        assert rank(hit, "fullTextRank") is not None
        assert rank(hit, "trigramRank") is not None
        assert number(hit, "semanticRank") > 5

    async def test_finds_a_dotted_call_only_trigram_search_matches(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)

        hit = top_five_is(await search_wire(client, DOTTED_QUERY), EXPECTED_DOTTED)

        assert rank(hit, "fullTextRank") is None
        assert rank(hit, "trigramRank") is not None
        assert number(hit, "semanticRank") > 5

    async def test_finds_a_paraphrase_only_semantic_search_matches(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)

        hits = await search_wire(client, SEMANTIC_QUERY)

        hit = top_five_is(hits, EXPECTED_SEMANTIC)
        assert len(str(hit["content"])) > 4000
        assert rank(hit, "fullTextRank") is None
        assert rank(hit, "trigramRank") is None
        assert rank(hit, "semanticRank") == 1

    async def test_finds_the_piece_of_a_line_over_the_bound(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)

        hit = top_five_is(await search_wire(client, LONG_LINE_QUERY), EXPECTED_LONG_LINE)

        assert len(str(hit["content"])) == 6000
        assert str(hit["content"]).startswith(LONG_LINE_QUERY)

    async def test_a_hit_carries_its_source_and_file(self, client: httpx.AsyncClient) -> None:
        source_id = await indexed_fixture(client)

        hit = top_five_is(await search_wire(client, KEYWORD_QUERY), EXPECTED_KEYWORD)

        assert hit["sourceId"] == source_id
        assert hit["url"] == "https://github.com/octocat/Hello-World"
        assert hit["ref"] == "main"
        assert hit["chunkId"]
        assert set(hit) == {
            "chunkId", "sourceId", "url", "ref", "path", "symbol", "startLine", "endLine",
            "content", "score", "semanticRank", "fullTextRank", "trigramRank",
        }  # fmt: skip

    async def test_a_symbol_over_the_bound_is_cut_into_windows_that_keep_its_name(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)

        hits = await search_wire(client, "tier_050", limit=20)

        windows = [hit for hit in hits if hit["symbol"] == OVERSIZED_SYMBOL]
        assert windows
        assert all(len(str(hit["content"])) <= 6000 for hit in windows)


class TestFixtureShape:
    """The limiter is sized as a real file, and each query's words are where the plan says."""

    def test_is_about_500_lines_with_the_dotted_call_past_line_300(self) -> None:
        lines = LIMITER_SOURCE.split("\n")

        assert 500 <= len(lines) <= 700, len(lines)
        assert EXPECTED_DOTTED.start_line > 300
        assert EXPECTED_DOTTED.start_line <= next(
            n for n, line in enumerate(lines, 1) if f"limiter.{DOTTED_QUERY}(key)" in line
        )

    def test_has_a_symbol_over_4000_characters_and_one_over_the_bound(self) -> None:
        lines = LIMITER_SOURCE.split("\n")

        def size(chunk: ExpectedChunk) -> int:
            return len("\n".join(lines[chunk.start_line - 1 : chunk.end_line]))

        assert 4000 < size(EXPECTED_SEMANTIC) <= 6000
        oversized = next(n for n, line in enumerate(lines) if OVERSIZED_SYMBOL in line)
        assert sum(len(line) + 1 for line in lines[oversized : oversized + 112]) > 6000
        assert max(len(line) for line in lines) > 6000

    def test_the_dotted_identifier_and_the_paraphrase_words_are_in_one_place_or_none(self) -> None:
        assert LIMITER_SOURCE.count(DOTTED_QUERY) == 1
        assert LIMITER_SOURCE.count("defer") == 1
        assert LIMITER_SOURCE.count("penalty") == 1

    def test_the_paraphrase_shares_no_word_with_the_file(self) -> None:
        text = LIMITER_SOURCE.lower()

        assert [word for word in SEMANTIC_QUERY.split() if word in text] == []


def blank_vector(seed: str, towards: Sequence[float] = (), weight: float = 0.0) -> list[float]:
    """A unit-ish vector from a seed, pulled towards `towards` by `weight` when one is given."""
    base = fake_voyage.vector_of(seed)
    if not towards:
        return base
    return [(1 - weight) * b + weight * t for b, t in zip(base, towards, strict=True)]


@dataclass(frozen=True)
class Seed:
    content: str
    embedding: list[float]
    id: str = ""


async def add_source(
    status: SourceStatus, name: str, chunks: Sequence[Seed]
) -> tuple[str, list[str]]:
    """A source in `status` with one document and these chunks, stored directly."""
    now = clock.now()
    source = await service.insert_source(
        SourceRecord(
            id=str(uuid.uuid4()),
            url=f"https://github.com/octocat/{name}",
            ref="main",
            status=status,
            error_code=None,
            indexed_commit="0" * 40,
            document_count=1,
            chunk_count=len(chunks),
            created_at=now,
            updated_at=now,
        )
    )
    document = DocumentRecord(
        id=str(uuid.uuid4()), source_id=source.id, path=f"{name}.py", language=None, created_at=now
    )
    await service.insert_documents([document])
    records = [
        ChunkRecord(
            id=seed.id or str(uuid.uuid4()),
            document_id=document.id,
            symbol=None,
            start_line=1,
            end_line=1,
            content=seed.content,
            created_at=now,
        )
        for seed in chunks
    ]
    await service.insert_chunks(records, [seed.embedding for seed in chunks])
    return source.id, [record.id for record in records]


def far(n: int) -> list[Seed]:
    return [Seed(f"unrelated text number {i}", blank_vector(f"far-{i}")) for i in range(n)]


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestFusion:
    async def test_score_is_the_rrf_sum_and_hits_are_ordered_by_it(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)

        hits = await search_wire(client, KEYWORD_QUERY, limit=20)

        assert len(hits) == 20
        for hit in hits:
            ranks = [rank(hit, name) for name in ("semanticRank", "fullTextRank", "trigramRank")]
            expected = sum(1 / (SEARCH.rrf_k + r) for r in ranks if r is not None)
            assert hit["score"] == pytest.approx(expected, rel=1e-9)
        scores = [(-float(str(h["score"])), str(h["chunkId"])) for h in hits]
        assert scores == sorted(scores)

    async def test_a_chunk_two_searches_return_beats_one_that_one_search_returns(self) -> None:
        text = "alpha beta"
        vector = fake_voyage.vector_of(text)
        _, ids = await add_source(
            SourceStatus.ready,
            "two",
            [
                Seed("nothing in common", vector),  # nearest, matches no word
                Seed("alpha beta gamma", blank_vector("elsewhere")),  # a word match, far away
                *far(3),
            ],
        )
        outcome = await run_search(text)

        by_id = {hit.chunk_id: hit for hit in outcome.hits}
        assert by_id[ids[0]].full_text_rank is None
        assert by_id[ids[1]].full_text_rank == 1
        assert [hit.chunk_id for hit in outcome.hits][:2] == [ids[1], ids[0]]
        assert by_id[ids[1]].score > by_id[ids[0]].score

    async def test_equal_scores_order_by_chunk_id(self) -> None:
        text = "alpha beta"
        vector = fake_voyage.vector_of(text)
        near = blank_vector("neighbour", vector, 0.7)
        # `a` is the first full-text match (equal ranks break on the id) and the second nearest,
        # `b` the second match and the nearest: 1/61 + 1/62 for both.
        _, ids = await add_source(
            SourceStatus.ready,
            "tie",
            [
                Seed("alpha beta", near, id="a-chunk"),
                Seed("alpha beta", vector, id="b-chunk"),
                *far(4),
            ],
        )

        outcome = await run_search(text)

        assert ids[:2] == ["a-chunk", "b-chunk"]
        first, second = outcome.hits[:2]
        assert (first.chunk_id, second.chunk_id) == ("a-chunk", "b-chunk")
        assert (first.semantic_rank, first.full_text_rank) == (2, 1)
        assert (second.semantic_rank, second.full_text_rank) == (1, 2)
        assert first.score == second.score

    async def test_limit_is_honoured(self, client: httpx.AsyncClient) -> None:
        await indexed_fixture(client)

        for limit in (1, 3, 20):
            assert len(await search_wire(client, "window limit", limit=limit)) == limit

    async def test_a_sentence_runs_no_trigram_search(self, client: httpx.AsyncClient) -> None:
        await indexed_fixture(client)

        hits = await search_wire(client, "sliding_window_remaining check", limit=20)

        assert hits
        assert {rank(hit, "trigramRank") for hit in hits} == {None}

    async def test_a_word_over_100_characters_runs_no_trigram_search(self) -> None:
        for length, expect_trigram in ((100, True), (101, False)):
            word = "w" * length
            vector = fake_voyage.vector_of(word)
            await add_source(
                SourceStatus.ready, f"long{length}", [Seed(f"x {word} y", vector), *far(2)]
            )

            outcome = await run_search(word)

            hit = outcome.hits[0]
            assert hit.full_text_rank == 1
            assert (hit.trigram_rank is not None) is expect_trigram, length
            await reset_store()

    async def test_a_three_letter_method_in_a_dotted_call_is_a_trigram_match_full_text_misses(
        self,
    ) -> None:
        """`self.get(key)` is the lexemes `self.get` and `key`: full-text search cannot find `get`,
        so the trigram search is the only one that does."""
        vector = fake_voyage.vector_of("get")
        _, ids = await add_source(
            SourceStatus.ready, "dotted", [Seed("value = self.get(key)", vector), *far(3)]
        )

        outcome = await run_search("get")

        hit = next(hit for hit in outcome.hits if hit.chunk_id == ids[0])
        assert hit.full_text_rank is None
        assert hit.trigram_rank == 1

    async def test_a_two_letter_word_runs_no_trigram_search(self) -> None:
        """It has no trigram of its own, only padded ones, so half the chunks of real code would be
        candidates; full-text search finds it, except inside a dotted call."""
        for length, expect_trigram in ((2, False), (3, True)):
            word = "z" * length
            vector = fake_voyage.vector_of(word)
            await add_source(
                SourceStatus.ready, f"short{length}", [Seed(f"x {word} y", vector), *far(2)]
            )

            outcome = await run_search(word)

            hit = outcome.hits[0]
            assert hit.full_text_rank == 1
            assert (hit.trigram_rank is not None) is expect_trigram, length
            await reset_store()

    async def test_text_under_the_0_9_threshold_is_no_trigram_match(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)

        hits = await search_wire(client, "slidng_window_remaning", limit=20)

        assert {rank(hit, "trigramRank") for hit in hits} == {None}
        assert {rank(hit, "fullTextRank") for hit in hits} == {None}


async def run_search(text: str) -> SearchOutcome:
    """The rule. The fake embeds `text` as `vector_of(text)`, so a test that stores that vector
    for a chunk gets it back as the chunk nearest to the query."""
    return await search_knowledge_base(text=text, limit=20)


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestReadyOnly:
    async def test_in_flight_chunks_nearer_than_every_ready_one_hide_nothing(self) -> None:
        text = "nearest first"
        vector = fake_voyage.vector_of(text)
        _, ready = await add_source(SourceStatus.ready, "ready", far(8))
        indexing = [Seed(f"in flight {n}", blank_vector(f"n{n}", vector, 0.8)) for n in range(60)]
        _, in_flight = await add_source(SourceStatus.indexing, "busy", indexing)

        async def work(db: service.Tx) -> tuple[list[str], list[str]]:
            await db.execute("set local enable_seqscan = off")
            await db.execute("set local enable_sort = off")
            await service.prepare_search(db=db)
            hits, _ = await service.search_chunks(
                embedding=vector, text=text, trigram_token=None, limit=20, db=db
            )
            plan = await explain(db, vector, text)
            return [hit.chunk_id for hit in hits], plan

        found, plan = await service.with_transaction(work)

        assert any("chunk_embedding_idx" in line for line in plan), plan
        assert sorted(found) == sorted(ready)
        assert not set(found) & set(in_flight)

    async def test_the_rule_returns_exactly_the_ready_chunks_and_is_complete(self) -> None:
        text = "nearest first"
        vector = fake_voyage.vector_of(text)
        _, ready = await add_source(SourceStatus.ready, "ready", far(8))
        await add_source(
            SourceStatus.indexing,
            "busy",
            [Seed(f"in flight {n}", blank_vector(f"n{n}", vector, 0.8)) for n in range(60)],
        )

        outcome = await run_search(text)

        assert sorted(hit.chunk_id for hit in outcome.hits) == sorted(ready)
        assert outcome.incomplete is False

    @pytest.mark.parametrize("status", [SourceStatus.queued, SourceStatus.failed])
    async def test_a_queued_or_failed_source_contributes_to_no_search(
        self, status: SourceStatus
    ) -> None:
        text = "alpha beta"
        vector = fake_voyage.vector_of(text)
        _, ready = await add_source(SourceStatus.ready, "ready", [Seed("alpha beta", vector)])
        await add_source(
            status, "other", [Seed("alpha beta", vector), Seed("alpha beta again", vector)]
        )

        outcome = await run_search(text)

        assert [hit.chunk_id for hit in outcome.hits] == ready

    async def test_a_source_not_ready_yet_is_searched_by_no_keyword_search(self) -> None:
        await add_source(
            SourceStatus.indexing, "busy", [Seed("sliding_window_remaining", [1.0] * 1024)]
        )

        outcome = await run_search("sliding_window_remaining")

        assert outcome.hits == []

    async def test_nothing_ready_is_an_empty_complete_result(
        self, client: httpx.AsyncClient
    ) -> None:
        res = await client.get("/api/search?q=anything", headers=member_bearer())

        assert res.status_code == 200
        assert res.json() == {"items": [], "incomplete": False}


async def explain(db: service.Tx, vector: Sequence[float], text: str) -> list[str]:
    """The plan of the search statement, one line per row."""
    literal = "[" + ",".join(format(x, ".8g") for x in vector) + "]"
    cursor = await db.execute(
        "explain " + service.SEARCH_STATEMENT,
        (
            literal, literal, SEARCH.candidates, text, text, SEARCH.keyword_candidates,
            SEARCH.candidates, None, None, SEARCH.keyword_candidates, SEARCH.candidates,
            SEARCH.rrf_k, SEARCH.rrf_k, SEARCH.rrf_k, 20,
        ),
    )  # fmt: skip
    return [str(row[0]) for row in await cursor.fetchall()]


@pytest.fixture
def small_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """A scan that stops after 20 tuples and a keyword search that caps at 3 matches."""
    small = replace(SEARCH, max_scan_tuples=20, keyword_candidates=3)
    monkeypatch.setattr("app.api.source.service.SEARCH", small)
    monkeypatch.setattr("app.api.source.controller.SEARCH", small)

    # A table this small is read by a sequential scan, which has no scan limit to stop at: the
    # planner is told to use the index, as in `TestReadyOnly`, and nothing else is changed.
    prepare = service.prepare_search

    async def with_index(*, db: service.Tx) -> None:
        await prepare(db=db)
        await db.execute("set local enable_seqscan = off")
        await db.execute("set local enable_sort = off")

    monkeypatch.setattr("app.api.source.service.prepare_search", with_index)


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestIncomplete:
    async def test_a_scan_cut_short_is_reported_and_logged(
        self, small_limits: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del small_limits
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.source.controller.log", logger)
        text = "nearest first"
        vector = fake_voyage.vector_of(text)
        await add_source(SourceStatus.ready, "ready", far(8))
        await add_source(
            SourceStatus.indexing,
            "busy",
            # 300 nearer than every ready chunk, as in the plan's probe: the scan stops at its 20
            # tuples among them and the 8 ready chunks are never reached (the default scan, with
            # no `strict_order`, returned none of them either).
            [Seed(f"in flight {n}", blank_vector(f"n{n}", vector, 0.8)) for n in range(300)],
        )

        outcome = await run_search(text)

        assert outcome.incomplete is True
        assert len(outcome.hits) < 8
        (line,) = [line for line in sink.lines if "search incomplete" in line]
        assert "readyChunks=8" in line
        assert text not in line

    async def test_a_keyword_search_at_its_cap_is_reported_and_logged(
        self, small_limits: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del small_limits
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.source.controller.log", logger)
        await add_source(
            SourceStatus.ready,
            "many",
            [Seed(f"common word {n}", blank_vector(f"m{n}")) for n in range(5)],
        )

        outcome = await run_search("common")

        assert outcome.incomplete is True
        assert len(outcome.hits) == 5  # the semantic search still returns them all
        assert sum("search incomplete" in line for line in sink.lines) == 1

    async def test_a_whole_result_is_not_incomplete_and_logs_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.source.controller.log", logger)
        await add_source(
            SourceStatus.ready,
            "few",
            [Seed(f"common word {n}", blank_vector(f"m{n}")) for n in range(5)],
        )

        outcome = await run_search("common")

        assert outcome.incomplete is False
        assert len(outcome.hits) == 5
        assert not any("search incomplete" in line for line in sink.lines)

    async def test_the_rule_for_other_modules_reports_the_same(self) -> None:
        await add_source(SourceStatus.ready, "few", far(3))

        outcome = await search_ready_chunks(
            embedding=fake_voyage.vector_of("x"), text="x", trigram_token=None, limit=5
        )

        assert (len(outcome.hits), outcome.incomplete) == (3, False)


def use_handler(handler: Callable[[httpx2.Request], httpx2.Response]) -> httpx2.AsyncClient:
    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler), base_url="http://fake-voyage"
    )
    voyage.use_client(client)
    return client


@pytest.mark.usefixtures("fakes")
class TestVoyageDown:
    """The search is a 503, never a silently keyword-only answer; no vendor or query text leaves."""

    @pytest.mark.parametrize("status", [429, 500, 503])
    async def test_voyage_failing_or_limiting_is_a_503(
        self, client: httpx.AsyncClient, status: int
    ) -> None:
        calls: list[int] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            calls.append(1)
            return httpx2.Response(status, headers={"retry-after": "30"}, json={"detail": "x"})

        voyage_client = use_handler(handler)

        res = await client.get("/api/search?q=secret-words-here", headers=member_bearer())

        assert res.status_code == 503
        assert error_of(res).code == "upstream_unavailable"
        assert res.json()["requestId"]
        assert len(calls) == SEARCH.embed_attempts
        assert "secret-words-here" not in res.text
        assert "voyage" not in res.text.lower()
        await voyage_client.aclose()

    async def test_an_unreachable_voyage_is_a_503(self, client: httpx.AsyncClient) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("no route", request=request)

        voyage_client = use_handler(handler)

        res = await client.get("/api/search?q=anything", headers=member_bearer())

        assert res.status_code == 503
        assert error_of(res).code == "upstream_unavailable"
        await voyage_client.aclose()

    async def test_the_log_carries_no_query_text(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger, sink = recording_logger()
        for module in (
            "app.api.search.controller",
            "app.services.voyage",
            "app.middleware.error_handler",
        ):
            monkeypatch.setattr(f"{module}.log", logger)
        voyage_client = use_handler(lambda request: httpx2.Response(503))

        await client.get("/api/search?q=secret-words-here", headers=member_bearer())

        assert sink.lines
        assert not any("secret-words-here" in line for line in sink.lines)
        await voyage_client.aclose()


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestStatementLimit:
    """A search holds a pooled connection, so the database bounds it: past `statement_timeout_ms`
    the answer is a 503, never a connection held for seconds."""

    async def test_a_search_past_its_statement_limit_is_a_503_with_no_query_text(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger, sink = recording_logger()
        for module in ("app.api.source.controller", "app.middleware.error_handler"):
            monkeypatch.setattr(f"{module}.log", logger)
        monkeypatch.setattr(
            "app.api.source.service.SEARCH", replace(SEARCH, statement_timeout_ms=1)
        )
        await add_source(
            SourceStatus.ready,
            "many",
            [Seed(f"common word {n}", blank_vector(f"s{n}")) for n in range(400)],
        )

        res = await client.get("/api/search?q=secret-words-here", headers=member_bearer())

        assert res.status_code == 503, res.text
        assert error_of(res).code == "upstream_unavailable"
        assert res.json()["requestId"]
        assert "secret-words-here" not in res.text
        assert not any("secret-words-here" in line for line in sink.lines)

    async def test_the_limit_is_set_for_the_transaction_only(self) -> None:
        """On one connection: two `with_transaction` calls may take two pooled connections, and
        the second would then read `0` whatever the first did (a `set_config(..., false)` leak
        would pass)."""

        async def read(connection: service.Tx) -> str:
            cursor = await connection.execute("show statement_timeout")
            row = await cursor.fetchone()
            assert row is not None
            return str(row[0])

        async with get_db() as connection:
            async with connection.transaction():
                await service.prepare_search(db=connection)
                assert await read(connection) == "3s"
            assert await read(connection) == "0"

    async def test_an_ordinary_search_finishes_inside_the_limit(
        self, client: httpx.AsyncClient
    ) -> None:
        await add_source(SourceStatus.ready, "few", far(5))

        res = await client.get("/api/search?q=anything", headers=member_bearer())

        assert res.status_code == 200
