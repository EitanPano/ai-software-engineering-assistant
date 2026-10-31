"""interface.py belongs: the records a search passes up: one chunk it returned, how many chunks
each of its three searches found, and the outcome the source module's rule hands the search
controller. Frozen dataclasses despite the name.
It does not belong: the wire shape (`api/search/schema.py`).

A rank is the chunk's position in one of the three searches, 1 is best, and `None` means that
search did not return it. `score` is the sum over the three of `1 / (rrf_k + rank)`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchHitRecord:
    chunk_id: str
    source_id: str
    url: str
    ref: str
    path: str
    symbol: str | None
    start_line: int
    end_line: int
    content: str
    score: float
    semantic_rank: int | None
    full_text_rank: int | None
    trigram_rank: int | None


@dataclass(frozen=True)
class SearchCounts:
    """How many chunks each of the three searches found: the semantic search up to its candidate
    cap, a keyword search among at most `keyword_candidates` matches."""

    semantic: int
    full_text: int
    trigram: int


@dataclass(frozen=True)
class SearchOutcome:
    """The best chunks, best first, and whether a limit cut the search short."""

    hits: list[SearchHitRecord]
    incomplete: bool
