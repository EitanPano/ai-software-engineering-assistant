"""enums.py belongs: the closed value sets of an MCP server's listing. On the wire the same sets are
`Literal[...]` aliases in `api/mcp_server/schema.py`.
It does not belong: open-ended strings, limits (`constants.py`) or shapes (`type.py`).
"""

from enum import StrEnum


class PinStatus(StrEnum):
    """Where a server's pin stands, read from stored rows with no call to the server.
    `not_required` is `knowledge`, which is ours and has none; `unpinned` is a third party with no
    pin; `current` is a stored last listing equal to the pin; `changed` is one that differs."""

    not_required = "not_required"
    unpinned = "unpinned"
    current = "current"
    changed = "changed"


class ToolChange(StrEnum):
    """What a live listing did to one tool against the pin."""

    added = "added"
    removed = "removed"
    changed = "changed"
    unchanged = "unchanged"
