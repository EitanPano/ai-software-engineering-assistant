"""FREE, and run by a person: not collected by pytest and in no gate. It makes no model turn.

    uv run --env-file .env python -m tests.live_github [owner repo path]

It meets the real GitHub half of the stack, through a gateway started by hand: `docker compose
--profile github up -d github-mcp` (the server, published on loopback 8082), then `uv run
--env-file .env.github poe github-gateway` in another terminal (`GITHUB_MCP_PAT` and the shared
`GITHUB_MCP_TOKEN` in `backend/.env.github`). The Compose gateway publishes no port, so it cannot
be reached from here. This script's own `backend/.env` holds the same `GITHUB_MCP_TOKEN` and the
Anthropic key, never the PAT:

1. lists the tools and compares them with `github_tools.json`, the seven definitions the fakes
   serve, and prints each difference (a drift here means the fake no longer stands for the server);
2. reads one real file whole through `get_file_contents` (default: the README of
   `github/github-mcp-server`, a public repository) and prints its size;
3. sends the live listing, built as the agent would offer it (`services/tool.py`, with the system
   prompt), to Anthropic's token-counting endpoint, which bills nothing, and prints the count.
   A refusal there (an `x-mcp-header` key outside `strict`, say) would fail every new
   conversation, so it shows here for free. A pass does not stand in for the paid run: the docs do
   not say that endpoint validates like `messages`.

The environment is this process's, read once by `config/env.py`: `GITHUB_MCP_URL` (default the
gateway on loopback) and `GITHUB_MCP_TOKEN` (the one the gateway holds) are needed, and
`ANTHROPIC_API_KEY` for step 3. `GITHUB_MCP_PAT` must not be set here: this is not the gateway
and the environment refuses it. Exit 0 when the listing has the seven tools, the file is not empty
and the count came back; 1 when a difference, an error result or an empty file stands; 2 when a
server or the API could not be reached or refused the request.
"""

import asyncio
import json
import sys
from typing import Final

from app.config.constants import AGENT_SYSTEM_PROMPT
from app.config.env import env
from app.models.mcp_server.constants import GITHUB_SERVER
from app.services import mcp, tool
from app.services.anthropic import count_tokens
from tests.fake_github_mcp import recorded_tools

DEFAULT_FILE: Final = ("github", "github-mcp-server", "README.md")


async def main(owner: str, repo: str, path: str) -> int:
    if env.github_mcp_token is None:
        print("GITHUB_MCP_TOKEN is not set: it is the token the gateway holds")
        return 2
    try:
        live = await mcp.list_tools(env.github_mcp_url, token=env.github_mcp_token)
    except mcp.McpUnavailable as error:
        print(f"the gateway did not answer at {env.github_mcp_url}: {error.reason}")
        return 2
    recorded = recorded_tools()
    differences = tool.listing_changes(recorded, live)
    names = [t.name for t in sorted(live, key=lambda t: t.name)]
    print(f"listed {len(live)} tools: {json.dumps(names)}")
    print(f"digest {tool.listing_digest(live)}")
    print("differs from github_tools.json:" if differences else "equal to github_tools.json")
    for line in differences:
        print(f"  {line}")

    try:
        reply = await mcp.call_tool(
            env.github_mcp_url,
            "get_file_contents",
            {"owner": owner, "repo": repo, "path": path},
            token=env.github_mcp_token,
            pinned=next((t for t in live if t.name == "get_file_contents"), None),
        )
    except (mcp.McpUnavailable, mcp.ToolDefinitionChanged) as error:
        print(f"the file could not be read: {type(error).__name__}")
        return 2
    print(f"read {owner}/{repo}/{path}: {len(reply.text)} characters, error={reply.is_error}")
    print(f"  starts: {reply.text[:80]!r}")

    definitions = tool.definitions({GITHUB_SERVER: live})
    try:
        counted = await count_tokens(definitions, system=AGENT_SYSTEM_PROMPT)
    except Exception as error:  # the SDK's error types stay inside services/anthropic.py
        print(f"count_tokens refused the {len(definitions)} definitions: {type(error).__name__}")
        print(f"  {getattr(error, 'message', 'no message')}")
        return 2
    print(f"count_tokens accepted {len(definitions)} definitions: {counted} input tokens")

    healthy = len(live) == len(recorded) and not reply.is_error and reply.text != ""
    return 0 if healthy and not differences else 1


if __name__ == "__main__":
    arguments = tuple(sys.argv[1:])
    target = arguments if len(arguments) == len(DEFAULT_FILE) else DEFAULT_FILE
    sys.exit(asyncio.run(main(*target)))
