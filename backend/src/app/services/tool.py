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
import re
from collections.abc import Mapping, Sequence
from typing import Final, Literal

from jsonschema import Draft202012Validator, SchemaError, ValidationError
from jsonschema.validators import validator_for
from referencing import Registry
from referencing.exceptions import Unresolvable

from app.models.mcp_server.constants import GITHUB_SERVER, KNOWLEDGE_SERVER
from app.models.mcp_server.enums import PinStatus, ToolChange
from app.models.mcp_server.interface import McpServerRecord
from app.models.mcp_server.type import ListedTool, canonical, same_definition
from app.models.tool_policy.constants import GITHUB_ALLOWABLE_TOOLS
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


def _forms(tools: Sequence[ListedTool] | None) -> dict[str, set[str]]:
    """Each name's definitions as canonical JSON: a name listed twice holds two."""
    forms: dict[str, set[str]] = {}
    for t in tools or []:
        forms.setdefault(t.name, set()).add(canonical(t.name, t.description, t.input_schema))
    return forms


def tool_changes(
    pinned: Sequence[ListedTool] | None, live: Sequence[ListedTool]
) -> dict[str, ToolChange]:
    """What the live listing did to each tool, by name: every name of either side. A name listed
    twice is `changed` unless every copy matches the pin. The one comparison under both
    `listing_changes` (the command) and the review screen."""
    before, after = _forms(pinned), _forms(live)
    changes: dict[str, ToolChange] = {}
    for name in sorted(before.keys() | after.keys()):
        if name not in before:
            changes[name] = ToolChange.added
        elif name not in after:
            changes[name] = ToolChange.removed
        elif before[name] != after[name]:
            changes[name] = ToolChange.changed
        else:
            changes[name] = ToolChange.unchanged
    return changes


def listing_changes(pinned: Sequence[ListedTool] | None, live: Sequence[ListedTool]) -> list[str]:
    """What differs between the pin and the live listing, one line each: `added: x`, `removed: x`,
    `changed: x`, by tool name, in name order. Empty when they are equal."""
    changes = tool_changes(pinned, live)
    # A name is rendered as JSON: a server chooses it, and a control character in it must not reach
    # an admin's terminal.
    return [
        f"{kind}: {_shown(name)}"
        for kind in (ToolChange.added, ToolChange.removed, ToolChange.changed)
        for name, change in changes.items()
        if change is kind
    ]


def pin_status(server: McpServerRecord) -> PinStatus:
    """Where the server's pin stands, from stored rows alone (no call to any server): `knowledge`
    is ours and needs none; a third party with no pin is `unpinned`; otherwise `changed` when the
    last listing differs from the pin (by `canonical`, so `0` and `false` differ) and `current`
    when it does not, or when there is no last listing yet."""
    if server.name == KNOWLEDGE_SERVER:
        return PinStatus.not_required
    if server.pinned_tool_definition is None:
        return PinStatus.unpinned
    if server.tool_definition is None:
        return PinStatus.current
    if listing_changes(server.pinned_tool_definition, server.tool_definition):
        return PinStatus.changed
    return PinStatus.current


def printed_schema(schema: object) -> str:
    """A definition's schema as the review screen shows it: `sort_keys`, two-space indent, the
    characters as written. Printed here and sent as a string: `canonical` calls `1` and `1.0`
    different and a browser's `JSON.parse` would print them alike and round past 2^53."""
    return json.dumps(schema, sort_keys=True, indent=2, ensure_ascii=False)


TOOL_NAME: Final = re.compile(r"[A-Za-z0-9_-]+")


def listing_problem(tools: Sequence[ListedTool]) -> str | None:
    """Why a listing cannot be accepted, or `None`: no tool, a name listed twice, or a name outside
    `[A-Za-z0-9_-]+` (the API refuses such a name, which would fail every new conversation, and a
    name could carry terminal escapes). The text names no tool: it is the server's. One rule for
    the review, the accept and the command."""
    names = [t.name for t in tools]
    if not names:
        return "the server lists no tool"
    if len(set(names)) != len(names) or not all(TOOL_NAME.fullmatch(n) for n in names):
        return "the listing has a tool name that is repeated or not [A-Za-z0-9_-]+"
    return None


def effects_for(server_name: str, tool_name: str) -> list[PolicyEffect]:
    """The effects an admin may set for a tool. On `github` only the five reads may be `allow`
    (`GITHUB_ALLOWABLE_TOOLS`): anything the agent changes there needs an approval, a tool it has
    never seen included. Another server has no cap."""
    if server_name == GITHUB_SERVER and tool_name not in GITHUB_ALLOWABLE_TOOLS:
        return [PolicyEffect.ask, PolicyEffect.deny]
    return [PolicyEffect.allow, PolicyEffect.ask, PolicyEffect.deny]


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
