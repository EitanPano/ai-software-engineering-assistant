"""enums.py belongs: the closed value sets of a conversation. `tool_result` turns are stored as
user-role API turns and never shown, so the wire's role is only `user` or `assistant`
(`api/conversation/schema.py`).
It does not belong: limits (`constants.py`) or object shapes (`interface.py`).
"""

from enum import StrEnum


class MessageRole(StrEnum):
    user = "user"
    assistant = "assistant"
    tool_result = "tool_result"
