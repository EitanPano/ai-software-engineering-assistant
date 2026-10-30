"""type.py belongs: shapes that several layers share and that are neither stored records nor wire
models.
It does not belong: the stored records (`interface.py`) or value sets (`enums.py`).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class HistoryTurn:
    """One API turn, ready to send: `role` is `user` or `assistant` (a `tool_result` message is a
    user turn), `content` the stored blocks."""

    role: str
    content: list[object]


@dataclass(frozen=True)
class NewTurn:
    """A turn to append: the role and its blocks, with the text the wire shows."""

    role: str
    blocks: list[object]
    text: str
