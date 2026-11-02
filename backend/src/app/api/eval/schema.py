"""schema.py belongs: this directory's contract, the pydantic models that validate requests, type
responses and produce `openapi.json`, and the model of the seed command's case file. The leaf of
the directory: routes and controller import it.
It does not belong: business rules or HTTP handling (`controller.py`) or data access
(`service.py`).
"""

from typing import Annotated, Literal

from fastapi import Path
from pydantic import Field, StringConstraints, field_validator, model_validator

from app.api.search.schema import SearchText
from app.config.constants import EVAL
from app.models.eval.constants import EVAL_LIMITS
from app.services.utils.api_model import RequestModel, ResponseModel, Timestamp
from app.services.utils.pagination import Page

# The wire's forms of `models/eval/enums.py`, inlined in the contract.
type EvalRunStatusName = Literal["queued", "running", "completed", "failed"]
type EvalRunErrorCodeName = Literal[
    "no_runnable_case", "search_unavailable", "interrupted", "internal"
]
type EvalCaseKindName = Literal["identifier", "paraphrase", "no_answer"]
type EvalSkipReasonName = Literal["source_missing", "expected_chunk_missing"]
type EvalSearchName = Literal["hybrid", "semantic", "keyword"]
type EvalScoreKindName = Literal["all", "identifier", "paraphrase"]

# A plain assignment, not a `type` statement: FastAPI reads the `Path` metadata off the annotation.
EvalRunId = Annotated[str, Path(alias="id", min_length=1)]

type Mean = Annotated[float, Field(ge=0, le=1)]


class EvalScore(ResponseModel):
    """The mean of each metric over the scored cases of one search and one kind."""

    search: EvalSearchName
    kind: EvalScoreKindName
    case_count: int
    recall_at_5: Mean
    recall_at_10: Mean
    recall_at_20: Mean
    mrr: Mean
    ndcg_at_10: Mean


class EvalCaseResult(ResponseModel):
    """One case under `hybrid`. The eight metrics are null for a skipped case; a `no_answer` case
    has only `top_cosine`."""

    question: str
    kind: EvalCaseKindName
    skip_reason: EvalSkipReasonName | None
    incomplete: bool
    rank: int | None
    recall_at_5: Mean | None
    recall_at_10: Mean | None
    recall_at_20: Mean | None
    reciprocal_rank: Mean | None
    ndcg_at_10: Mean | None
    top_cosine: float | None
    relevant_cosine: float | None


class EvalRun(ResponseModel):
    """`headline` is the `hybrid` `all` row."""

    id: str
    status: EvalRunStatusName
    error_code: EvalRunErrorCodeName | None
    case_count: int
    skipped_case_count: int
    incomplete_case_count: int
    headline: EvalScore | None
    created_at: Timestamp
    updated_at: Timestamp


class EvalCorpus(ResponseModel):
    url: str
    ref: str
    indexed_commit: str
    chunk_count: int


class EvalRunSettings(ResponseModel):
    embedding_model: str
    rrf_k: int
    candidates: int
    keyword_candidates: int
    trigram_threshold: float


class EvalCosine(ResponseModel):
    relevant_min: float | None
    relevant_median: float | None
    no_answer_median: float | None
    no_answer_max: float | None


class EvalRunDetail(EvalRun):
    """`corpus` is empty and `settings` null until a run starts; until it completes, `scores` and
    `cases` are empty and `cosine` is null."""

    scores: list[EvalScore]
    cases: list[EvalCaseResult]
    corpus: list[EvalCorpus]
    settings: EvalRunSettings | None
    cosine: EvalCosine | None


class EvalRunPage(Page[EvalRun]):
    """The list endpoint's page; the concrete name is the contract component."""


class EvalExpectedChunk(RequestModel):
    """Lines `startLine` to `endLine` (1-based, inclusive) of `path` at the file's pinned commit."""

    path: Annotated[str, StringConstraints(min_length=1, max_length=EVAL_LIMITS.path_max)]
    start_line: Annotated[int, Field(ge=1)]
    end_line: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def _lines_are_ordered(self) -> EvalExpectedChunk:
        if self.end_line < self.start_line:
            raise ValueError("endLine must not precede startLine")
        return self


class EvalCaseEntry(RequestModel):
    """A `no_answer` case holds no expected chunk; any other kind holds at least one. The question
    is held to what a search text is, because `search_knowledge_base` requires it of a caller."""

    kind: EvalCaseKindName
    question: SearchText
    expected_chunks: list[EvalExpectedChunk]

    @field_validator("question")
    @classmethod
    def _has_no_nul(cls, question: str) -> str:
        if "\x00" in question:
            raise ValueError("must not contain NUL")
        return question

    @model_validator(mode="after")
    def _chunks_match_the_kind(self) -> EvalCaseEntry:
        if self.kind == "no_answer" and self.expected_chunks:
            raise ValueError("a no_answer case holds no expected chunk")
        if self.kind != "no_answer" and not self.expected_chunks:
            raise ValueError("an answerable case holds at least one expected chunk")
        return self


class EvalCaseFile(RequestModel):
    """The seed command's file: the cases of one pinned commit, at most `EVAL.max_cases`."""

    pinned_commit: Annotated[
        str,
        StringConstraints(
            pattern=EVAL_LIMITS.commit_pattern,
            min_length=EVAL_LIMITS.commit_length,
            max_length=EVAL_LIMITS.commit_length,
        ),
    ]
    cases: Annotated[list[EvalCaseEntry], Field(min_length=1, max_length=EVAL.max_cases)]

    @field_validator("cases")
    @classmethod
    def _questions_are_distinct(cls, cases: list[EvalCaseEntry]) -> list[EvalCaseEntry]:
        questions = [entry.question for entry in cases]
        if len(set(questions)) != len(questions):
            raise ValueError("a question appears once in a file")
        return cases
