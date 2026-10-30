"""The agent's tool seam: definitions the model is offered, and the decision whether a call may run.

`decide` is the default-deny gate (`.doc/conventions.md`, Agent security): a tool runs only when
it was registered, and the registry is empty in production until the policy task adds a source for
it. The model's request never changes that; the browser never sees it. A test registers a tool,
runs, and clears the registry.

Definitions are sorted by name and built the same way every time, so the tools part of the prompt
is byte-stable and the cache does not miss silently.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

type ToolHandler = Callable[[dict[str, object]], Awaitable[str]]
type Decision = Literal["allow", "deny"]
type ToolDefinition = dict[str, object]


class ToolInput(BaseModel):
    """Base of a tool's input model: unknown fields are refused, which is also the schema's
    `additionalProperties: false` that `strict` tool use needs."""

    model_config = ConfigDict(extra="forbid")


class InvalidToolInput(ValueError):  # noqa: N818  # a value error that names what it is
    """The model's input does not match the tool's schema (or was cut short by the stream)."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[ToolInput]
    run: ToolHandler


_REGISTRY: Final[dict[str, Tool]] = {}


def register_tool(tool: Tool) -> None:
    """Allows `tool`: from now on `decide` answers allow for its name."""
    _REGISTRY[tool.name] = tool


def clear_tools() -> None:
    _REGISTRY.clear()


def decide(name: str) -> Decision:
    """Deny unless the name was registered."""
    return "allow" if name in _REGISTRY else "deny"


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def definitions() -> list[ToolDefinition]:
    """What the model is offered, sorted by name. `eager_input_streaming` lets large inputs stream,
    so every input is validated (`validate_input`) before it runs."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_model.model_json_schema(),
            "strict": True,
            "eager_input_streaming": True,
        }
        for tool in sorted(_REGISTRY.values(), key=lambda registered: registered.name)
    ]


def validate_input(tool: Tool, raw: dict[str, object]) -> dict[str, object]:
    """The input as the tool's model parses it, or `InvalidToolInput`; the message names the
    failing fields and never echoes values."""
    try:
        return tool.input_model.model_validate(raw).model_dump()
    except ValidationError as error:
        fields = ", ".join(
            ".".join(str(step) for step in issue["loc"]) or "input" for issue in error.errors()
        )
        raise InvalidToolInput(f"invalid input: {fields}") from None
