"""The agent's tool seam: how a listed tool becomes a definition the model is offered, what the
model calls it, whether a policy lets a call run, and whether its input matches the tool's schema.

`decide` is the default-deny gate (`.doc/conventions.md`, Agent security): a call runs at once only
when its policy row says `allow`; `ask` waits for a person's approval, and no row or `deny` refuses.
The model's request never changes that; the browser never sees it. The policy is read at each call,
so a definition stored earlier never outranks it.

`arguments_digest` is what an approval binds to: the SHA-256 of the call's arguments, canonical so
the same value always gives the same digest.

Definitions are sorted by name and built the same way every time, so the tools part of the prompt
is byte-stable and the cache does not miss silently. A tool is offered as `<server>__<tool>`.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Final, Literal

from jsonschema import Draft202012Validator, SchemaError, ValidationError
from jsonschema.validators import validator_for
from referencing import Registry
from referencing.exceptions import Unresolvable

from app.models.mcp_server.constants import KNOWLEDGE_SERVER
from app.models.mcp_server.interface import McpServerRecord
from app.models.mcp_server.type import ListedTool, canonical, same_definition
from app.models.tool_policy.enums import PolicyEffect

type Decision = Literal["allow", "ask", "deny"]
type ToolDefinition = dict[str, object]

SEPARATOR: Final = "__"


class InvalidToolInput(ValueError):  # noqa: N818  # a value error that names what it is
    """The model's input does not match the tool's schema (or was cut short by the stream)."""


def decide(effect: PolicyEffect | None) -> Decision:
    """Deny unless a policy row says `allow` or `ask`."""
    match effect:
        case PolicyEffect.allow:
            return "allow"
        case PolicyEffect.ask:
            return "ask"
        case _:
            return "deny"


def arguments_digest(arguments: Mapping[str, object]) -> str:
    """The SHA-256 of the arguments as 64 lowercase hex characters, over their canonical JSON:
    sorted keys, no whitespace, characters as written. Compute it over the value read back from
    the store (JSONB), so what is bound is what is stored."""
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8", errors="surrogatepass")).hexdigest()


def model_name(server: str, tool_name: str) -> str:
    return f"{server}{SEPARATOR}{tool_name}"


def split_name(name: str) -> tuple[str, str] | None:
    """The server and tool a model's tool name stands for, or `None` for a name with no server."""
    server, separator, tool_name = name.partition(SEPARATOR)
    if separator == "" or server == "" or tool_name == "":
        return None
    return server, tool_name


def _definition(server: str, listed: ListedTool) -> ToolDefinition:
    definition: ToolDefinition = {
        "name": model_name(server, listed.name),
        "description": listed.description,
        # A copy: the definition is stored and sent, and must not alias a listing.
        "input_schema": _copy(listed.input_schema),
    }
    if server == KNOWLEDGE_SERVER:
        # `strict` needs `additionalProperties: false` on every object and refuses `minimum`,
        # `maximum` and `minLength`. We wrote `knowledge`'s schema to fit; a third party's does not,
        # and rewriting it would send what no admin accepted. `validate_input` checks every input
        # against the full schema either way.
        definition["strict"] = True
    definition["eager_input_streaming"] = True
    return definition


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


def pin_holds(server: McpServerRecord, tool_name: str, offered: Mapping[str, object]) -> bool:
    """Whether a call may run against what an admin accepted. `knowledge` is ours and is not pinned.
    Any other server needs the tool in its pin, and the last listing (if there is one) and the
    definition the conversation was offered must equal the pin by description and schema: a changed
    listing, a tool gone from it, or a conversation frozen before a re-pin all deny. A server never
    listed holds on the offer alone, because `call_tool` lists again in the call's own session."""
    if server.name == KNOWLEDGE_SERVER:
        return True
    pinned = next((t for t in server.pinned_tool_definition or [] if t.name == tool_name), None)
    if pinned is None:
        return False
    if canonical(pinned.name, offered.get("description"), offered.get("input_schema")) != canonical(
        pinned.name, pinned.description, pinned.input_schema
    ):
        return False
    if server.tool_definition is None:
        return True
    return any(t.name == pinned.name and same_definition(t, pinned) for t in server.tool_definition)


def listing_digest(tools: Sequence[ListedTool]) -> str:
    """The SHA-256 of a listing as 64 hex characters, canonical and sorted by name, so an admin can
    compare what they read with what is stored."""
    document = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in sorted(tools, key=lambda t: t.name)
    ]
    return arguments_digest({"tools": document})


def _shown(name: str) -> str:
    """A server-chosen name as JSON escapes it (no quotes): a control character becomes `\\x1b`
    text and cannot move an admin's cursor."""
    return json.dumps(name)[1:-1]


def listing_changes(pinned: Sequence[ListedTool] | None, live: Sequence[ListedTool]) -> list[str]:
    """What differs between the pin and the live listing, one line each: `added: x`, `removed: x`,
    `changed: x`, by tool name, in name order. Empty when they are equal."""
    before: dict[str, set[str]] = {}
    for t in pinned or []:
        before.setdefault(t.name, set()).add(canonical(t.name, t.description, t.input_schema))
    after: dict[str, set[str]] = {}
    for t in live:
        after.setdefault(t.name, set()).add(canonical(t.name, t.description, t.input_schema))
    # A name is rendered as JSON: a server chooses it, and a control character in it must not reach
    # an admin's terminal. A name listed twice differs from the pin unless every copy matches.
    lines = [f"added: {_shown(name)}" for name in sorted(after.keys() - before.keys())]
    lines += [f"removed: {_shown(name)}" for name in sorted(before.keys() - after.keys())]
    lines += [
        f"changed: {_shown(name)}"
        for name in sorted(before.keys() & after.keys())
        if before[name] != after[name]
    ]
    return lines


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
