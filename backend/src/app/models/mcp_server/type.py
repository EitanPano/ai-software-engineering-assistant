"""type.py belongs: shapes that several layers share and that are not stored records: a tool as a
server lists it, and what one run's discovery found.
It does not belong: the stored row (`interface.py`) or the wire (no route lists servers).
"""

from dataclasses import dataclass, field

from app.models.run.enums import ToolCallStatus


@dataclass(frozen=True)
class ListedTool:
    """One tool as an MCP server lists it: the name it knows, a description for the model and the
    JSON Schema of its input."""

    name: str
    description: str
    input_schema: dict[str, object]


@dataclass(frozen=True)
class ToolOutcome:
    """What one call came to: `succeeded` with the server's text, or `failed` with the server's own
    error text (a fixed code on `knowledge`) or a fixed message when it could not be reached."""

    status: ToolCallStatus
    output: str


@dataclass(frozen=True)
class Discovery:
    """What a run found: the tools to offer, each with the name of the server it came from, and
    the names of the servers that did not answer (their last good listing is used, if any)."""

    listings: dict[str, list[ListedTool]] = field(default_factory=dict)
    unavailable: list[str] = field(default_factory=list)
