"""service.py belongs: every query for the `mcp_server` table and nothing else, private to this
directory: only its `controller.py` imports it. Rows are plain records.
It does not belong: business rules, calls to a server or error mapping (`controller.py`).
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Final, LiteralString

from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, field_validator

from app.models.mcp_server.constants import KNOWLEDGE_SERVER
from app.models.mcp_server.interface import McpServerRecord
from app.models.mcp_server.type import ListedTool
from app.services.db import Executor, execute, fetch_all, fetch_one
from app.services.utils.pagination import Slice, decode_cursor, encode_cursor, to_page

_COLUMNS: Final[LiteralString] = (
    "id, name, url, enabled, tool_definition, pinned_tool_definition, created_at, updated_at"
)
_SELECT: Final[LiteralString] = "select " + _COLUMNS + " from mcp_server "  # noqa: S608
_ISO: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T.+")


def _iso_text(value: object) -> object:
    if isinstance(value, str) and _ISO.fullmatch(value):
        return datetime.fromisoformat(value)
    raise ValueError("must be an ISO 8601 timestamp")


class ServerCursor(BaseModel):
    """The sort key of the server list: (created_at, id), newest first."""

    model_config = ConfigDict(strict=True)

    created_at: Annotated[AwareDatetime, BeforeValidator(_iso_text)]
    id: str

    @field_validator("id")
    @classmethod
    def _no_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("must not hold a NUL")
        return value


def _cursor_of(record: McpServerRecord) -> str:
    return encode_cursor({"created_at": record.created_at.isoformat(), "id": record.id})


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


async def list_page(
    *, cursor: str | None, limit: int, db: Executor | None = None
) -> Slice[McpServerRecord]:
    """Newest first, paged by `(created_at, id)`; a malformed cursor is a 400."""
    after = None if cursor is None else decode_cursor(cursor, ServerCursor)
    if after is None:
        rows = await fetch_all(
            _ServerRow,
            _SELECT + "order by created_at desc, id desc limit %s",
            (limit + 1,),
            db=db,
        )
    else:
        rows = await fetch_all(
            _ServerRow,
            _SELECT
            + "where (created_at, id) < (%s, %s) order by created_at desc, id desc limit %s",
            (after.created_at, after.id, limit + 1),
            db=db,
        )
    return to_page([_to_record(row) for row in rows], limit, _cursor_of)


async def find_by_id(server_id: str, *, db: Executor | None = None) -> McpServerRecord | None:
    if "\x00" in server_id:  # a text column cannot hold it, so no row can match
        return None
    row = await fetch_one(_ServerRow, _SELECT + "where id = %s", (server_id,), db=db)
    return None if row is None else _to_record(row)


async def set_enabled(
    server_id: str, enabled: bool, now: datetime, *, db: Executor | None = None
) -> McpServerRecord | None:
    """Turns a server on or off and returns the row. Enabling a third party with no pin writes
    nothing and returns `None`, in the statement itself: a pin is never undone, so the check cannot
    race. `None` is also an unknown id; the caller tells them apart."""
    if "\x00" in server_id:
        return None
    row = await fetch_one(
        _ServerRow,
        "update mcp_server set enabled = %s, updated_at = %s where id = %s "  # noqa: S608
        "and (not %s or name = %s or pinned_tool_definition is not null) returning " + _COLUMNS,
        (enabled, now, server_id, enabled, KNOWLEDGE_SERVER),
        db=db,
    )
    return None if row is None else _to_record(row)


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
    """Keeps the last good listing of a server; an unchanged one writes nothing, so concurrent runs
    do not queue on the row."""
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
