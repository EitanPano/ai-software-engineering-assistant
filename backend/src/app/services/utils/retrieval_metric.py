"""Retrieval metrics, pure: relevance, recall@k, reciprocal rank and nDCG@k over a ranked list of
hits, the three orderings of one search's hits, and the means and medians that summarise cases.

Definitions (plan 009):
- A hit is relevant to an expected chunk when both lie in the same file at the same commit and
  share at least half of the shorter of the two line ranges.
- An expected chunk is found at the rank of its first relevant hit within the depth. A later hit
  on it adds nothing; one hit may find several expected chunks.
- recall@k is the share of expected chunks found at a rank within k.
- Reciprocal rank is 1 over the rank of the first relevant hit within the depth, else 0.
- DCG@k adds `1 / log2(rank + 1)` once for each distinct rank at which an expected chunk is found,
  within k; nDCG@k divides it by the DCG of `min(expected, k)` hits at ranks 1 to that many. The
  distinct ranks number at most `min(expected, k)`, so nDCG cannot pass 1.
"""

import math
from collections.abc import Sequence

from app.models.eval.enums import EvalSearch
from app.models.eval.type import CaseMetrics, RankedHit, Span


def is_relevant(hit: Span, expected: Span) -> bool:
    if hit.commit != expected.commit or hit.path != expected.path:
        return False
    shared = min(hit.end_line, expected.end_line) - max(hit.start_line, expected.start_line) + 1
    shorter = min(hit.end_line - hit.start_line, expected.end_line - expected.start_line) + 1
    # `shared / shorter >= 1/2` without a float: an odd range rounds its half up.
    return shared > 0 and shared * 2 >= shorter


def order_hits(hits: Sequence[RankedHit], search: EvalSearch, *, rrf_k: int) -> list[RankedHit]:
    """The hits as one search alone would order them. `hybrid` is the order returned; `semantic`
    keeps what the semantic search returned, by its rank; `keyword` keeps what either keyword
    search returned, by the RRF sum of their ranks alone, ties in the order returned."""
    match search:
        case EvalSearch.hybrid:
            return list(hits)
        case EvalSearch.semantic:
            ranked = [hit for hit in hits if hit.semantic_rank is not None]
            return sorted(ranked, key=lambda hit: hit.semantic_rank or 0)
        case EvalSearch.keyword:
            matched = [
                hit
                for hit in hits
                if hit.full_text_rank is not None or hit.trigram_rank is not None
            ]
            return sorted(matched, key=lambda hit: -_keyword_score(hit, rrf_k))


def _keyword_score(hit: RankedHit, rrf_k: int) -> float:
    return sum(
        1 / (rrf_k + rank) for rank in (hit.full_text_rank, hit.trigram_rank) if rank is not None
    )


def _first_ranks(ordered: Sequence[RankedHit], expected: Sequence[Span], depth: int) -> list[int]:
    """For each expected chunk with a relevant hit within `depth`, the 1-based rank of its first."""
    ranks: list[int] = []
    for label in expected:
        for position, hit in enumerate(ordered[:depth], start=1):
            if is_relevant(hit.span, label):
                ranks.append(position)
                break
    return ranks


def _dcg(ranks: Sequence[int], k: int) -> float:
    return sum(1 / math.log2(rank + 1) for rank in ranks if rank <= k)


def score_case(
    ordered: Sequence[RankedHit], expected: Sequence[Span], *, depth: int
) -> CaseMetrics:
    """The metrics of one answerable case over the first `depth` hits of `ordered`."""
    ranks = _first_ranks(ordered, expected, depth)
    gain_ranks = sorted(set(ranks))
    total = len(expected)
    ideal = _dcg(list(range(1, min(total, 10) + 1)), 10)
    first = _first_relevant_rank(ordered, expected, depth)
    return CaseMetrics(
        rank=first,
        recall_at_5=sum(rank <= 5 for rank in ranks) / total,
        recall_at_10=sum(rank <= 10 for rank in ranks) / total,
        recall_at_20=sum(rank <= 20 for rank in ranks) / total,
        reciprocal_rank=0.0 if first is None else 1 / first,
        ndcg_at_10=_dcg(gain_ranks, 10) / ideal,
    )


def _first_relevant_rank(
    ordered: Sequence[RankedHit], expected: Sequence[Span], depth: int
) -> int | None:
    for position, hit in enumerate(ordered[:depth], start=1):
        if any(is_relevant(hit.span, e) for e in expected):
            return position
    return None


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2
