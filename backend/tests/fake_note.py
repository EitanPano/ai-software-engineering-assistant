"""`fixture`, a one-tool MCP server for the journeys that cross processes (`TestRealRestart`, the
e2e suite), where `services/mcp.py` `use_transport` cannot reach. It is served by the
`tests/fake_anthropic.py` process at `/mcp` (`python -m tests.fake_anthropic`), so a seventh e2e web
server is not needed, and it imports `services/mcp.py`, not `tests/fake_mcp.py`, which loads
`knowledge` and its store.

Its one tool, `note { text }`, answers `noted:<text>`. It runs without a token and checks the `Host`
header against the port it is reached by. `tests/seed_ask_tool.py` writes the `mcp_server` row and
the `ask` policy that make the agent offer it.
"""

from typing import Final

from app.models.mcp_server.type import ListedTool
from app.services.mcp import McpApp, build_app

SERVER_NAME: Final = "fixture"
TOOL_NAME: Final = "note"
NOTE_TOOL: Final = ListedTool(
    name=TOOL_NAME,
    description="Stores a short note and answers it back.",
    input_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
)


async def _call(name: str, arguments: dict[str, object], user_id: str | None) -> str:
    del name, user_id
    return f"noted:{arguments.get('text')}"


def create_note_app(port: int) -> McpApp:
    """The server, reachable as `127.0.0.1:<port>` or `localhost:<port>`."""
    return build_app(
        [NOTE_TOOL],
        _call,
        token=None,
        allowed_hosts=[f"127.0.0.1:{port}", f"localhost:{port}"],
    )
