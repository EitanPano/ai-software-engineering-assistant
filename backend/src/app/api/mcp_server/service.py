"""service.py belongs: every query for the `mcp_server` table and nothing else, private to this
directory: only its `controller.py` imports it. Rows are plain records.
It does not belong: business rules, calls to a server or error mapping (`controller.py`).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from app.models.mcp_server.interface import McpServerRecord
from app.models.mcp_server.type import ListedTool
from app.services.db import Executor, execute, fetch_all, fetch_one


@dataclass(frozen=True)
class _ServerRow:
    id: str
    name: str
    url: str | None
    enabled: bool
    tool_definition: list[object] | None
    pinned_tool_definition: list[object] | None
    created_at: datetime
    updated_at: datetime


def _listing(value: list[object] | None) -> list[ListedTool] | None:
    """The stored listing, or `None` when there is none. An entry that does not read as a tool is
    dropped: the column is ours, but a bad row must not fail every run."""
    if value is None:
        return None
    tools: list[ListedTool] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        description = entry.get("description")
        schema = entry.get("input_schema")
        if isinstance(name, str) and isinstance(description, str) and isinstance(schema, dict):
            tools.append(ListedTool(name=name, description=description, input_schema=schema))
    return tools


def _document(tools: list[ListedTool]) -> Jsonb:
    return Jsonb(
        [
            {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
            for tool in tools
        ]
    )


def _to_record(row: _ServerRow) -> McpServerRecord:
    return McpServerRecord(
        id=row.id,
        name=row.name,
        url=row.url,
        enabled=row.enabled,
        tool_definition=_listing(row.tool_definition),
        created_at=row.created_at.astimezone(UTC),
        updated_at=row.updated_at.astimezone(UTC),
        pinned_tool_definition=_listing(row.pinned_tool_definition),
    )


async def list_enabled(*, db: Executor | None = None) -> list[McpServerRecord]:
    rows = await fetch_all(
        _ServerRow,
        "select id, name, url, enabled, tool_definition, pinned_tool_definition, created_at, "
        "updated_at from mcp_server where enabled order by name",
        db=db,
    )
    return [_to_record(row) for row in rows]


async def find_by_name(name: str, *, db: Executor | None = None) -> McpServerRecord | None:
    row = await fetch_one(
        _ServerRow,
        "select id, name, url, enabled, tool_definition, pinned_tool_definition, created_at, "
        "updated_at from mcp_server where name = %s",
        (name,),
        db=db,
    )
    return None if row is None else _to_record(row)


async def save_listing(
    server_id: str, tools: list[ListedTool], now: datetime, *, db: Executor | None = None
) -> None:
    """Keeps the last good listing of a server; an unchanged one writes nothing, so `updated_at`
    means "the listing changed" and concurrent runs do not queue on the row."""
    document = _document(tools)
    await execute(
        "update mcp_server set tool_definition = %s, updated_at = %s "
        "where id = %s and tool_definition is distinct from %s",
        (document, now, server_id, document),
        db=db,
    )


async def save_pin(
    server_id: str, tools: list[ListedTool], now: datetime, *, db: Executor | None = None
) -> None:
    """An admin's accept: the pin, the same tools as the last listing, and the row enabled, in one
    statement. Only `accept_listing` calls this."""
    document = _document(tools)
    await execute(
        "update mcp_server set pinned_tool_definition = %s, tool_definition = %s, enabled = true, "
        "updated_at = %s where id = %s",
        (document, document, now, server_id),
        db=db,
    )
