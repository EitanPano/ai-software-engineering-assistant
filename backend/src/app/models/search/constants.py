"""constants.py belongs: the limits of a search request itself: how long the text may be and how
many hits one answer holds.
It does not belong: how the search behaves, such as its candidate caps and thresholds
(`config/constants.py`, `SEARCH`).
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class SearchLimits:
    # Counted in characters after trimming, not bytes.
    q_min: int
    q_max: int
    limit_min: int
    limit_max: int
    limit_default: int


SEARCH_LIMITS: Final = SearchLimits(q_min=1, q_max=500, limit_min=1, limit_max=20, limit_default=10)
