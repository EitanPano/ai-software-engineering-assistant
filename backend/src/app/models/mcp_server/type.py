"""type.py belongs: shapes that several layers share and that are not stored records: a tool as a
server lists it, and what one run's discovery found.
It does not belong: the stored row (`interface.py`) or the wire (no route lists servers).
"""

import json
import math
from dataclasses import dataclass, field
from decimal import Decimal

from app.models.run.enums import ToolCallStatus


@dataclass(frozen=True)
class ListedTool:
    """One tool as an MCP server lists it: the name it knows, a description for the model and the
    JSON Schema of its input."""

    name: str
    description: str
    input_schema: dict[str, object]


def _as_jsonb_keeps_it(value: object) -> object:
    """The number forms JSONB rewrites are written as it returns them: a float from 1e16 up is an
    integer there, and `-0.0` is `0.0`. A `bool` is not a float, so `true` stays apart from `1`."""
    if isinstance(value, float) and math.isfinite(value):
        if abs(value) >= 1e16:
            return int(Decimal(repr(value)))
        return value + 0.0 if value == 0 else value
    if isinstance(value, list):
        return [_as_jsonb_keeps_it(item) for item in value]
    if isinstance(value, dict):
        return {key: _as_jsonb_keeps_it(item) for key, item in value.items()}
    return value


def canonical(name: str, description: object, input_schema: object) -> str:
    """A definition as canonical JSON, the form the digest uses. Python equality calls `0` equal
    to `false` and `1` to `1.0`; this does not, so a changed default or bound is a change. A number
    is first written the way JSONB returns it, so a stored pin equals the live tool it came from."""
    return json.dumps(
        {
            "name": name,
            "description": description,
            "input_schema": _as_jsonb_keeps_it(input_schema),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def same_definition(a: ListedTool, b: ListedTool) -> bool:
    """Whether two listed tools are one definition, by `canonical`."""
    return canonical(a.name, a.description, a.input_schema) == canonical(
        b.name, b.description, b.input_schema
    )


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
