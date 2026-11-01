"""enums.py belongs: the closed value sets of a tool policy.
It does not belong: limits (`constants.py`) or object shapes (`interface.py`).
"""

from enum import StrEnum


class PolicyEffect(StrEnum):
    """What the loop does with a call of a tool: `allow` runs it, `deny` refuses it, `ask` waits
    for an approval. Until the approval task lands `ask` is refused like `deny`."""

    allow = "allow"
    deny = "deny"
    ask = "ask"
