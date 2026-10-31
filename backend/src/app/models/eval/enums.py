"""enums.py belongs: the closed value sets of an eval: where a run stands, why one failed, the kinds
of case, why a case was skipped, and the searches and groupings a score is reported for.
It does not belong: limits (`constants.py`) or object shapes (`interface.py`).
"""

from enum import StrEnum


class EvalRunStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class EvalRunErrorCode(StrEnum):
    no_runnable_case = "no_runnable_case"
    search_unavailable = "search_unavailable"
    interrupted = "interrupted"
    internal = "internal"


class EvalCaseKind(StrEnum):
    identifier = "identifier"
    paraphrase = "paraphrase"
    no_answer = "no_answer"


class EvalSkipReason(StrEnum):
    source_missing = "source_missing"
    expected_chunk_missing = "expected_chunk_missing"


class EvalSearch(StrEnum):
    """The ordering a score is computed over: `hybrid` is the order returned, `semantic` orders by
    `semantic_rank`, `keyword` by the RRF sum of the full-text and trigram ranks alone."""

    hybrid = "hybrid"
    semantic = "semantic"
    keyword = "keyword"


class EvalScoreKind(StrEnum):
    """The cases a score averages: all answerable cases, or one kind of them."""

    all = "all"
    identifier = "identifier"
    paraphrase = "paraphrase"
