"""`python -m tests.seed_ask_tool`: writes the `fixture` server and its `note` tool at `ask` into
the e2e database, for the journeys that approve a call, pinned (it is third party). It also pins
`github` to the seven recorded definitions and enables it, the state `accept_mcp_server github`
leaves, so `[[github_comment]]` is offered and waits at `ask`. Free: no network and no key.

It has `e2e_db.py`'s entry shape: it reads `E2E_DATABASE_URL`, refuses a name that does not end in
`_e2e`, sets `DATABASE_URL` before the first `app` import that reads the environment, and the URL of
the server is `ANTHROPIC_BASE_URL` + `/mcp` (the fake Anthropic process serves it, see
`tests/fake_note.py`). `restore_seed` deletes the row, so it runs after `e2e-db` and not before.
`TestRealRestart` calls `seed` after `reset_store()` for the same reason.
"""

import asyncio
import contextlib
import os
import sys
from dataclasses import dataclass
from typing import Final

from app.infra.scripts.e2e_db import assert_e2e_database, e2e_url

SERVER_ID: Final = "fixture"
TOOL_NAME: Final = "note"
DEFAULT_BASE_URL: Final = "http://127.0.0.1:8101"


@dataclass(frozen=True)
class _Name:
    name: str


async def seed(base_url: str) -> None:
    """The `fixture` server at `<base_url>/mcp` and its `note` tool at `ask`, replacing earlier
    rows of the same ids. Refuses any database but a `_test` or `_e2e` one."""
    from psycopg.types.json import Jsonb

    from app.infra.scripts.mcp_seed import assert_seedable
    from app.models.mcp_server.type import ListedTool
    from app.services.db import execute, fetch_one
    from tests.fake_github_mcp import recorded_tools
    from tests.fake_note import NOTE_TOOL

    def pin(tools: list[ListedTool]) -> Jsonb:
        return Jsonb(
            [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]
        )

    row = await fetch_one(_Name, "select current_database() as name")
    assert_seedable("" if row is None else row.name)
    await execute("delete from tool_policy where mcp_server_id = %s", (SERVER_ID,))
    await execute("delete from mcp_server where id = %s", (SERVER_ID,))
    # A third party offers nothing until its tools are pinned (plan 012), as an admin's accept does.
    await execute(
        "insert into mcp_server (id, name, url, enabled, pinned_tool_definition, created_at, "
        "updated_at) values (%s, %s, %s, true, %s, now(), now())",
        (SERVER_ID, SERVER_ID, f"{base_url.rstrip('/')}/mcp", pin([NOTE_TOOL])),
    )
    await execute(
        "insert into tool_policy (id, mcp_server_id, tool_name, effect, created_at, updated_at) "
        "values (%s, %s, %s, 'ask', now(), now())",
        (f"{SERVER_ID}-{TOOL_NAME}", SERVER_ID, TOOL_NAME),
    )
    # The seeded `github` row, accepted: its address is `GITHUB_MCP_URL`, the fake at
    # `<base_url>/github/mcp`, and its policies are the migration's.
    github = pin(recorded_tools())
    await execute(
        "update mcp_server set pinned_tool_definition = %s, tool_definition = %s, enabled = true "
        "where name = 'github'",
        (github, github),
    )


async def main() -> int:
    url = e2e_url(os.environ)
    try:
        assert_e2e_database(url)
        # Before the first import that reads the environment.
        os.environ["DATABASE_URL"] = url
        from app.infra.postgres import postgres

        try:
            await seed(os.environ.get("ANTHROPIC_BASE_URL") or DEFAULT_BASE_URL)
        finally:
            with contextlib.suppress(Exception):
                await postgres.close()
    except Exception as error:
        print(f"seed of the ask tool failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    from app.infra.loop import selector_loop_factory

    sys.exit(asyncio.run(main(), loop_factory=selector_loop_factory))
