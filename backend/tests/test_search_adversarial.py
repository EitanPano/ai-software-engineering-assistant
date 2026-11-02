"""QA's attacks on `GET /api/search`: hostile text in `q`, repeated rapid submission, an empty
knowledge base, and the per-user limit (a burst, a forged token, a varied request, an alias path).
Each runs against the fixture repository on the scripted Voyage fake."""

import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import httpx2
import pytest

from app.config.constants import RATE_LIMITS, SEARCH
from app.models.search.interface import SearchOutcome
from tests import fake_voyage
from tests.agent_support import bearer
from tests.fixture_repository import KEYWORD_QUERY
from tests.source_support import member_bearer
from tests.store import reset_store, store_backed
from tests.support import error_of
from tests.test_search import indexed_fixture, search_wire, use_handler

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


LIMIT = RATE_LIMITS.search_per_user.limit
BLANK = {"q": ""}  # a 400 that touches neither Voyage nor the database, and still counts


async def blank_search(client: httpx.AsyncClient, headers: dict[str, str]) -> httpx.Response:
    return await client.get("/api/search", params=BLANK, headers=headers)


@pytest.mark.usefixtures("fakes")
class TestSearchLimitAttacks:
    """The per-user limit under attack. None of these needs the database: a refused search, a 400
    and a Voyage failure all end before a pooled connection."""

    async def test_an_upstream_failure_counts_and_the_next_search_is_refused_before_voyage(
        self, client: httpx.AsyncClient
    ) -> None:
        calls: list[int] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            calls.append(1)
            return httpx2.Response(503, json={"detail": "x"})

        voyage_client = use_handler(handler)
        headers = member_bearer()
        for _ in range(LIMIT):
            res = await client.get("/api/search", params={"q": "retry me"}, headers=headers)
            assert res.status_code == 503
        attempts = len(calls)
        assert attempts == LIMIT * SEARCH.embed_attempts

        refused = await client.get("/api/search", params={"q": "retry me"}, headers=headers)

        assert refused.status_code == 429
        assert error_of(refused).code == "rate_limited"
        assert len(calls) == attempts  # the refused search paid Voyage nothing
        await voyage_client.aclose()

    async def test_a_forged_token_cannot_spend_another_users_searches(
        self, client: httpx.AsyncClient
    ) -> None:
        victim = str(uuid.uuid4())
        header, payload, signature = bearer(victim)["Authorization"].split(" ")[1].split(".")
        middle = len(signature) // 2
        flipped = "A" if signature[middle] != "A" else "B"
        tampered = f"{signature[:middle]}{flipped}{signature[middle + 1 :]}"
        forged = {"Authorization": f"Bearer {header}.{payload}.{tampered}"}

        for _ in range(LIMIT * 3):
            res = await blank_search(client, forged)
            assert res.status_code == 401
            assert error_of(res).code == "unauthenticated"

        # The victim still has the whole window: LIMIT attempts get through, the next is refused.
        for _ in range(LIMIT):
            assert (await blank_search(client, bearer(victim))).status_code == 400
        assert (await blank_search(client, bearer(victim))).status_code == 429

    async def test_varying_the_request_does_not_dodge_the_limit(
        self, client: httpx.AsyncClient
    ) -> None:
        caller = str(uuid.uuid4())
        for n in range(LIMIT):
            res = await client.get(
                "/api/search",
                params={"q": "  ", "limit": str(n)},
                headers={
                    **bearer(caller),  # a new session each time, the same user
                    "X-Forwarded-For": f"203.0.113.{n}",
                    "User-Agent": f"agent-{n}",
                },
            )
            assert res.status_code == 400

        for params in (
            {"q": "check_limit"},
            {"q": "CHECK_LIMIT ", "limit": "1"},
            {"q": "another text", "limit": "20", "utm": "x"},
        ):
            res = await client.get(
                "/api/search",
                params=params,
                headers={**bearer(caller), "X-Forwarded-For": "198.51.100.9"},
            )

            assert res.status_code == 429
            assert error_of(res).code == "rate_limited"
        assert fake_voyage.state.requests == []

    async def test_a_refused_search_never_reaches_the_index(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reached: list[str] = []

        async def index(**fields: object) -> SearchOutcome:
            reached.append(str(fields["text"]))
            return SearchOutcome(hits=[], incomplete=False)

        monkeypatch.setattr("app.api.search.controller.search_ready_chunks", index)
        headers = member_bearer()

        statuses = [
            (
                await client.get("/api/search", params={"q": f"text {n}"}, headers=headers)
            ).status_code
            for n in range(LIMIT + 4)
        ]

        assert statuses == [200] * LIMIT + [429] * 4
        assert len(reached) == LIMIT
        assert len(fake_voyage.state.requests) == LIMIT

    @pytest.mark.parametrize("path", ["/api/search/", "//api/search", "/api/search;x=1"])
    async def test_an_alias_of_the_path_does_not_dodge_the_limit(
        self, client: httpx.AsyncClient, path: str
    ) -> None:
        headers = member_bearer()
        for _ in range(LIMIT):
            assert (await blank_search(client, headers)).status_code == 400

        res = await client.get(path, params={"q": "check_limit"}, headers=headers)

        assert res.status_code in {307, 308, 404, 405, 429}
        assert fake_voyage.state.requests == []

    async def test_the_search_limit_and_the_send_limit_are_separate_buckets(
        self, client: httpx.AsyncClient
    ) -> None:
        caller = str(uuid.uuid4())
        send = f"/api/conversation/{uuid.uuid4()}/message"
        for _ in range(LIMIT):
            assert (await blank_search(client, bearer(caller))).status_code == 400
        assert (await blank_search(client, bearer(caller))).status_code == 429

        # Out of searches, still inside the send limit: an invalid body is a 400, not a 429.
        assert (await client.post(send, headers=bearer(caller), json={})).status_code == 400

        other = str(uuid.uuid4())
        for _ in range(RATE_LIMITS.message_per_user.limit):
            assert (await client.post(send, headers=bearer(other), json={})).status_code == 400
        assert (await client.post(send, headers=bearer(other), json={})).status_code == 429
        # Out of sends, still inside the search limit.
        assert (await blank_search(client, bearer(other))).status_code == 400


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestSearchLimitBurst:
    async def test_a_burst_of_concurrent_searches_lets_exactly_the_limit_through(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = member_bearer()
        burst = 4 * LIMIT

        results = await asyncio.gather(
            *(
                client.get("/api/search", params={"q": f"burst {n}"}, headers=headers)
                for n in range(burst)
            )
        )

        statuses = sorted(res.status_code for res in results)
        assert statuses == [200] * LIMIT + [429] * (burst - LIMIT)
        assert len(fake_voyage.state.requests) == LIMIT
        assert all(
            error_of(res).code == "rate_limited" for res in results if res.status_code == 429
        )
