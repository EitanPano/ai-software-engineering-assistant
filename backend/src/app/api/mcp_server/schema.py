"""schema.py belongs: this directory's contract, the pydantic models that validate requests, type
responses and produce `openapi.json`. The leaf of the directory: routes and controller import it.
It does not belong: business rules or HTTP handling (`controller.py`) or data access
(`service.py`).

`McpServer` carries no URL, no token and no tool count. `ListingTool` carries third-party text and
two printed schemas: they are strings the server prints (`json.dumps`, `sort_keys`, `indent=2`,
`ensure_ascii=False`), never objects, because the browser's `JSON.parse` would print `1` and `1.0`
alike and round past 2^53.
"""

from typing import Annotated, Literal

from fastapi import Path
from pydantic import StringConstraints

from app.services.utils.api_model import RequestModel, ResponseModel, Timestamp
from app.services.utils.pagination import Page

# The wire's forms of `models/mcp_server/enums.py`, inlined in the contract.
type PinStatusName = Literal["not_required", "unpinned", "current", "changed"]
type ToolChangeName = Literal["added", "removed", "changed", "unchanged"]

# A plain assignment, not a `type` statement: FastAPI reads the `Path` metadata off the annotation.
McpServerId = Annotated[str, Path(alias="id", min_length=1)]

# SHA-256 as 64 lowercase hex characters; the class is spelled out, as `\d` is Unicode in pydantic.
type ListingDigest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class McpServer(ResponseModel):
    id: str
    name: str
    enabled: bool
    pin_status: PinStatusName
    created_at: Timestamp
    updated_at: Timestamp


class McpServerPage(Page[McpServer]):
    """The list endpoint's page; the concrete name is the contract component."""


class ListingTool(ResponseModel):
    """Live fields are null on `removed`; the pinned fields are set only on `changed` and
    `removed`."""

    name: str
    change: ToolChangeName
    description: str | None
    input_schema: str | None
    pinned_description: str | None
    pinned_input_schema: str | None


class McpServerListing(ResponseModel):
    mcp_server_id: str
    listing_digest: str
    items: list[ListingTool]


class UpdateMcpServerBody(RequestModel):
    enabled: bool


class AcceptListingBody(RequestModel):
    """The digest the review returned: the accept binds to exactly what the admin read."""

    listing_digest: ListingDigest
