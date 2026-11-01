"""The `knowledge` process entry: `python -m app.knowledge_main` serves the MCP server that offers
the agent one tool, `search`, over the hybrid search (`search_for_tool` of the search module).

It is a process of its own so the agent's tool calls reach the index through a boundary the loop
holds: only the loop, with the bearer token, can call it, and its pool and its concurrency are its
own, so a burst of searches never takes a connection from the API. It connects `postgres` alone and
nothing else of `infra/` (no bus, no scheduler, no sweep: a second sweep would end the API's live
runs). With `APP_PROCESS=knowledge` the environment holds only `DATABASE_URL`, `VOYAGE_API_KEY` and
`KNOWLEDGE_MCP_TOKEN` (`config/env.py`), so no key to the model and no signing secret is here.

`uvicorn_options` is a copy of `main.py`'s, because nothing may import the API's entry;
`tests/test_entry.py` holds the two equal except `host`, which is loopback outside production.
`search_for_tool` is passed in, not imported by `services/mcp.py`, which sits below `api/`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final, NotRequired, TypedDict

import uvicorn

from app.api.search.controller import search_for_tool
from app.config.env import defaulted_secrets, env
from app.infra.dependency import connect_all, disconnect_all
from app.infra.postgres import postgres
from app.services.logger import configure_logging, log
from app.services.mcp import McpApp, serve

configure_logging()

_LOOP: Final = "app.infra.loop:selector_loop_factory"
# The names the server is reached by: its Compose service name on any port, and loopback for a
# process started by hand. The SDK refuses any other `Host` (DNS rebinding protection).
ALLOWED_HOSTS: Final = ("knowledge:*", "127.0.0.1:*", "localhost:*", "[::1]:*")


class UvicornOptions(TypedDict):
    host: str
    port: int
    loop: str
    server_header: bool
    proxy_headers: bool
    access_log: bool
    log_config: None
    timeout_graceful_shutdown: int
    reload: NotRequired[bool]
    reload_dirs: NotRequired[list[str]]


def uvicorn_options() -> UvicornOptions:
    """What `main.py` passes uvicorn, without the reload: the selector loop, no `Server` header, no
    proxy-header trust, no access log (it would log the query string), no uvicorn log config."""
    return {
        # The container listens on every interface; Compose publishes no port for it. Outside
        # production the token is the public development default, so only loopback may reach it.
        "host": "0.0.0.0" if env.app_env == "production" else "127.0.0.1",  # noqa: S104
        "port": env.port,
        "loop": _LOOP,
        "server_header": False,
        "proxy_headers": False,
        "access_log": False,
        "log_config": None,
        "timeout_graceful_shutdown": 5,
    }


@asynccontextmanager
async def _connected() -> AsyncIterator[None]:
    """`postgres` alone, with the boot's bounded retry, closed on the way out."""
    for name in defaulted_secrets:
        log.warning("using a development default for a secret", {"variable": name})
    await connect_all([postgres])
    try:
        yield
    finally:
        await disconnect_all([postgres])


async def _search(query: str) -> str:
    return await search_for_tool(query=query)


def create_app() -> McpApp:
    """The server, with the store connected around it. Tests import this and enter the SDK's own
    lifespan on the same object."""
    return serve(
        _search, token=env.knowledge_mcp_token, allowed_hosts=ALLOWED_HOSTS, around=_connected
    )


app: Final = create_app()


def main() -> None:
    uvicorn.run(app, **uvicorn_options())


if __name__ == "__main__":
    main()
