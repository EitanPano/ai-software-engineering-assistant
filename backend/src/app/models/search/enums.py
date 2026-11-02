"""enums.py belongs: the closed value sets of a search. A failure of the `knowledge` server's tool
is one of these fixed codes, never exception text.
It does not belong: limits (`constants.py`) or object shapes (`interface.py`).
"""

from enum import StrEnum


class ToolSearchCode(StrEnum):
    invalid_query = "invalid_query"
    busy = "busy"
    search_unavailable = "search_unavailable"
