"""constants.py belongs: limits of the eval data itself: the form of a pinned commit.
It does not belong: policy such as how many hits a run asks for (`config/constants.py`, `EVAL`).
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class EvalLimits:
    # A full commit id, lowercase, as `source.indexed_commit` stores it. Spelled out for
    # pydantic's regex engine.
    commit_pattern: str
    commit_length: int
    path_max: int


EVAL_LIMITS: Final = EvalLimits(commit_pattern=r"^[0-9a-f]{40}$", commit_length=40, path_max=1024)
