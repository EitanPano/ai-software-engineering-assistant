"""`Rewrite`: serves an ASGI app, writing each `old` bytes of its answers as `new`.

pydantic prints NaN and Infinity as `null`, so a listing a hostile server sends raw (`NaN`,
`Infinity`, `1e400`) needs its bytes swapped on the way out. Each `new` is padded with JSON
whitespace to the length of `old`, so a `content-length` header stays true.
"""

from collections.abc import MutableMapping

from starlette.types import ASGIApp, Receive, Scope, Send


class Rewrite:
    def __init__(self, app: ASGIApp, swaps: dict[bytes, bytes]) -> None:
        self._app = app
        self._swaps = swaps

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def patched(message: MutableMapping[str, object]) -> None:
            body = message.get("body")
            if message["type"] == "http.response.body" and isinstance(body, bytes):
                for old, new in self._swaps.items():
                    body = body.replace(old, new.ljust(len(old)))
                message = {**message, "body": body}
            await send(message)

        await self._app(scope, receive, patched)
