"""`python -m tests.seed_changed_server <name>`: writes a disabled third-party server whose pin is
older than its last listing, for the e2e journey that reviews and accepts a changed definition.
Free: no network and no key.

The row is `<name>` at the fake Anthropic process's `/mcp` (the `note` tool of
`tests/fake_note.py`), disabled; its pin holds `note` with an older description and
`tool_definition` holds today's, so its pin status reads `changed`; `note`'s policy row is `ask`.
The name is unique per journey, so parallel journeys never share a row, and never `knowledge` or
`github` (a name the row's check allows without an address).

Entry shape of `seed_ask_tool.py`: it reads `E2E_DATABASE_URL`, refuses a name that does not end in
`_e2e`, and sets `DATABASE_URL` before the first `app` import that reads the environment. `seed`
refuses any database but a `_test` or `_e2e` one.
"""

import asyncio
import contextlib
import os
import re
import sys
from dataclasses import dataclass, replace
from typing import Final

from app.infra.scripts.e2e_db import assert_e2e_database, e2e_url

DEFAULT_BASE_URL: Final = "http://127.0.0.1:8101"
TOOL_NAME: Final = "note"
OLDER_DESCRIPTION: Final = "Stores a short note."
_NAME: Final = re.compile(r"[a-z][a-z0-9-]{0,40}")
_RESERVED: Final = frozenset({"knowledge", "github"})


@dataclass(frozen=True)
class _Name:
    name: str


def assert_server_name(name: str) -> None:
    """The name is the row's id and name: lowercase, no `__` (it splits `<server>__<tool>`), and
    not one of the two seeded servers."""
    if _NAME.fullmatch(name) is None or "__" in name or name in _RESERVED:
        raise ValueError("the server name must be new: lowercase letters, digits and hyphens")


async def seed(base_url: str, name: str) -> None:
    """The row `name`, replacing an earlier one of the same name. Refuses any database but a
    `_test` or `_e2e` one."""
    from psycopg.types.json import Jsonb

    from app.infra.scripts.mcp_seed import assert_seedable
    from app.models.mcp_server.type import ListedTool
    from app.services.db import execute, fetch_one
    from tests.fake_note import NOTE_TOOL

    def document(tools: list[ListedTool]) -> Jsonb:
        return Jsonb(
            [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]
        )

    assert_server_name(name)
    row = await fetch_one(_Name, "select current_database() as name")
    assert_seedable("" if row is None else row.name)
    await execute("delete from tool_policy where mcp_server_id = %s", (name,))
    await execute("delete from mcp_server where id = %s", (name,))
    await execute(
        "insert into mcp_server (id, name, url, enabled, tool_definition, "
        "pinned_tool_definition, created_at, updated_at) "
        "values (%s, %s, %s, false, %s, %s, now(), now())",
        (
            name,
            name,
            f"{base_url.rstrip('/')}/mcp",
            document([NOTE_TOOL]),
            document([replace(NOTE_TOOL, description=OLDER_DESCRIPTION)]),
        ),
    )
    await execute(
        "insert into tool_policy (id, mcp_server_id, tool_name, effect, created_at, updated_at) "
        "values (%s, %s, %s, 'ask', now(), now())",
        (f"{name}-{TOOL_NAME}", name, TOOL_NAME),
    )


async def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m tests.seed_changed_server <name>", file=sys.stderr)
        return 1
    url = e2e_url(os.environ)
    try:
        assert_e2e_database(url)
        # Before the first import that reads the environment.
        os.environ["DATABASE_URL"] = url
        from app.infra.postgres import postgres

        try:
            await seed(os.environ.get("ANTHROPIC_BASE_URL") or DEFAULT_BASE_URL, argv[0])
        finally:
            with contextlib.suppress(Exception):
                await postgres.close()
    except Exception as error:
        print(
            f"seed of the changed server failed: {type(error).__name__}: {error}", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    from app.infra.loop import selector_loop_factory

    sys.exit(asyncio.run(main(sys.argv[1:]), loop_factory=selector_loop_factory))
