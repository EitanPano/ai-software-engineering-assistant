"""The agent's tool seam: how a listed tool becomes a definition the model is offered, what the
model calls it, whether a policy lets a call run, and whether its input matches the tool's schema.

`decide` is the default-deny gate (`.doc/conventions.md`, Agent security): a call runs only when its
policy row says `allow`, so no row, `deny` and `ask` (which waits for an approval no task has built
yet) all refuse. The model's request never changes that; the browser never sees it. The policy is
read at each call, so a definition stored earlier never outranks it.

Definitions are sorted by name and built the same way every time, so the tools part of the prompt
is byte-stable and the cache does not miss silently. A tool is offered as `<server>__<tool>`.
"""

from collections.abc import Mapping, Sequence
from typing import Final, Literal

from jsonschema import Draft202012Validator, SchemaError, ValidationError
from jsonschema.validators import validator_for
from referencing import Registry
from referencing.exceptions import Unresolvable

from app.models.mcp_server.type import ListedTool
from app.models.tool_policy.enums import PolicyEffect

type Decision = Literal["allow", "deny"]
type ToolDefinition = dict[str, object]

SEPARATOR: Final = "__"


class InvalidToolInput(ValueError):  # noqa: N818  # a value error that names what it is
    """The model's input does not match the tool's schema (or was cut short by the stream)."""


def decide(effect: PolicyEffect | None) -> Decision:
    """Deny unless a policy row says `allow`."""
    return "allow" if effect is PolicyEffect.allow else "deny"


def model_name(server: str, tool_name: str) -> str:
    return f"{server}{SEPARATOR}{tool_name}"


def split_name(name: str) -> tuple[str, str] | None:
    """The server and tool a model's tool name stands for, or `None` for a name with no server."""
    server, separator, tool_name = name.partition(SEPARATOR)
    if separator == "" or server == "" or tool_name == "":
        return None
    return server, tool_name


def _definition(server: str, listed: ListedTool) -> ToolDefinition:
    return {
        "name": model_name(server, listed.name),
        "description": listed.description,
        # A copy: the definition is stored and sent, and must not alias a listing.
        "input_schema": _copy(listed.input_schema),
        "strict": True,
        "eager_input_streaming": True,
    }


def _copy(value: dict[str, object]) -> dict[str, object]:
    copied: dict[str, object] = {}
    for key, item in value.items():
        copied[key] = _copy(item) if isinstance(item, dict) else item
    return copied


def definitions(listings: Mapping[str, Sequence[ListedTool]]) -> list[ToolDefinition]:
    """What the model is offered, sorted by name. `eager_input_streaming` lets large inputs stream,
    so every input is validated (`validate_input`) before it runs."""
    offered = [
        _definition(server, listed) for server, tools in listings.items() for listed in tools
    ]
    return sorted(offered, key=lambda definition: str(definition["name"]))


def _field(error: ValidationError, schema_keys: set[str], given: set[str]) -> list[str]:
    path = ".".join(str(step) for step in error.absolute_path)
    if error.validator == "required" and not error.absolute_path:
        required = error.validator_value
        names = (
            [name for name in required if name not in given] if isinstance(required, list) else []
        )
        return [str(name) for name in names] or ["input"]
    if error.validator == "additionalProperties" and not error.absolute_path:
        return sorted(given - schema_keys) or ["input"]
    return [path or "input"]


def validate_input(schema: Mapping[str, object], raw: dict[str, object]) -> dict[str, object]:
    """The input when it matches `schema`, or `InvalidToolInput`; the message names the failing
    fields and never echoes values."""
    try:
        validator_class = validator_for(dict(schema), default=Draft202012Validator)
        validator_class.check_schema(dict(schema))
        # An empty registry: a `$ref` to another document is unresolvable, never fetched (the
        # default registry would request a remote URL a third-party listing names).
        validator = validator_class(dict(schema), registry=Registry())
        errors: list[ValidationError] = sorted(
            validator.iter_errors(raw),
            key=lambda error: [str(step) for step in error.absolute_path],
        )
    except SchemaError, Unresolvable:
        # A listing the client cannot read is no listing: refuse the call, name nothing.
        raise InvalidToolInput("invalid input: input") from None
    if not errors:
        return raw
    properties = schema.get("properties")
    schema_keys = set(properties) if isinstance(properties, dict) else set()
    fields: list[str] = []
    for error in errors:
        for name in _field(error, {str(key) for key in schema_keys}, set(raw)):
            if name not in fields:
                fields.append(name)
    raise InvalidToolInput(f"invalid input: {', '.join(fields)}")
