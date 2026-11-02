"""type.py belongs: the shapes the metrics pass between their steps: a span of lines at a commit, a
hit as the metrics read it, and the metrics of one case under one search.
It does not belong: the stored records (`interface.py`) or the wire shapes (`api/eval/schema.py`).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """Lines `start_line` to `end_line` (1-based, inclusive) of `path` in the source indexed at
    `commit`: an expected chunk, or where a hit lies."""

    commit: str
    path: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class RankedHit:
    """A hit as the metrics read it: where it lies, its rank in each of the three searches (`None`
    when that search did not return it) and its semantic cosine. No content."""

    span: Span
    semantic_rank: int | None
    full_text_rank: int | None
    trigram_rank: int | None
    cosine: float | None


@dataclass(frozen=True)
class CaseMetrics:
    """One answerable case under one ordering. `rank` is the 1-based position of the first
    relevant hit within the depth, `None` when there is none; the others are 0 to 1."""

    rank: int | None
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    reciprocal_rank: float
    ndcg_at_10: float
