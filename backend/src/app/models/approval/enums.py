"""enums.py belongs: the closed value sets of an approval.
It does not belong: limits (`constants.py`) or object shapes (`interface.py`).
"""

from enum import StrEnum


class ApprovalDecision(StrEnum):
    """What a person decided about a tool call; an undecided approval has none (null)."""

    approved = "approved"
    rejected = "rejected"
