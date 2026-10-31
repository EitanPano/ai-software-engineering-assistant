"""The retrieval metrics against values worked by hand. Every number below is derived in the test
from the definitions in plan 009's Contract, never read back from the code under test."""

import math

import pytest

from app.models.eval.enums import EvalSearch
from app.models.eval.type import RankedHit, Span
from app.services.utils.retrieval_metric import (
    is_relevant,
    mean,
    median,
    order_hits,
    score_case,
)

COMMIT = "a" * 40
OTHER = "b" * 40
PATH = "src/click/core.py"


def span(start: int, end: int, *, path: str = PATH, commit: str = COMMIT) -> Span:
    return Span(commit=commit, path=path, start_line=start, end_line=end)


def hit(
    start: int,
    end: int,
    *,
    semantic: int | None = None,
    full_text: int | None = None,
    trigram: int | None = None,
    cosine: float | None = None,
    path: str = PATH,
    commit: str = COMMIT,
) -> RankedHit:
    return RankedHit(
        span=span(start, end, path=path, commit=commit),
        semantic_rank=semantic,
        full_text_rank=full_text,
        trigram_rank=trigram,
        cosine=cosine,
    )


def elsewhere(n: int) -> RankedHit:
    """A hit that is relevant to nothing in these tests (a file nothing expects)."""
    return hit(1, 10, path=f"src/click/other_{n}.py")


class TestRelevance:
    def test_half_the_shorter_range_is_relevant_and_one_line_less_is_not(self) -> None:
        expected = span(1, 10)  # shorter range of 10 lines: half is 5
        assert is_relevant(span(6, 20), expected)  # shares lines 6..10 = 5
        assert not is_relevant(span(7, 20), expected)  # shares 4

    def test_the_shorter_of_the_two_ranges_sets_the_bar(self) -> None:
        # A 100-line chunk around a 10-line label: the label is the shorter range.
        assert is_relevant(span(1, 100), span(48, 57))
        # The label is longer than the hit: the hit's 4 lines are the shorter range, half is 2.
        assert is_relevant(span(10, 13), span(12, 40))
        assert not is_relevant(span(10, 13), span(13, 40))

    def test_an_odd_shorter_range_rounds_the_half_up(self) -> None:
        expected = span(1, 5)  # half of 5 lines is 2.5, so 3 lines must be shared
        assert is_relevant(span(3, 9), expected)
        assert not is_relevant(span(4, 9), expected)

    def test_another_path_or_another_commit_is_never_relevant(self) -> None:
        expected = span(1, 10)
        assert not is_relevant(span(1, 10, path="src/click/types.py"), expected)
        assert not is_relevant(span(1, 10, commit=OTHER), expected)

    def test_disjoint_ranges_are_not_relevant(self) -> None:
        assert not is_relevant(span(20, 30), span(1, 10))


class TestOrdering:
    HITS = (  # the order the hybrid search returned
        hit(1, 5, semantic=3, full_text=1),
        hit(11, 15, semantic=1),
        hit(21, 25, trigram=1),
        hit(31, 35, semantic=2, trigram=2),
    )

    def test_hybrid_is_the_order_returned(self) -> None:
        assert order_hits(self.HITS, EvalSearch.hybrid, rrf_k=60) == list(self.HITS)

    def test_semantic_orders_by_its_own_rank_and_drops_what_it_did_not_return(self) -> None:
        ordered = order_hits(self.HITS, EvalSearch.semantic, rrf_k=60)

        assert [h.span.start_line for h in ordered] == [11, 31, 1]

    def test_keyword_orders_by_the_rrf_sum_of_full_text_and_trigram_alone(self) -> None:
        # k = 60: 1/61 for full text 1; 1/61 for trigram 1; 1/62 for trigram 2.
        # The semantic rank counts for nothing, and a hit with neither rank is dropped.
        ordered = order_hits(self.HITS, EvalSearch.keyword, rrf_k=60)

        assert [h.span.start_line for h in ordered] == [1, 21, 31]

    def test_keyword_ties_keep_the_order_returned(self) -> None:
        ordered = order_hits(self.HITS, EvalSearch.keyword, rrf_k=60)

        assert ordered[0].span.start_line == 1  # 1/61, returned before the other 1/61
        assert ordered[1].span.start_line == 21

    def test_a_hit_in_both_keyword_searches_beats_one_in_a_single_first_place(self) -> None:
        hits = (hit(1, 5, full_text=1), hit(11, 15, full_text=2, trigram=2))

        ordered = order_hits(hits, EvalSearch.keyword, rrf_k=60)

        # 1/62 + 1/62 = 0.03226 beats 1/61 = 0.01639
        assert [h.span.start_line for h in ordered] == [11, 1]


class TestScoreCase:
    def test_a_hit_on_the_first_rank_scores_one_everywhere(self) -> None:
        metrics = score_case([hit(1, 10)], [span(1, 10)], depth=20)

        assert metrics.rank == 1
        assert (metrics.recall_at_5, metrics.recall_at_10, metrics.recall_at_20) == (1, 1, 1)
        assert metrics.reciprocal_rank == 1
        assert metrics.ndcg_at_10 == pytest.approx(1.0)

    def test_nothing_relevant_is_zero_and_has_no_rank(self) -> None:
        metrics = score_case([elsewhere(n) for n in range(5)], [span(1, 10)], depth=20)

        assert metrics.rank is None
        assert (metrics.recall_at_5, metrics.recall_at_10, metrics.recall_at_20) == (0, 0, 0)
        assert metrics.reciprocal_rank == 0
        assert metrics.ndcg_at_10 == 0

    def test_an_empty_search_scores_zero(self) -> None:
        metrics = score_case([], [span(1, 10)], depth=20)

        assert metrics.rank is None
        assert metrics.recall_at_20 == 0

    def test_recall_is_the_share_of_expected_chunks_with_a_relevant_hit(self) -> None:
        # Expected a (lines 1-10) and b (lines 101-110); a is found at rank 2, b at rank 7.
        ordered = [elsewhere(0), hit(1, 10), *(elsewhere(n) for n in range(1, 5)), hit(101, 110)]
        metrics = score_case(ordered, [span(1, 10), span(101, 110)], depth=20)

        assert metrics.recall_at_5 == 0.5  # only a is within 5
        assert metrics.recall_at_10 == 1.0
        assert metrics.recall_at_20 == 1.0
        assert metrics.rank == 2
        assert metrics.reciprocal_rank == 0.5

    def test_ndcg_adds_a_discounted_gain_at_the_first_hit_of_each_expected_chunk(self) -> None:
        ordered = [elsewhere(0), hit(1, 10), *(elsewhere(n) for n in range(1, 5)), hit(101, 110)]
        metrics = score_case(ordered, [span(1, 10), span(101, 110)], depth=20)

        dcg = 1 / math.log2(2 + 1) + 1 / math.log2(7 + 1)
        ideal = 1 / math.log2(1 + 1) + 1 / math.log2(2 + 1)  # both found at ranks 1 and 2
        assert metrics.ndcg_at_10 == pytest.approx(dcg / ideal)

    def test_an_expected_chunk_two_hits_match_counts_once(self) -> None:
        # Two overlapping hits (ranks 1 and 2) both match the one expected chunk.
        metrics = score_case([hit(1, 10), hit(3, 12)], [span(1, 10)], depth=20)

        assert metrics.recall_at_5 == 1.0  # not 2.0
        assert metrics.ndcg_at_10 == pytest.approx(1.0)  # one gain at rank 1, ideal is one gain

    def test_one_hit_on_two_labels_finds_both_and_gains_once_so_ndcg_never_passes_one(self) -> None:
        metrics = score_case([hit(1, 20)], [span(1, 10), span(11, 20)], depth=20)

        assert metrics.recall_at_5 == 1.0
        assert metrics.ndcg_at_10 <= 1.0
        assert metrics.ndcg_at_10 == pytest.approx(1 / (1 / math.log2(2) + 1 / math.log2(3)))

    def test_recall_does_not_depend_on_which_hit_a_greedy_pass_would_give_which_label(self) -> None:
        # Rank 1 lies on both labels, rank 2 on the first alone: both labels are found at rank 1.
        metrics = score_case([hit(1, 20), hit(1, 10)], [span(1, 10), span(11, 20)], depth=20)

        assert metrics.recall_at_5 == 1.0
        assert metrics.ndcg_at_10 <= 1.0

    def test_ndcg_ideal_holds_at_most_k_gains(self) -> None:
        # Twelve expected chunks found at ranks 1 to 12: @10 sees ten gains of an ideal ten.
        expected = [span(100 * n + 1, 100 * n + 10) for n in range(12)]
        ordered = [hit(100 * n + 1, 100 * n + 10) for n in range(12)]

        metrics = score_case(ordered, expected, depth=20)

        assert metrics.ndcg_at_10 == pytest.approx(1.0)
        assert metrics.recall_at_10 == pytest.approx(10 / 12)
        assert metrics.recall_at_20 == 1.0

    def test_only_the_first_depth_hits_count(self) -> None:
        ordered = [*(elsewhere(n) for n in range(20)), hit(1, 10)]  # relevant at rank 21

        metrics = score_case(ordered, [span(1, 10)], depth=20)

        assert metrics.rank is None
        assert metrics.recall_at_20 == 0
        assert metrics.reciprocal_rank == 0

    def test_a_hit_at_rank_twenty_counts_for_recall_20_only(self) -> None:
        ordered = [*(elsewhere(n) for n in range(19)), hit(1, 10)]

        metrics = score_case(ordered, [span(1, 10)], depth=20)

        assert (metrics.recall_at_5, metrics.recall_at_10, metrics.recall_at_20) == (0, 0, 1)
        assert metrics.rank == 20
        assert metrics.reciprocal_rank == pytest.approx(1 / 20)
        assert metrics.ndcg_at_10 == 0  # the gain is past rank 10


class TestMeanAndMedian:
    def test_the_mean_of_nothing_is_none(self) -> None:
        assert mean([]) is None
        assert median([]) is None

    def test_the_mean(self) -> None:
        assert mean([1.0, 0.0, 0.5]) == pytest.approx(0.5)

    def test_the_median_of_an_odd_and_an_even_count(self) -> None:
        assert median([0.9, 0.1, 0.5]) == 0.5
        assert median([0.1, 0.2, 0.4, 0.9]) == pytest.approx(0.3)
