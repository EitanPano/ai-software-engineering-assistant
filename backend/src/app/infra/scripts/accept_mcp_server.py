"""`python -m app.infra.scripts.accept_mcp_server <name>`: an admin accepts a third-party MCP
server's tools. There is no screen for it yet, so this is the admin's act, as `grant_admin` made
the first admin.

It lists the server live and prints the listing whole (every tool with its description and schema),
its digest and what changed from the current pin, then asks for a yes. On a yes it stores exactly
what it printed as the pin and as the last listing and enables the row; a policy row is never
touched. Anything else exits 1 writing nothing: an unknown name, `knowledge` (ours, not pinned), a
server that does not answer or lists no tool, a wrong argument, or no yes.

A tool name outside `[A-Za-z0-9_-]+`, or listed twice, exits 1 before anything of the listing is
printed (the API refuses such a name, and a name could carry terminal escapes).

In Compose it runs through `backend-migrate`, which has the same image and environment as the API:
`docker compose --env-file backend/.env.github --profile app --profile github run --rm
backend-migrate python -m app.infra.scripts.accept_mcp_server github`. By hand:
`uv run --env-file .env python -m app.infra.scripts.accept_mcp_server github`.
"""

import asyncio
import contextlib
import json
import re
import sys
from collections.abc import Callable, Sequence
from typing import Final

from app.api.mcp_server.controller import accept_listing, find_server, read_listing
from app.infra.loop import selector_loop_factory
from app.infra.postgres import postgres
from app.models.mcp_server.constants import KNOWLEDGE_SERVER
from app.services import tool
from app.services.logger import Logger, configure_logging, log

USAGE: Final = "usage: accept_mcp_server <name>"
TOOL_NAME: Final = re.compile(r"[A-Za-z0-9_-]+")


def read_answer() -> str:
    return input("Type yes to accept these tools: ")


async def accept(
    argv: Sequence[str], logger: Logger, answer: Callable[[], str], write: Callable[[str], object]
) -> int:
    if len(argv) != 1 or argv[0].startswith("-"):
        logger.error(USAGE)
        return 1
    name = argv[0]
    server = await find_server(name)
    if server is None or server.name == KNOWLEDGE_SERVER:
        logger.error("no third-party server of that name", {"server": name})
        return 1
    live = await read_listing(server)
    if live is None:
        logger.error("the server did not answer", {"server": name})
        return 1
    if not live:
        logger.error("the server lists no tool", {"server": name})
        return 1

    names = [entry.name for entry in live]
    if len(set(names)) != len(names) or not all(TOOL_NAME.fullmatch(n) for n in names):
        # Nothing of the listing is printed: a name is the server's, and may carry terminal escapes.
        # The API also refuses a name outside this set, which would fail every new conversation.
        logger.error("the listing has a tool name that is repeated or not [A-Za-z0-9_-]+")
        return 1

    write(f"{name}: {len(live)} tools, digest {tool.listing_digest(live)}")
    for entry in live:
        document = {
            "name": entry.name,
            "description": entry.description,
            "input_schema": entry.input_schema,
        }
        write(json.dumps(document, indent=2, sort_keys=True))
    changes = tool.listing_changes(server.pinned_tool_definition, live)
    if server.pinned_tool_definition is None:
        write("no earlier pin: every tool is new")
    elif not changes:
        write("unchanged from the pin")
    for change in changes:
        write(change)

    if answer().strip() != "yes":
        logger.error("not accepted", {"server": name})
        return 1
    await accept_listing(server, live)
    logger.info("accepted", {"server": name, "tools": len(live)})
    return 0


async def main(
    argv: Sequence[str],
    *,
    logger: Logger = log,
    read_answer: Callable[[], str] = read_answer,
    write: Callable[[str], object] = print,
) -> int:
    configure_logging()
    try:
        return await accept(argv, logger, read_answer, write)
    except Exception as error:
        logger.error("accepting failed", {}, error)
        return 1
    finally:
        with contextlib.suppress(Exception):
            await postgres.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:]), loop_factory=selector_loop_factory))
