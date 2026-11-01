"""The MCP configuration `0009-mcp-server.sql` seeds (the `knowledge` server and its `search`
policy), restored to exactly what the migration inserts. The e2e preparation and the test reset
call it, so a stored listing, an edited policy or a deleted row never leaks into the next run, and
the migration stays the one place the values are written: the statements are read from its text,
not copied.
"""

import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Final

from app.services.db import Executor, execute, fetch_one

MIGRATION: Final = "0009-mcp-server.sql"
SEEDABLE_SUFFIXES: Final = ("_test", "_e2e")
_SEEDS: Final = re.compile(
    r"^insert into (?:mcp_server|tool_policy)\b.*?;", re.DOTALL | re.MULTILINE
)


def seed_statements() -> list[str]:
    """The migration's `insert` statements for the two seeded tables, in file order."""
    text = files("app.infra.migrations").joinpath(MIGRATION).read_text(encoding="utf-8")
    return _SEEDS.findall(text)


class SeedDatabaseError(Exception):
    """`restore_seed` was pointed at a database that is neither a test nor an e2e database."""


def assert_seedable(name: str) -> None:
    """Raises unless the database name ends in `_test` or `_e2e`: this helper deletes rows, so it
    checks the connection it is given, whatever its callers checked."""
    if not name.endswith(SEEDABLE_SUFFIXES):
        raise SeedDatabaseError(
            f"refusing to restore the seed in database {name!r}: its name must end in _test or _e2e"
        )


@dataclass(frozen=True)
class _Name:
    name: str


async def _current_database(db: Executor | None) -> str:
    row = await fetch_one(_Name, "select current_database() as name", db=db)
    return "" if row is None else row.name


async def restore_seed(*, db: Executor | None = None) -> None:
    """Empties both tables and inserts the migration's rows again (a test or e2e database only)."""
    assert_seedable(await _current_database(db))
    await execute("delete from tool_policy", db=db)
    await execute("delete from mcp_server", db=db)
    for statement in seed_statements():
        await execute(statement, db=db)
