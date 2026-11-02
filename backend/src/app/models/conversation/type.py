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
class ConversationPrefix:
    """What every request of a conversation starts with, frozen at its first run: a thinking block
    is bound to `system`, `tools` and every earlier message, so a byte of change is a 400. The
    tools are full definitions, as sent."""

    system_prompt: str
    tool_definition: list[dict[str, object]]


@dataclass(frozen=True)
class NewTurn:
    """A turn to append: the role and its blocks, with the text the wire shows."""

    role: str
    blocks: list[object]
    text: str
