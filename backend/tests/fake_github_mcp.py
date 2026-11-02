"""A scripted `github-mcp-server`: the seven tools of `github_tools.json`, recorded from the image's
tag (`v2.0.3`), served by the SDK through `services/mcp.py` `build_app`, so the real transport runs
against it: stateless Streamable HTTP, a bearer check before the SDK, and the SDK's own
`Mcp-Param-*` header validation for a tool whose schema carries `x-mcp-header` (a call that was not
listed first, or whose headers are missing, is refused with a 400).

It stands in for the real server in three places: in process behind `tests/fake_mcp.py`, at
`/github/mcp` in the `tests/fake_anthropic.py` process for e2e, and behind the gateway in
`tests/test_github_gateway.py`. It returns `get_file_contents` the way the real server does: a line
that says the download succeeded, then the file as an embedded resource.

The scripted tools are not the real ones: an `issue_write` and an `add_issue_comment` write nothing
anywhere, they answer a made-up id. `tests/live_github.py` is what meets the real server.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from app.models.mcp_server.type import ListedTool
from app.services.mcp import EmbeddedFile, McpApp, ToolFailure, ToolReply, build_app

TOOLS_FILE: Final = Path(__file__).with_name("github_tools.json")
# The bearer both sides share in an e2e run, where the fake runs in a process of its own and reads
# `GITHUB_MCP_TOKEN` when the web server sets it. A placeholder, refused in production.
E2E_TOKEN: Final = "dev-only-github-mcp-token-not-real-0123456789"
FILE_TEXT: Final = "# hello-world\n\nThe repository's README, read through the scripted server.\n"
BLOB_PATH: Final = "logo.png"


def recorded_tools() -> list[ListedTool]:
    """The seven definitions recorded from the tag, as a listing returns them."""
    entries = json.loads(TOOLS_FILE.read_text(encoding="utf-8"))
    return [
        ListedTool(
            name=str(entry["name"]),
            description=str(entry["description"]),
            input_schema=dict(entry["input_schema"]),
        )
        for entry in entries
    ]


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


@dataclass
class Github:
    """The tools the server lists (a test edits them to change a definition) and what it was asked
    to do."""

    tools: list[ListedTool] = field(default_factory=recorded_tools)
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    # The caller each call's `_meta` named; GitHub is sent none, so each is `None`.
    callers: list[str | None] = field(default_factory=list)

    async def call(
        self, name: str, arguments: dict[str, object], user_id: str | None
    ) -> str | ToolReply:
        self.calls.append((name, arguments))
        self.callers.append(user_id)
        owner, repo = _text(arguments.get("owner")), _text(arguments.get("repo"))
        match name:
            case "get_file_contents":
                path = _text(arguments.get("path")) or "/"
                if path == "missing.txt":
                    raise ToolFailure("failed to get file contents: 404 Not Found")
                uri = f"repo://{owner}/{repo}/contents/{path.lstrip('/')}"
                if path == BLOB_PATH:
                    return ToolReply(
                        text="successfully downloaded binary file",
                        files=(EmbeddedFile(uri=uri, blob="iVBORw0KGgo=", mime_type="image/png"),),
                    )
                return ToolReply(
                    text="successfully downloaded text file (SHA: 0123abc)",
                    files=(EmbeddedFile(uri=uri, text=FILE_TEXT, mime_type="text/plain"),),
                )
            case "add_issue_comment":
                number = arguments.get("issue_number")
                return json.dumps(
                    {
                        "id": "4242",
                        "html_url": f"https://github.com/{owner}/{repo}/issues/{number}#c-4242",
                    }
                )
            case "issue_write":
                return json.dumps(
                    {"id": "77", "url": f"https://github.com/{owner}/{repo}/issues/9"}
                )
            case _:
                return f"{name}:{owner}/{repo}"


def create_github_app(
    github: Github,
    *,
    token: str | None,
    allowed_hosts: Sequence[str],
    streaming: bool = False,
) -> McpApp:
    """The server, answering JSON, or as an event stream when `streaming` (what the real server may
    do). `token` is the bearer it enforces (`None` serves anyone)."""
    return build_app(
        github.tools,
        github.call,
        token=token,
        allowed_hosts=allowed_hosts,
        name="github-mcp-server",
        json_response=not streaming,
    )
