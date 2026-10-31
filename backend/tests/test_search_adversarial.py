"""QA's attacks on `GET /api/search`: hostile text in `q`, repeated rapid submission, an empty
knowledge base. Each runs against the fixture repository on the scripted Voyage fake."""

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

from tests.fixture_repository import KEYWORD_QUERY
from tests.source_support import member_bearer
from tests.store import reset_store, store_backed
from tests.test_search import indexed_fixture, search_wire

HOSTILE = [
    "'; drop table chunk; --",
    "check_limit' or '1'='1",
    "a & b | !c",
    "(((",
    "((((",
    "!!!",
    "!!!!",
    "%",
    "_",
    "\\",
    "\\\\%",
    "<script>alert(1)</script>",
    "x:*",
    "é" * 400,
    "\U0001f600 emoji",
    "line one\nline two",
    "‮evil",
]


@pytest.fixture
async def empty_store() -> AsyncIterator[None]:
    await reset_store()
    yield
    await reset_store()


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestHostileText:
    @pytest.mark.parametrize("q", HOSTILE)
    async def test_hostile_text_is_a_200_never_a_500(
        self, client: httpx.AsyncClient, q: str
    ) -> None:
        await indexed_fixture(client)

        res = await client.get("/api/search", params={"q": q}, headers=member_bearer())

        assert res.status_code == 200, res.text
        assert isinstance(res.json()["items"], list)

    async def test_the_table_survives_an_injection_attempt(self, client: httpx.AsyncClient) -> None:
        await indexed_fixture(client)

        await search_wire(client, "'; drop table chunk; --")

        assert await search_wire(client, KEYWORD_QUERY)

    async def test_a_query_of_only_punctuation_has_no_keyword_match(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)

        for punctuation in ("!!!", "!!!!"):
            hits = await search_wire(client, punctuation)

            assert hits
            assert all(hit["fullTextRank"] is None for hit in hits)
            # "!!!!" has no trigram at all and still goes through `<%`: it matches nothing.
            assert all(hit["trigramRank"] is None for hit in hits)


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestRepeatedSubmission:
    async def test_twenty_concurrent_identical_searches_agree(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)

        results = await asyncio.gather(*(search_wire(client, KEYWORD_QUERY) for _ in range(20)))

        first = [hit["chunkId"] for hit in results[0]]
        assert first
        assert all([hit["chunkId"] for hit in result] == first for result in results)

    async def test_an_empty_knowledge_base_answers_every_hostile_query_empty(
        self, client: httpx.AsyncClient
    ) -> None:
        for q in HOSTILE[:6]:
            res = await client.get("/api/search", params={"q": q}, headers=member_bearer())

            assert res.json() == {"items": [], "incomplete": False}
