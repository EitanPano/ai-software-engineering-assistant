"""A request must name this server in `Host`, or it is refused before a route reads it.

Loopback is this API's boundary, and a published port does not hold against DNS rebinding: a page on
`http://evil.example:8000` whose name then resolves to 127.0.0.1 is same-origin with the API, so
CORS never applies. Its requests still say `Host: evil.example:8000`, and no allowed name matches.

- Loopback names always pass, so a health check needs no setting; `ALLOWED_HOSTS` adds a public
  host's names.
- The port is ignored: the Vite proxy keeps the page's `Host`, so the API sees `localhost:5173`.
- No `Host`, or more than one, is refused: a browser always sends exactly one.

`knowledge` gets the same check from the MCP SDK (`services/mcp.py`).
"""

import re
from collections.abc import Iterable
from typing import Final

from starlette.types import ASGIApp, Receive, Scope, Send

from app.middleware.asgi import header_values, send_error
from app.services.utils.error import AppError

_LOOPBACK: Final = frozenset({"localhost", "127.0.0.1", "[::1]"})
# A name or a bracketed IPv6 address, then digits only as the port, so that nothing after the first
# `:` can smuggle in a second host (`127.0.0.1:8000@evil.example`).
_HOST_LINE: Final = re.compile(r"(\[[0-9a-f:.]+\]|[^\[\]:@/]+)(?::[0-9]*)?")


def _name_of(line: str) -> str | None:
    """The name in a `Host` line, lower-cased and without its port; `None` when it is malformed."""
    match = _HOST_LINE.fullmatch(line.strip().lower())
    return None if match is None else match[1]


class TrustedHostMiddleware:
    def __init__(self, app: ASGIApp, *, allowed: Iterable[str]) -> None:
        self.app = app
        self._allowed = _LOOPBACK | frozenset(allowed)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._trusts(header_values(scope, "host")):
            await self.app(scope, receive, send)
            return
        await send_error(scope, receive, send, AppError("validation_failed", "unknown host"))

    def _trusts(self, lines: list[str]) -> bool:
        return len(lines) == 1 and _name_of(lines[0]) in self._allowed
