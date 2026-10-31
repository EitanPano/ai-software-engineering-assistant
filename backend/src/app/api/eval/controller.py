"""controller.py belongs: the eval module's business logic and its HTTP handlers, and the system
operations the boot sweep, the run's subscriber and the seed command call. Each handler rechecks
the admin role, because `routes.py` gates with `require_role` and an endpoint mounted without its
gate must still refuse.
It does not belong: gates (`routes.py`), queries (`service.py`), schemas (`schema.py`) or the
metrics' arithmetic (`services/utils/retrieval_metric.py`).

A start stores a `queued` run and publishes `eval_run.queued`; `infra/subscribers/
execute_eval_run.py` calls `execute_eval_run`, the same shape as `index_source`. The run takes the
cases in order and, for each one it can run, calls `search_knowledge_base` (the rule the agent will
use, not `GET /api/search`, whose per-user window would stretch a run and lock the admin out). A
case is skipped, visibly and before anything is spent, when no `ready` source stands at its commit
or no stored chunk matches an expected chunk, so a bad label is never read as bad retrieval. A run
is all or nothing: one failed search fails it with no scores, because a mean over fewer cases does
not compare. It stores ranks, cosines, questions, its corpus and its settings, never a hit's
content, and it ends `completed` or `failed` on every exit.
"""

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated

from fastapi import Query, Request
from pydantic import MISSING

from app.api.eval import service
from app.api.eval.schema import (
    EvalCaseFile,
    EvalCaseResult,
    EvalCorpus,
    EvalCosine,
    EvalRun,
    EvalRunDetail,
    EvalRunId,
    EvalRunPage,
    EvalRunSettings,
    EvalScore,
)
from app.api.search.controller import search_knowledge_base
from app.api.source.controller import find_chunk_lines, list_ready_sources
from app.config.constants import EMBEDDING, EVAL, SEARCH
from app.middleware.auth import require_caller
from app.models.auth.type import Caller
from app.models.eval.enums import (
    EvalCaseKind,
    EvalRunErrorCode,
    EvalRunStatus,
    EvalScoreKind,
    EvalSearch,
    EvalSkipReason,
)
from app.models.eval.interface import (
    EvalCaseRecord,
    EvalCaseResultRecord,
    EvalCorpusRecord,
    EvalCosineRecord,
    EvalRunRecord,
    EvalScoreRecord,
    EvalSettingsRecord,
    ExpectedChunk,
)
from app.models.eval.type import CaseMetrics, RankedHit, Span
from app.models.search.interface import SearchHitRecord
from app.models.source.type import ChunkLines
from app.models.user.enums import UserRole
from app.services.event import EVAL_RUN_QUEUED, publish
from app.services.logger import log
from app.services.utils import clock
from app.services.utils.error import AppError
from app.services.utils.pagination import PageQuery
from app.services.utils.postgres_error import classify_postgres_error
from app.services.utils.retrieval_metric import (
    is_relevant,
    mean,
    median,
    order_hits,
    score_case,
)


def _assert_admin(caller: Caller) -> None:
    if caller.role is not UserRole.admin:
        raise AppError("forbidden", "insufficient role")


# The wire's literals are the enums' values: mypy types `.value` as the union of the members'
# values, so a member added to one side and not the other fails the type check here.
def _to_score(record: EvalScoreRecord) -> EvalScore:
    return EvalScore(
        search=record.search.value,
        kind=record.kind.value,
        case_count=record.case_count,
        recall_at_5=record.recall_at_5,
        recall_at_10=record.recall_at_10,
        recall_at_20=record.recall_at_20,
        mrr=record.mrr,
        ndcg_at_10=record.ndcg_at_10,
    )


def _to_case_result(record: EvalCaseResultRecord) -> EvalCaseResult:
    return EvalCaseResult(
        question=record.question,
        kind=record.kind.value,
        skip_reason=None if record.skip_reason is None else record.skip_reason.value,
        incomplete=record.incomplete,
        rank=record.rank,
        recall_at_5=record.recall_at_5,
        recall_at_10=record.recall_at_10,
        recall_at_20=record.recall_at_20,
        reciprocal_rank=record.reciprocal_rank,
        ndcg_at_10=record.ndcg_at_10,
        top_cosine=record.top_cosine,
        relevant_cosine=record.relevant_cosine,
    )


def _headline(record: EvalRunRecord) -> EvalScore | None:
    """The `hybrid` `all` row."""
    for score in record.scores:
        if score.search is EvalSearch.hybrid and score.kind is EvalScoreKind.all:
            return _to_score(score)
    return None


def _to_run(record: EvalRunRecord) -> EvalRun:
    return EvalRun(
        id=record.id,
        status=record.status.value,
        error_code=None if record.error_code is None else record.error_code.value,
        case_count=record.case_count,
        skipped_case_count=record.skipped_case_count,
        incomplete_case_count=record.incomplete_case_count,
        headline=_headline(record),
        created_at=clock.to_iso(record.created_at),
        updated_at=clock.to_iso(record.updated_at),
    )


def _to_detail(record: EvalRunRecord) -> EvalRunDetail:
    settings = record.settings
    cosine = record.cosine
    run = _to_run(record)
    return EvalRunDetail(
        id=run.id,
        status=run.status,
        error_code=run.error_code,
        case_count=run.case_count,
        skipped_case_count=run.skipped_case_count,
        incomplete_case_count=run.incomplete_case_count,
        headline=run.headline,
        created_at=run.created_at,
        updated_at=run.updated_at,
        scores=[_to_score(score) for score in record.scores],
        cases=[_to_case_result(result) for result in record.case_results],
        corpus=[
            EvalCorpus(
                url=source.url,
                ref=source.ref,
                indexed_commit=source.indexed_commit,
                chunk_count=source.chunk_count,
            )
            for source in record.corpus
        ],
        settings=(
            None
            if settings is None
            else EvalRunSettings(
                embedding_model=settings.embedding_model,
                rrf_k=settings.rrf_k,
                candidates=settings.candidates,
                keyword_candidates=settings.keyword_candidates,
                trigram_threshold=settings.trigram_threshold,
            )
        ),
        cosine=(
            None
            if cosine is None
            else EvalCosine(
                relevant_min=cosine.relevant_min,
                relevant_median=cosine.relevant_median,
                no_answer_median=cosine.no_answer_median,
                no_answer_max=cosine.no_answer_max,
            )
        ),
    )


async def start_eval_run(request: Request) -> EvalRun:
    """Stores a `queued` run and publishes it. A second start while one is active violates the
    partial unique index, which the error handler answers as a 409."""
    _assert_admin(require_caller(request))
    now = clock.now()
    record = await service.insert_run(
        EvalRunRecord(
            id=str(uuid.uuid4()),
            status=EvalRunStatus.queued,
            error_code=None,
            case_count=0,
            skipped_case_count=0,
            incomplete_case_count=0,
            scores=(),
            case_results=(),
            corpus=(),
            settings=None,
            cosine=None,
            created_at=now,
            updated_at=now,
        )
    )
    await publish(EVAL_RUN_QUEUED, {"eval_run_id": record.id})
    return _to_run(record)


async def list_eval_run(request: Request, query: Annotated[PageQuery, Query()]) -> EvalRunPage:
    _assert_admin(require_caller(request))
    page = await service.list_runs(
        cursor=None if query.cursor is MISSING else query.cursor, limit=query.limit
    )
    return EvalRunPage(
        items=[_to_run(record) for record in page.items], next_cursor=page.next_cursor
    )


async def get_eval_run(request: Request, eval_run_id: EvalRunId) -> EvalRunDetail:
    _assert_admin(require_caller(request))
    record = await service.find_run(eval_run_id)
    if record is None:
        raise AppError("not_found", "eval run not found")
    return _to_detail(record)


class _NoRunnableCaseError(Exception):
    """Every case was skipped, or there is none: nothing was spent and nothing can be scored."""


def _failure_code(error: Exception) -> EvalRunErrorCode | None:
    """The code an expected failure ends a run with; `None` for anything else."""
    if isinstance(error, _NoRunnableCaseError):
        return EvalRunErrorCode.no_runnable_case
    app_error = error if isinstance(error, AppError) else classify_postgres_error(error)
    if app_error is not None and app_error.code == "upstream_unavailable":
        return EvalRunErrorCode.search_unavailable
    return None


async def execute_eval_run(run_id: str) -> None:
    """System operation: carries one queued run to its end. A run that is not queued (another
    executor has it, or the boot sweep ended it) is left alone. Every exit ends it `completed` or
    `failed`."""
    if not await service.claim_run(run_id, clock.now()):
        return
    try:
        await _execute(run_id)
    except asyncio.CancelledError:
        # A shutdown: end the run now rather than leave it for the next boot's sweep.
        await asyncio.shield(_end_failed(run_id, EvalRunErrorCode.interrupted))
        raise
    except Exception as error:
        code = _failure_code(error)
        if code is None:
            log.error("eval run failed", {"evalRunId": run_id}, error)
            code = EvalRunErrorCode.internal
        else:
            log.warning("eval run failed", {"evalRunId": run_id, "reason": code.value})
        await _end_failed(run_id, code)


async def _end_failed(run_id: str, code: EvalRunErrorCode) -> None:
    if not await service.finish_failed(run_id, code, clock.now()):
        log.warning("eval run already over", {"evalRunId": run_id})


def _span_of(case: EvalCaseRecord, expected: ExpectedChunk) -> Span:
    return Span(case.pinned_commit, expected.path, expected.start_line, expected.end_line)


def _stored(lines: Sequence[ChunkLines]) -> dict[tuple[str, str], list[Span]]:
    by_file: dict[tuple[str, str], list[Span]] = {}
    for chunk in lines:
        span = Span(chunk.commit, chunk.path, chunk.start_line, chunk.end_line)
        by_file.setdefault((chunk.commit, chunk.path), []).append(span)
    return by_file


async def _skips(
    cases: Sequence[EvalCaseRecord], commits: frozenset[str]
) -> dict[str, EvalSkipReason]:
    """The cases that cannot run, by id, decided from stored chunk positions alone: nothing is
    embedded. An expected chunk is missing when no stored chunk would count as relevant to it."""
    at_commit = [case for case in cases if case.pinned_commit in commits]
    paths = sorted({e.path for case in at_commit for e in case.expected_chunks})
    stored = _stored(
        await find_chunk_lines(
            commits=sorted({case.pinned_commit for case in at_commit}), paths=paths
        )
    )
    skips: dict[str, EvalSkipReason] = {}
    for case in cases:
        if case.pinned_commit not in commits:
            skips[case.id] = EvalSkipReason.source_missing
            continue
        for expected in case.expected_chunks:
            label = _span_of(case, expected)
            candidates = stored.get((label.commit, label.path), [])
            # The metric's own rule: a label is present exactly when a hit at that place would
            # count as relevant.
            if not any(is_relevant(chunk, label) for chunk in candidates):
                skips[case.id] = EvalSkipReason.expected_chunk_missing
                break
    return skips


def _ranked(hit: SearchHitRecord, commit_by_source: Mapping[str, str]) -> RankedHit:
    # A source that became `ready` after the snapshot has no commit here, so it is relevant to
    # nothing.
    commit = commit_by_source.get(hit.source_id, "")
    return RankedHit(
        span=Span(commit, hit.path, hit.start_line, hit.end_line),
        semantic_rank=hit.semantic_rank,
        full_text_rank=hit.full_text_rank,
        trigram_rank=hit.trigram_rank,
        cosine=hit.cosine,
    )


def _top_cosine(hits: Sequence[RankedHit]) -> float | None:
    """The cosine of the semantic search's first hit."""
    return next((hit.cosine for hit in hits if hit.semantic_rank == 1), None)


def _skipped_result(case: EvalCaseRecord, reason: EvalSkipReason) -> EvalCaseResultRecord:
    return EvalCaseResultRecord(
        question=case.question,
        kind=case.kind,
        skip_reason=reason,
        incomplete=False,
        rank=None,
        recall_at_5=None,
        recall_at_10=None,
        recall_at_20=None,
        reciprocal_rank=None,
        ndcg_at_10=None,
        top_cosine=None,
        relevant_cosine=None,
    )


def _scored_result(
    case: EvalCaseRecord,
    metrics: CaseMetrics,
    hybrid: Sequence[RankedHit],
    *,
    incomplete: bool,
) -> EvalCaseResultRecord:
    best = None if metrics.rank is None else hybrid[metrics.rank - 1]
    return EvalCaseResultRecord(
        question=case.question,
        kind=case.kind,
        skip_reason=None,
        incomplete=incomplete,
        rank=metrics.rank,
        recall_at_5=metrics.recall_at_5,
        recall_at_10=metrics.recall_at_10,
        recall_at_20=metrics.recall_at_20,
        reciprocal_rank=metrics.reciprocal_rank,
        ndcg_at_10=metrics.ndcg_at_10,
        top_cosine=_top_cosine(hybrid),
        relevant_cosine=None if best is None else best.cosine,
    )


def _no_answer_result(
    case: EvalCaseRecord, hits: Sequence[RankedHit], *, incomplete: bool
) -> EvalCaseResultRecord:
    return EvalCaseResultRecord(
        question=case.question,
        kind=case.kind,
        skip_reason=None,
        incomplete=incomplete,
        rank=None,
        recall_at_5=None,
        recall_at_10=None,
        recall_at_20=None,
        reciprocal_rank=None,
        ndcg_at_10=None,
        top_cosine=_top_cosine(hits),
        relevant_cosine=None,
    )


_SCORE_KINDS = (
    (EvalScoreKind.all, None),
    (EvalScoreKind.identifier, EvalCaseKind.identifier),
    (EvalScoreKind.paraphrase, EvalCaseKind.paraphrase),
)


def _scores(
    by_search: Mapping[EvalSearch, list[tuple[EvalCaseKind, CaseMetrics]]],
) -> list[EvalScoreRecord]:
    """One row per search and kind of case; a row with no case is absent."""
    rows: list[EvalScoreRecord] = []
    for search in EvalSearch:
        for score_kind, case_kind in _SCORE_KINDS:
            metrics = [m for kind, m in by_search[search] if case_kind in (None, kind)]
            if not metrics:
                continue
            rows.append(
                EvalScoreRecord(
                    search=search,
                    kind=score_kind,
                    case_count=len(metrics),
                    recall_at_5=mean([m.recall_at_5 for m in metrics]) or 0.0,
                    recall_at_10=mean([m.recall_at_10 for m in metrics]) or 0.0,
                    recall_at_20=mean([m.recall_at_20 for m in metrics]) or 0.0,
                    mrr=mean([m.reciprocal_rank for m in metrics]) or 0.0,
                    ndcg_at_10=mean([m.ndcg_at_10 for m in metrics]) or 0.0,
                )
            )
    return rows


def _cosine(results: Sequence[EvalCaseResultRecord]) -> EvalCosineRecord:
    """The cutoff's evidence: the cosine of the best relevant hit of each answerable case against
    the cosine of the best hit of each `no_answer` case."""
    relevant = [
        r.relevant_cosine
        for r in results
        if r.kind is not EvalCaseKind.no_answer and r.relevant_cosine is not None
    ]
    none = [
        r.top_cosine
        for r in results
        if r.kind is EvalCaseKind.no_answer and r.top_cosine is not None
    ]
    return EvalCosineRecord(
        relevant_min=min(relevant, default=None),
        relevant_median=median(relevant),
        no_answer_median=median(none),
        no_answer_max=max(none, default=None),
    )


async def _execute(run_id: str) -> None:
    cases = await service.list_cases()
    sources = [s for s in await list_ready_sources() if s.indexed_commit is not None]
    commit_by_source = {s.id: s.indexed_commit for s in sources if s.indexed_commit is not None}
    skips = await _skips(cases, frozenset(commit_by_source.values()))
    await service.record_start(
        run_id,
        case_count=len(cases),
        skipped_case_count=len(skips),
        corpus=[
            EvalCorpusRecord(
                url=s.url,
                ref=s.ref,
                indexed_commit=s.indexed_commit or "",
                chunk_count=s.chunk_count,
            )
            for s in sources
        ],
        settings=EvalSettingsRecord(
            embedding_model=EMBEDDING.model,
            rrf_k=SEARCH.rrf_k,
            candidates=SEARCH.candidates,
            keyword_candidates=SEARCH.keyword_candidates,
            trigram_threshold=SEARCH.trigram_threshold,
        ),
        now=clock.now(),
    )
    if len(skips) == len(cases):
        raise _NoRunnableCaseError

    by_search: dict[EvalSearch, list[tuple[EvalCaseKind, CaseMetrics]]] = {
        s: [] for s in EvalSearch
    }
    results: list[EvalCaseResultRecord] = []
    incomplete = 0
    for case in cases:
        reason = skips.get(case.id)
        if reason is not None:
            results.append(_skipped_result(case, reason))
            continue
        outcome = await search_knowledge_base(text=case.question, limit=EVAL.hit_limit)
        hits = [_ranked(hit, commit_by_source) for hit in outcome.hits]
        incomplete += outcome.incomplete
        if case.kind is EvalCaseKind.no_answer:
            results.append(_no_answer_result(case, hits, incomplete=outcome.incomplete))
            continue
        expected = [_span_of(case, e) for e in case.expected_chunks]
        for search in EvalSearch:
            ordered = order_hits(hits, search, rrf_k=SEARCH.rrf_k)
            metrics = score_case(ordered, expected, depth=EVAL.depth)
            by_search[search].append((case.kind, metrics))
            if search is EvalSearch.hybrid:
                results.append(
                    _scored_result(case, metrics, ordered, incomplete=outcome.incomplete)
                )

    finished = await service.finish_completed(
        run_id,
        incomplete_case_count=incomplete,
        scores=_scores(by_search),
        case_results=results,
        cosine=_cosine(results),
        now=clock.now(),
    )
    log.info(
        "eval run ended",
        {
            "evalRunId": run_id,
            "cases": len(cases),
            "skipped": len(skips),
            "incomplete": incomplete,
            "stored": finished,
        },
    )


async def replace_eval_cases(file: EvalCaseFile) -> int:
    """System operation: the seed. Makes the cases of the file's commit exactly the file's, in one
    transaction: an upsert on `(commit, question)` so two seeds of one file cannot collide, then
    a delete of the questions the file no longer holds. Other commits are left alone. Refused
    with nothing written when the total across commits would pass `EVAL.max_cases`."""

    async def work(db: service.Tx) -> None:
        outside = await service.count_cases_outside(file.pinned_commit, db=db)
        if outside + len(file.cases) > EVAL.max_cases:
            raise AppError(
                "validation_failed",
                f"a run holds at most {EVAL.max_cases} cases in total",
            )
        now = clock.now()
        for entry in file.cases:
            await service.upsert_case(
                EvalCaseRecord(
                    id=str(uuid.uuid4()),
                    pinned_commit=file.pinned_commit,
                    kind=EvalCaseKind(entry.kind),
                    question=entry.question,
                    expected_chunks=tuple(
                        ExpectedChunk(chunk.path, chunk.start_line, chunk.end_line)
                        for chunk in entry.expected_chunks
                    ),
                    created_at=now,
                    updated_at=now,
                ),
                db=db,
            )
        await service.delete_cases_except(
            file.pinned_commit, [entry.question for entry in file.cases], db=db
        )

    await service.with_transaction(work)
    return len(file.cases)


async def fail_lost_eval_runs(started_before: datetime) -> int:
    """System operation: the boot sweep. Runs still active that were last touched before this
    process started belong to a process that is gone; each ends `failed` as `interrupted`, and is
    never requeued."""
    failed = 0
    for record in await service.list_active_before(started_before):
        if await service.finish_failed(record.id, EvalRunErrorCode.interrupted, clock.now()):
            failed += 1
    if failed:
        log.warning("failed lost eval runs", {"count": failed})
    return failed
