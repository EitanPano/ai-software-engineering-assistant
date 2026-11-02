"""enums.py belongs: the closed value sets of memory. A failure of the `knowledge` server's `recall`
tool is one of these fixed codes, never exception text.
It does not belong: limits (`config/constants.py`, `MEMORY`) or object shapes (`interface.py`).
"""

from enum import StrEnum


class ToolRecallCode(StrEnum):
    invalid_query = "invalid_query"
    no_caller = "no_caller"
    busy = "busy"
    recall_unavailable = "recall_unavailable"
