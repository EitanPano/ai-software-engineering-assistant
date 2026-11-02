"""interface.py belongs: the stored `eval_case` and `eval_run` records, what `api/eval/service.py`
reads and writes, and the parts of a run kept in its JSONB columns. Frozen dataclasses despite the
name. A run stores ranks, cosines, questions, its corpus and its settings, never a hit's content.
It does not belong: the wire shape (`api/eval/schema.py`) or value sets (`enums.py`).
"""

from dataclasses import dataclass
from datetime import datetime

from app.models.eval.enums import (
    EvalCaseKind,
    EvalRunErrorCode,
    EvalRunStatus,
    EvalScoreKind,
    EvalSearch,
    EvalSkipReason,
)


@dataclass(frozen=True)
class ExpectedChunk:
    """A label: lines `start_line` to `end_line` (1-based, inclusive) of `path` at the case's
    pinned commit. Never a chunk id, because every index mints new ones."""

    path: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class EvalCaseRecord:
    id: str
    pinned_commit: str
    kind: EvalCaseKind
    question: str
    expected_chunks: tuple[ExpectedChunk, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class EvalScoreRecord:
    """The mean of each metric over the scored cases of one search and one kind, each 0 to 1."""

    search: EvalSearch
    kind: EvalScoreKind
    case_count: int
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    mrr: float
    ndcg_at_10: float


@dataclass(frozen=True)
class EvalCaseResultRecord:
    """One case's outcome under `hybrid`. A skipped case and a `no_answer` case carry no metric;
    a `no_answer` case has only `top_cosine`."""

    question: str
    kind: EvalCaseKind
    skip_reason: EvalSkipReason | None
    incomplete: bool
    rank: int | None
    recall_at_5: float | None
    recall_at_10: float | None
    recall_at_20: float | None
    reciprocal_rank: float | None
    ndcg_at_10: float | None
    top_cosine: float | None
    relevant_cosine: float | None


@dataclass(frozen=True)
class EvalCorpusRecord:
    """One `ready` source a run searched, as it stood when the run started."""

    url: str
    ref: str
    indexed_commit: str
    chunk_count: int


@dataclass(frozen=True)
class EvalSettingsRecord:
    """The `SEARCH` and `EMBEDDING` values a run was made with, so a later change to them does not
    rewrite what a stored run means."""

    embedding_model: str
    rrf_k: int
    candidates: int
    keyword_candidates: int
    trigram_threshold: float


@dataclass(frozen=True)
class EvalCosineRecord:
    """The evidence for a cosine cutoff: relevant hits against the best hit of a question the
    corpus cannot answer. Each is `None` when its group is empty."""

    relevant_min: float | None
    relevant_median: float | None
    no_answer_median: float | None
    no_answer_max: float | None


@dataclass(frozen=True)
class EvalRunRecord:
    """A run. Until it starts, `corpus` is empty and `settings` `None`; until it completes,
    `scores` and `case_results` are empty and `cosine` is `None`. A page of runs leaves
    `case_results` empty."""

    id: str
    status: EvalRunStatus
    error_code: EvalRunErrorCode | None
    case_count: int
    skipped_case_count: int
    incomplete_case_count: int
    scores: tuple[EvalScoreRecord, ...]
    case_results: tuple[EvalCaseResultRecord, ...]
    corpus: tuple[EvalCorpusRecord, ...]
    settings: EvalSettingsRecord | None
    cosine: EvalCosineRecord | None
    created_at: datetime
    updated_at: datetime
