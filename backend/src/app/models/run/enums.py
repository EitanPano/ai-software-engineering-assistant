"""enums.py belongs: the closed value sets of a run and its events, each a `StrEnum`. On the wire
the same sets are `Literal[...]` aliases in `api/run/schema.py`.
It does not belong: limits (`constants.py`) or object shapes (`interface.py`).
"""

from enum import StrEnum


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class RunErrorCode(StrEnum):
    refused = "refused"
    truncated = "truncated"
    turn_limit = "turn_limit"
    upstream_unavailable = "upstream_unavailable"
    interrupted = "interrupted"
    internal = "internal"


class RunEventType(StrEnum):
    run_started = "run_started"
    text_delta = "text_delta"
    tool_call_started = "tool_call_started"
    tool_call_finished = "tool_call_finished"
    mcp_server_unavailable = "mcp_server_unavailable"
    run_finished = "run_finished"


class ToolCallStatus(StrEnum):
    succeeded = "succeeded"
    failed = "failed"
    denied = "denied"
