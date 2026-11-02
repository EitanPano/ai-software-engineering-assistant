import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.api.eval import service
from app.api.eval.controller import execute_eval_run, fail_lost_eval_runs, replace_eval_cases
from app.api.eval.schema import EvalCaseFile
from app.api.search.controller import search_knowledge_base
from app.api.source.controller import index_source
from app.config.constants import EVAL, RATE_LIMITS, SEARCH
from app.infra.pubsub import pubsub
from app.infra.scripts.seed_eval_case import seed
from app.models.search.interface import SearchOutcome
from app.services.db import fetch_one
from app.services.event import drain
from app.services.utils import clock
from app.services.utils.error import AppError
from tests import fake_voyage
from tests.eval_support import (
    NO_ANSWER_QUESTION,
    fixture_case_file,
    fixture_cases,
    fixture_file,
    generated_cases,
)
from tests.fixture_repository import (
    DOTTED_QUERY,
    FIXTURE_COMMIT,
    KEYWORD_QUERY,
    SEMANTIC_QUERY,
)
from tests.source_support import admin_bearer, connect, member_bearer, stored_chunks
from tests.store import reset_store, store_backed
from tests.support import error_of

type Json = dict[str, object]

COMMIT = "8b19813f2bfca99f1018a587a8cf54fc959f2e5d"
CHUNK = {"path": "src/click/core.py", "startLine": 10, "endLine": 40}


def case(**overrides: object) -> dict[str, object]:
    return {
        "kind": "identifier",
        "question": "where is Context.invoke defined",
        "expectedChunks": [CHUNK],
        **overrides,
    }


def case_file(*cases: Mapping[str, object], commit: str = COMMIT) -> dict[str, object]:
    return {"pinnedCommit": commit, "cases": list(cases or [case()])}


def rejected(body: Mapping[str, object], *path: str | int) -> None:
    with pytest.raises(ValidationError) as failure:
        EvalCaseFile.model_validate(body)

    assert failure.value.errors()[0]["loc"][: len(path)] == path


class TestCaseFile:
    """The request rules of the seed command's file (`api/eval/schema.py`, plan step 9)."""

    def test_accepts_one_case_of_each_kind(self) -> None:
        parsed = EvalCaseFile.model_validate(
            case_file(
                case(),
                case(kind="paraphrase", question="how do I stop a command early"),
                case(
                    kind="no_answer",
                    question="how does click talk to a database",
                    expectedChunks=[],
                ),
            )
        )

        assert [entry.kind for entry in parsed.cases] == ["identifier", "paraphrase", "no_answer"]
        assert parsed.pinned_commit == COMMIT

    def test_a_no_answer_case_holds_no_expected_chunk(self) -> None:
        rejected(case_file(case(kind="no_answer")), "cases", 0)

    @pytest.mark.parametrize("kind", ["identifier", "paraphrase"])
    def test_any_other_kind_holds_at_least_one_expected_chunk(self, kind: str) -> None:
        rejected(case_file(case(kind=kind, expectedChunks=[])), "cases", 0)

    def test_a_kind_outside_the_three_is_refused(self) -> None:
        rejected(case_file(case(kind="trivia")), "cases", 0, "kind")

    @pytest.mark.parametrize("question", ["", "   ", "x" * 501, "a\x00b"])
    def test_a_question_is_held_to_what_a_search_text_is(self, question: str) -> None:
        rejected(case_file(case(question=question)), "cases", 0, "question")

    def test_a_question_is_trimmed_like_a_search_text(self) -> None:
        parsed = EvalCaseFile.model_validate(case_file(case(question="  where  ")))

        assert parsed.cases[0].question == "where"

    @pytest.mark.parametrize(
        "commit",
        ["", "main", COMMIT[:39], COMMIT + "0", COMMIT.upper(), COMMIT[:-1] + "g"],
    )
    def test_the_commit_is_forty_lowercase_hex_characters(self, commit: str) -> None:
        rejected(case_file(commit=commit), "pinnedCommit")

    @pytest.mark.parametrize(
        "chunk",
        [
            {**CHUNK, "path": ""},
            {**CHUNK, "startLine": 0},
            {**CHUNK, "endLine": 9},
            {**CHUNK, "startLine": "10"},
        ],
    )
    def test_an_expected_chunk_is_a_path_and_an_ordered_pair_of_lines(
        self, chunk: Mapping[str, object]
    ) -> None:
        rejected(case_file(case(expectedChunks=[chunk])), "cases", 0, "expectedChunks")

    def test_a_single_line_chunk_is_allowed(self) -> None:
        chunk = {**CHUNK, "startLine": 7, "endLine": 7}

        assert EvalCaseFile.model_validate(case_file(case(expectedChunks=[chunk])))

    def test_a_question_appears_once_in_a_file(self) -> None:
        rejected(case_file(case(), case()), "cases")

    def test_a_file_holds_at_least_one_case_and_at_most_the_run_cap(self) -> None:
        rejected({"pinnedCommit": COMMIT, "cases": []}, "cases")
        many = [case(question=f"question {n}") for n in range(EVAL.max_cases + 1)]
        rejected(case_file(*many), "cases")

    def test_a_snake_case_name_is_not_accepted(self) -> None:
        rejected({"pinned_commit": COMMIT, "cases": [case()]}, "pinnedCommit")


@pytest.fixture
async def empty_store() -> AsyncIterator[None]:
    await reset_store()
    yield
    await reset_store()


@pytest.fixture
async def bus() -> AsyncIterator[None]:
    await pubsub.connect()
    yield
    await pubsub.close()


@dataclass(frozen=True)
class _Text:
    text: str


async def indexed_fixture(client: httpx.AsyncClient) -> str:
    """The fixture repository connected and indexed: `ready` at `FIXTURE_COMMIT`."""
    res = await connect(client, admin_bearer())
    assert res.status_code == 201, res.text
    source_id = str(res.json()["id"])
    await index_source(source_id)
    # With the bus connected the connect also queued an index beside this one; wait it out so the
    # source is `ready` before a run looks.
    await drain()
    return source_id


async def start(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    res = await client.post("/api/eval-run", headers=headers)
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "queued"
    return str(res.json()["id"])


async def detail(client: httpx.AsyncClient, headers: dict[str, str], run_id: str) -> Json:
    res = await client.get(f"/api/eval-run/{run_id}", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body, dict)
    return body


async def run_to_the_end(client: httpx.AsyncClient) -> Json:
    """Seeds nothing: starts a run, lets the reaction's rule finish it and reads it back."""
    headers = admin_bearer()
    run_id = await start(client, headers)
    await execute_eval_run(run_id)
    return await detail(client, headers, run_id)


def rows(body: Json, name: str) -> list[Json]:
    value = body[name]
    assert isinstance(value, list)
    return [row for row in value if isinstance(row, dict)]


def score(body: Json, search: str, kind: str) -> Json:
    (found,) = [r for r in rows(body, "scores") if (r["search"], r["kind"]) == (search, kind)]
    return found


def embedded_questions() -> list[str]:
    return [
        str(request["input"])
        for request in fake_voyage.state.requests
        if request["input_type"] == "query"
    ]


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestEvalRun:
    """V02: a start ends `completed` with the scores of the fixture, scripted Voyage."""

    async def test_a_start_ends_completed_with_scores_per_search_and_kind(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)
        await replace_eval_cases(fixture_case_file())

        body = await run_to_the_end(client)

        assert body["status"] == "completed"
        assert body["errorCode"] is None
        assert (body["caseCount"], body["skippedCaseCount"], body["incompleteCaseCount"]) == (
            4,
            0,
            0,
        )
        assert score(body, "hybrid", "all")["recallAt5"] == 1.0
        assert score(body, "semantic", "identifier")["recallAt20"] == 0.0
        assert score(body, "keyword", "paraphrase")["recallAt20"] == 0.0
        assert score(body, "semantic", "paraphrase")["recallAt5"] == 1.0
        assert score(body, "keyword", "identifier")["recallAt5"] == 1.0
        assert score(body, "hybrid", "all")["caseCount"] == 3  # the no_answer case is no mean
        assert body["headline"] == score(body, "hybrid", "all")

    async def test_stores_a_row_per_case_with_its_rank_and_cosines(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)
        await replace_eval_cases(fixture_case_file())

        body = await run_to_the_end(client)

        by_question = {str(r["question"]): r for r in rows(body, "cases")}
        assert set(by_question) == {KEYWORD_QUERY, DOTTED_QUERY, SEMANTIC_QUERY, NO_ANSWER_QUESTION}
        paraphrase = by_question[SEMANTIC_QUERY]
        assert (paraphrase["kind"], paraphrase["rank"], paraphrase["skipReason"]) == (
            "paraphrase",
            1,
            None,
        )
        assert paraphrase["reciprocalRank"] == 1.0
        assert paraphrase["relevantCosine"] == pytest.approx(1.0, abs=5e-3)
        assert paraphrase["topCosine"] == pytest.approx(1.0, abs=5e-3)
        identifier = by_question[KEYWORD_QUERY]
        assert identifier["rank"] is not None
        no_answer = by_question[NO_ANSWER_QUESTION]
        assert isinstance(no_answer["topCosine"], float)
        assert {
            k: v for k, v in no_answer.items() if k not in {"question", "kind", "topCosine"}
        } == {
            "skipReason": None,
            "incomplete": False,
            "rank": None,
            "recallAt5": None,
            "recallAt10": None,
            "recallAt20": None,
            "reciprocalRank": None,
            "ndcgAt10": None,
            "relevantCosine": None,
        }

    async def test_stores_the_corpus_the_settings_and_the_cosine_evidence(
        self, client: httpx.AsyncClient
    ) -> None:
        source_id = await indexed_fixture(client)
        await replace_eval_cases(fixture_case_file())

        body = await run_to_the_end(client)

        assert body["corpus"] == [
            {
                "url": "https://github.com/octocat/Hello-World",
                "ref": "main",
                "indexedCommit": FIXTURE_COMMIT,
                "chunkCount": len(await stored_chunks(source_id)),
            }
        ]
        assert body["settings"] == {
            "embeddingModel": "voyage-code-4",
            "rrfK": SEARCH.rrf_k,
            "candidates": SEARCH.candidates,
            "keywordCandidates": SEARCH.keyword_candidates,
            "trigramThreshold": SEARCH.trigram_threshold,
        }
        cosine = body["cosine"]
        assert isinstance(cosine, dict)
        assert cosine["relevantMin"] is not None
        assert cosine["noAnswerMax"] is not None
        assert cosine["noAnswerMedian"] == cosine["noAnswerMax"]  # one no_answer case

    async def test_the_stored_row_holds_no_chunk_content(self, client: httpx.AsyncClient) -> None:
        source_id = await indexed_fixture(client)
        await replace_eval_cases(fixture_case_file())
        headers = admin_bearer()
        run_id = await start(client, headers)

        await execute_eval_run(run_id)

        row = await fetch_one(
            _Text,
            "select coalesce(scores::text, '') || coalesce(case_result::text, '') "
            "|| coalesce(corpus::text, '') || coalesce(settings::text, '') "
            "|| coalesce(cosine::text, '') as text from eval_run where id = %s",
            (run_id,),
        )
        assert row is not None
        chunks = await stored_chunks(source_id)
        assert chunks
        for chunk in chunks:
            assert chunk.content.strip().splitlines()[0] not in row.text
        assert "def sliding_window_remaining" not in row.text

    async def test_a_run_longer_than_the_search_window_embeds_once_per_case(
        self, client: httpx.AsyncClient
    ) -> None:
        """The rule is not the route: plan 006's window does not stretch a run, and the admin who
        starts one still searches afterwards. One `headers` throughout, because a new bearer is a
        new caller and would pass on any code."""
        await indexed_fixture(client)
        count = RATE_LIMITS.search_per_user.limit + 3
        await replace_eval_cases(fixture_case_file(generated_cases(count)))
        headers = admin_bearer()
        run_id = await start(client, headers)

        await execute_eval_run(run_id)

        body = await detail(client, headers, run_id)
        assert body["status"] == "completed"
        assert len(embedded_questions()) == count
        search = await client.get("/api/search", params={"q": "check_limit"}, headers=headers)
        assert search.status_code == 200, search.text

    async def test_a_run_asks_for_the_whole_union_of_the_three_searches(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await indexed_fixture(client)
        await replace_eval_cases(fixture_case_file())
        limits: list[int] = []

        async def spy(*, text: str, limit: int) -> SearchOutcome:
            limits.append(limit)
            return await search_knowledge_base(text=text, limit=limit)

        monkeypatch.setattr("app.api.eval.controller.search_knowledge_base", spy)

        await run_to_the_end(client)

        assert limits == [EVAL.hit_limit] * 4

    async def test_an_incomplete_search_is_counted(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await indexed_fixture(client)
        await replace_eval_cases(fixture_case_file())
        small = replace(SEARCH, keyword_candidates=1)
        monkeypatch.setattr("app.api.source.service.SEARCH", small)
        monkeypatch.setattr("app.api.source.controller.SEARCH", small)

        body = await run_to_the_end(client)

        assert body["status"] == "completed"
        incomplete = [r for r in rows(body, "cases") if r["incomplete"]]
        assert body["incompleteCaseCount"] == len(incomplete) >= 1

    @pytest.mark.usefixtures("bus")
    async def test_the_start_is_carried_out_beside_the_request(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)
        await replace_eval_cases(fixture_case_file())
        headers = admin_bearer()

        run_id = await start(client, headers)
        await drain()

        assert (await detail(client, headers, run_id))["status"] == "completed"


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestSkippedCase:
    """V03: what cannot run is skipped before anything is spent."""

    async def test_a_case_with_no_ready_source_at_its_commit_is_skipped_unembedded(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)
        elsewhere = case_at("other question", "f" * 40)
        await replace_eval_cases(fixture_case_file())
        await replace_eval_cases(elsewhere)

        body = await run_to_the_end(client)

        skipped = [r for r in rows(body, "cases") if r["skipReason"] is not None]
        assert [(r["question"], r["skipReason"]) for r in skipped] == [
            ("other question", "source_missing")
        ]
        assert skipped[0]["rank"] is None
        assert skipped[0]["topCosine"] is None
        assert (body["caseCount"], body["skippedCaseCount"]) == (5, 1)
        assert "other question" not in embedded_questions()
        assert len(embedded_questions()) == 4

    async def test_an_expected_chunk_no_stored_chunk_matches_is_skipped_unembedded(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)
        missing: list[Json] = [
            {
                "kind": "identifier",
                "question": "where is the lost file",
                "expectedChunks": [{"path": "src/not_there.py", "startLine": 1, "endLine": 5}],
            }
        ]
        await replace_eval_cases(fixture_case_file(fixture_cases() + missing))

        body = await run_to_the_end(client)

        skipped = [r for r in rows(body, "cases") if r["skipReason"] is not None]
        assert [(r["question"], r["skipReason"]) for r in skipped] == [
            ("where is the lost file", "expected_chunk_missing")
        ]
        assert "where is the lost file" not in embedded_questions()
        assert score(body, "hybrid", "all")["caseCount"] == 3

    async def test_nothing_to_run_is_failed_with_no_embedding(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)
        await replace_eval_cases(fixture_case_file(commit="e" * 40))

        body = await run_to_the_end(client)

        assert (body["status"], body["errorCode"]) == ("failed", "no_runnable_case")
        assert (body["scores"], body["cases"]) == ([], [])
        assert body["cosine"] is None
        assert body["headline"] is None
        assert embedded_questions() == []

    async def test_no_case_at_all_is_failed_no_runnable_case(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)

        body = await run_to_the_end(client)

        assert (body["status"], body["errorCode"]) == ("failed", "no_runnable_case")
        assert embedded_questions() == []

    async def test_no_ready_source_at_all_skips_every_case(self, client: httpx.AsyncClient) -> None:
        await replace_eval_cases(fixture_case_file())

        body = await run_to_the_end(client)

        assert (body["status"], body["errorCode"]) == ("failed", "no_runnable_case")
        assert body["corpus"] == []


def case_at(question: str, commit: str) -> EvalCaseFile:
    return fixture_case_file([fixture_cases()[3] | {"question": question}], commit=commit)


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestFailedRun:
    """V03: all or nothing; a mean over fewer cases does not compare."""

    async def test_voyage_down_mid_run_is_failed_search_unavailable_with_no_scores(
        self, client: httpx.AsyncClient
    ) -> None:
        await indexed_fixture(client)
        failing = [
            {
                "kind": "paraphrase",
                "question": "zzz down [[fail:evalrun]]",
                "expectedChunks": fixture_cases()[2]["expectedChunks"],
            }
        ]
        await replace_eval_cases(fixture_case_file(fixture_cases() + failing))

        body = await run_to_the_end(client)

        assert (body["status"], body["errorCode"]) == ("failed", "search_unavailable")
        assert (body["scores"], body["cases"]) == ([], [])
        assert body["cosine"] is None
        assert body["headline"] is None
        assert len(embedded_questions()) > 1  # earlier cases were embedded and scored for nothing
        assert body["corpus"] != []  # the snapshot of what it tried to search stays

    async def test_an_unexpected_error_is_failed_internal_and_leaks_nothing(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await indexed_fixture(client)
        await replace_eval_cases(fixture_case_file())

        async def broken(*, text: str, limit: int) -> None:
            raise RuntimeError(f"secret internals {text} {limit}")

        monkeypatch.setattr("app.api.eval.controller.search_knowledge_base", broken)

        body = await run_to_the_end(client)

        assert (body["status"], body["errorCode"]) == ("failed", "internal")
        assert "secret internals" not in json.dumps(body)

    async def test_a_cancellation_ends_the_run_interrupted_and_is_re_raised(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await indexed_fixture(client)
        await replace_eval_cases(fixture_case_file())
        headers = admin_bearer()
        run_id = await start(client, headers)

        async def cancelled(*, text: str, limit: int) -> None:
            raise asyncio.CancelledError

        monkeypatch.setattr("app.api.eval.controller.search_knowledge_base", cancelled)

        with pytest.raises(asyncio.CancelledError):
            await execute_eval_run(run_id)

        body = await detail(client, headers, run_id)
        assert (body["status"], body["errorCode"]) == ("failed", "interrupted")

    async def test_a_run_that_is_not_queued_is_left_alone(self, client: httpx.AsyncClient) -> None:
        await indexed_fixture(client)
        await replace_eval_cases(fixture_case_file())

        body = await run_to_the_end(client)
        await execute_eval_run(str(body["id"]))  # the second claim finds it completed

        again = await detail(client, admin_bearer(), str(body["id"]))
        assert again["updatedAt"] == body["updatedAt"]
        assert len(embedded_questions()) == 4


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestOneActive:
    """V04: one run at a time, and a lost one ends `interrupted`."""

    async def test_a_second_start_while_one_is_active_is_a_409(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = admin_bearer()
        first = await start(client, headers)

        res = await client.post("/api/eval-run", headers=headers)

        assert res.status_code == 409
        assert error_of(res).code == "conflict"
        assert res.json()["requestId"]
        listing = await client.get("/api/eval-run", headers=headers)
        assert [item["id"] for item in listing.json()["items"]] == [first]

    async def test_a_start_is_allowed_again_once_the_run_has_ended(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = admin_bearer()
        first = await start(client, headers)
        await execute_eval_run(first)  # no cases: ends failed

        second = await start(client, headers)

        assert second != first

    async def test_the_boot_sweep_ends_a_lost_run_interrupted(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = admin_bearer()
        queued = await start(client, headers)

        ended = await fail_lost_eval_runs(clock.now() + timedelta(seconds=1))

        assert ended == 1
        body = await detail(client, headers, queued)
        assert (body["status"], body["errorCode"]) == ("failed", "interrupted")
        assert await start(client, headers)  # the slot is free

    async def test_the_sweep_leaves_a_run_started_after_the_boot_alone(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = admin_bearer()
        run_id = await start(client, headers)

        ended = await fail_lost_eval_runs(clock.now() - timedelta(hours=1))

        assert ended == 0
        assert (await detail(client, headers, run_id))["status"] == "queued"


@store_backed
@pytest.mark.usefixtures("empty_store")
class TestSeed:
    """V03: the seed replaces a commit's cases in one transaction; a bad file writes nothing."""

    async def stored(self, commit: str = FIXTURE_COMMIT) -> list[str]:
        return [
            case.question for case in await service.list_cases() if case.pinned_commit == commit
        ]

    async def test_two_seeds_of_one_file_leave_one_set(self) -> None:
        await replace_eval_cases(fixture_case_file())
        await replace_eval_cases(fixture_case_file())

        assert sorted(await self.stored()) == sorted(
            [KEYWORD_QUERY, DOTTED_QUERY, SEMANTIC_QUERY, NO_ANSWER_QUESTION]
        )

    async def test_a_question_the_file_no_longer_holds_is_dropped(self) -> None:
        await replace_eval_cases(fixture_case_file())
        await replace_eval_cases(fixture_case_file(fixture_cases()[:2]))

        assert sorted(await self.stored()) == sorted([KEYWORD_QUERY, DOTTED_QUERY])

    async def test_a_changed_label_replaces_the_old_one(self) -> None:
        await replace_eval_cases(fixture_case_file())
        moved = fixture_cases()
        moved[0] = {**moved[0], "expectedChunks": [{"path": "a.py", "startLine": 1, "endLine": 2}]}

        await replace_eval_cases(fixture_case_file(moved))

        (stored,) = [c for c in await service.list_cases() if c.question == KEYWORD_QUERY]
        assert [(e.path, e.start_line, e.end_line) for e in stored.expected_chunks] == [
            ("a.py", 1, 2)
        ]

    async def test_another_commit_is_left_alone(self) -> None:
        await replace_eval_cases(fixture_case_file())
        await replace_eval_cases(case_at("elsewhere", "c" * 40))

        await replace_eval_cases(fixture_case_file(fixture_cases()[:1]))

        assert await self.stored("c" * 40) == ["elsewhere"]

    async def test_two_seeds_started_together_do_not_collide(self) -> None:
        await asyncio.gather(
            replace_eval_cases(fixture_case_file()), replace_eval_cases(fixture_case_file())
        )

        assert len(await self.stored()) == 4

    async def test_a_total_over_the_cap_is_refused_and_writes_nothing(self) -> None:
        await replace_eval_cases(fixture_case_file())
        many = fixture_case_file(generated_cases(EVAL.max_cases), commit="d" * 40)

        with pytest.raises(AppError) as refusal:
            await replace_eval_cases(many)

        assert refusal.value.code == "validation_failed"
        assert await self.stored("d" * 40) == []
        assert len(await self.stored()) == 4

    async def test_the_cap_counts_the_cases_of_other_commits_but_not_the_ones_replaced(
        self,
    ) -> None:
        await replace_eval_cases(fixture_case_file(generated_cases(EVAL.max_cases - 1)))

        await replace_eval_cases(fixture_case_file(generated_cases(EVAL.max_cases)))

        assert len(await self.stored()) == EVAL.max_cases

    async def test_a_good_file_exits_0(self, tmp_path: Path) -> None:
        path = tmp_path / "cases.json"
        path.write_text(json.dumps(fixture_file()), encoding="utf-8")

        assert await seed([str(path)]) == 0
        assert len(await self.stored()) == 4

    @pytest.mark.parametrize(
        "text",
        [
            "not json",
            "[]",
            json.dumps({"pinnedCommit": "main", "cases": []}),
            json.dumps(
                fixture_file(
                    [{"kind": "no_answer", "question": "q", "expectedChunks": [{"path": "a"}]}]
                )
            ),
            json.dumps(fixture_file([fixture_cases()[0] | {"expectedChunks": []}])),
        ],
    )
    async def test_a_bad_file_exits_1_and_writes_nothing(self, tmp_path: Path, text: str) -> None:
        path = tmp_path / "cases.json"
        path.write_text(text, encoding="utf-8")

        assert await seed([str(path)]) == 1
        assert await service.list_cases() == []

    async def test_a_missing_file_or_a_wrong_argument_count_exits_1(self, tmp_path: Path) -> None:
        assert await seed([str(tmp_path / "nothing.json")]) == 1
        assert await seed([]) == 1
        assert await seed(["a.json", "b.json"]) == 1


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestStoredAccess:
    """V05: an admin reads a page of runs and one run; an unknown id is a 404."""

    async def test_a_page_of_runs_is_newest_first_and_pages_by_cursor(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = admin_bearer()
        ids: list[str] = []
        for _ in range(3):
            ids.append(await start(client, headers))
            await execute_eval_run(ids[-1])

        first = await client.get("/api/eval-run?limit=2", headers=headers)
        second = await client.get(
            f"/api/eval-run?limit=2&cursor={first.json()['nextCursor']}", headers=headers
        )

        assert [item["id"] for item in first.json()["items"]] == [ids[2], ids[1]]
        assert [item["id"] for item in second.json()["items"]] == [ids[0]]
        assert second.json()["nextCursor"] is None
        assert set(first.json()["items"][0]) == {
            "id",
            "status",
            "errorCode",
            "caseCount",
            "skippedCaseCount",
            "incompleteCaseCount",
            "headline",
            "createdAt",
            "updatedAt",
        }

    async def test_a_bad_cursor_is_a_400(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/eval-run?cursor=not-a-cursor", headers=admin_bearer())

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"
        assert res.json()["requestId"]

    async def test_an_empty_store_is_an_empty_page(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/eval-run", headers=admin_bearer())

        assert res.json() == {"items": [], "nextCursor": None}

    async def test_a_queued_run_has_nothing_to_show_yet(self, client: httpx.AsyncClient) -> None:
        headers = admin_bearer()
        run_id = await start(client, headers)

        body = await detail(client, headers, run_id)

        assert body["status"] == "queued"
        assert (body["scores"], body["cases"], body["corpus"]) == ([], [], [])
        assert (body["settings"], body["cosine"], body["headline"]) == (None, None, None)

    async def test_an_unknown_id_is_a_404_with_the_envelope(
        self, client: httpx.AsyncClient
    ) -> None:
        res = await client.get("/api/eval-run/no-such-run", headers=admin_bearer())

        assert res.status_code == 404
        assert error_of(res).code == "not_found"
        assert res.json()["requestId"]

    async def test_a_user_cannot_read_a_stored_run(self, client: httpx.AsyncClient) -> None:
        run_id = await start(client, admin_bearer())

        res = await client.get(f"/api/eval-run/{run_id}", headers=member_bearer())

        assert res.status_code == 403


class TestAccess:
    """Every route is admin-only: 401 without a token, 403 for a user, each with the envelope."""

    CALLS = (
        ("POST", "/api/eval-run"),
        ("GET", "/api/eval-run"),
        ("GET", "/api/eval-run/some-id"),
    )

    @pytest.mark.parametrize(("method", "path"), CALLS)
    async def test_no_token_is_a_401(
        self, client: httpx.AsyncClient, method: str, path: str
    ) -> None:
        res = await client.request(method, path)

        assert res.status_code == 401
        assert error_of(res).code == "unauthenticated"
        assert res.json()["requestId"]

    @pytest.mark.parametrize(("method", "path"), CALLS)
    async def test_a_user_is_a_403(self, client: httpx.AsyncClient, method: str, path: str) -> None:
        res = await client.request(method, path, headers=member_bearer())

        assert res.status_code == 403
        assert error_of(res).code == "forbidden"
        assert res.json()["requestId"]


class TestListQuery:
    @pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=abc"])
    async def test_a_bad_query_is_a_400_naming_the_part(
        self, client: httpx.AsyncClient, query: str
    ) -> None:
        res = await client.get(f"/api/eval-run?{query}", headers=admin_bearer())

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"
        assert res.json()["requestId"]
