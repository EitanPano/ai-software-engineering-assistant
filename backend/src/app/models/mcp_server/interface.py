"""interface.py belongs: the stored `mcp_server` record, what `api/mcp_server/service.py` reads and
writes. `url` is null for `knowledge`, whose address comes from the environment; `tool_definition`
is the last good listing of the server, or null before the first one. `pinned_tool_definition` is
what an admin accepted (`accept_mcp_server`): every server but `knowledge` offers only pinned tools
whose live listing still matches, and nothing while it is null. A frozen dataclass despite the name.
It does not belong: the tool shapes (`type.py`) or fixed values (`constants.py`).
"""

from dataclasses import dataclass
from datetime import datetime

from app.models.mcp_server.type import ListedTool


@dataclass(frozen=True)
class McpServerRecord:
    id: str
    name: str
    url: str | None
    enabled: bool
    tool_definition: list[ListedTool] | None
    created_at: datetime
    updated_at: datetime
    pinned_tool_definition: list[ListedTool] | None = None
