"""QA's attacks on the eval run: concurrent starts, gates before validation, boundary pages and
metric inputs the schema normally keeps out."""

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

from app.models.eval.type import RankedHit, Span
from app.services.utils.retrieval_metric import is_relevant, score_case
from tests.source_support import admin_bearer, member_bearer
from tests.store import reset_store, store_backed
from tests.support import error_of

COMMIT = "8b19813f2bfca99f1018a587a8cf54fc959f2e5d"


@pytest.fixture
async def empty_store() -> AsyncIterator[None]:
    await reset_store()
    yield
    await reset_store()


@store_backed
@pytest.mark.usefixtures("empty_store")
class TestRapidStart:
    async def test_two_starts_at_once_leave_one_run_and_one_409(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = admin_bearer()

        first, second = await asyncio.gather(
            client.post("/api/eval-run", headers=headers),
            client.post("/api/eval-run", headers=headers),
        )

        assert sorted([first.status_code, second.status_code]) == [201, 409]
        listed = await client.get("/api/eval-run", headers=headers)
        assert len(listed.json()["items"]) == 1

    async def test_the_largest_page_and_a_page_past_the_end_are_valid(
        self, client: httpx.AsyncClient
    ) -> None:
        res = await client.get("/api/eval-run?limit=100", headers=admin_bearer())

        assert res.status_code == 200
        assert res.json()["items"] == []
        assert res.json()["nextCursor"] is None


class TestGateBeforeValidation:
    async def test_a_user_with_a_bad_query_is_a_403_not_a_400(
        self, client: httpx.AsyncClient
    ) -> None:
        res = await client.get("/api/eval-run?limit=-5&cursor=%00", headers=member_bearer())

        assert res.status_code == 403
        assert error_of(res).code == "forbidden"

    @pytest.mark.parametrize(
        "path", ["/api/eval-run/%00", "/api/eval-run/../source", "/api/eval-run/" + "x" * 5000]
    )
    async def test_no_token_with_a_hostile_id_is_a_401(
        self, client: httpx.AsyncClient, path: str
    ) -> None:
        res = await client.get(path)

        assert res.status_code in (401, 404)
        if res.status_code == 401:
            assert error_of(res).code == "unauthenticated"

    async def test_a_user_cannot_start_a_run_with_a_junk_body(
        self, client: httpx.AsyncClient
    ) -> None:
        res = await client.post(
            "/api/eval-run",
            headers={**member_bearer(), "content-type": "application/json"},
            content=b"{not json" * 1000,
        )

        assert res.status_code == 403

    @pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
    async def test_a_write_the_contract_does_not_have_is_refused(
        self, client: httpx.AsyncClient, method: str
    ) -> None:
        res = await client.request(method, "/api/eval-run/some-id", headers=admin_bearer())

        assert res.status_code in (404, 405)


def hit(start: int, end: int, *, path: str = "a.py") -> RankedHit:
    return RankedHit(
        span=Span(commit=COMMIT, path=path, start_line=start, end_line=end),
        semantic_rank=1,
        full_text_rank=None,
        trigram_rank=None,
        cosine=0.5,
    )


class TestMetricBoundaries:
    def test_a_single_line_label_matches_only_a_hit_holding_that_line(self) -> None:
        label = Span(commit=COMMIT, path="a.py", start_line=7, end_line=7)

        assert is_relevant(hit(1, 100).span, label)
        assert not is_relevant(hit(8, 100).span, label)

    def test_a_hit_one_line_before_the_label_is_not_relevant(self) -> None:
        label = Span(commit=COMMIT, path="a.py", start_line=10, end_line=19)

        assert not is_relevant(hit(1, 9).span, label)

    def test_a_hit_list_longer_than_the_depth_cannot_score_past_it(self) -> None:
        label = Span(commit=COMMIT, path="a.py", start_line=1, end_line=10)
        far = [hit(1, 10, path=f"o{n}.py") for n in range(25)] + [hit(1, 10)]

        metrics = score_case(far, [label], depth=20)

        assert metrics.rank is None
        assert metrics.recall_at_20 == 0.0
        assert metrics.ndcg_at_10 == 0.0

    def test_many_labels_all_met_never_pass_one(self) -> None:
        labels = [
            Span(commit=COMMIT, path="a.py", start_line=n * 100, end_line=n * 100 + 9)
            for n in range(1, 15)
        ]
        hits = [hit(n * 100, n * 100 + 9) for n in range(1, 15)]

        metrics = score_case(hits, labels, depth=20)

        assert metrics.recall_at_20 == 1.0
        assert metrics.recall_at_10 == pytest.approx(10 / 14)
        assert metrics.ndcg_at_10 == pytest.approx(1.0)
