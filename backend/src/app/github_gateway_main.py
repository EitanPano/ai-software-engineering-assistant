"""The GitHub gateway entry: `python -m app.github_gateway_main` is the one process that holds
`GITHUB_MCP_PAT`. `github-mcp-server http` has no static token (it reads a personal access token
from each request's `Authorization`), so a plain Compose service would make the API send the token.
The gateway takes the API's generated `GITHUB_MCP_TOKEN` instead, adds the personal access token and
forwards to `github-mcp-server`, which sees it per request and stores it nowhere (`build_gateway`).

It has no store and nothing of `infra/`: no bus, scheduler or sweep (a second sweep would end the
API's live runs). With `APP_PROCESS=github_gateway` the environment holds only `GITHUB_MCP_PAT`,
`GITHUB_MCP_TOKEN` and `GITHUB_MCP_UPSTREAM_URL` (`config/env.py`), both secrets with no
development default in any environment; the other secrets are replaced with per-boot values.

`uvicorn_options` is a copy of `main.py`'s, because nothing may import the API's entry;
`tests/test_entry.py` holds the two equal except `host`, which is loopback outside production.
"""

from typing import Final, NotRequired, TypedDict

import uvicorn

from app.config.env import env
from app.services.logger import configure_logging
from app.services.mcp import McpApp, build_gateway

configure_logging()

_LOOP: Final = "app.infra.loop:selector_loop_factory"


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
        # production the token is one a person generated, but only loopback may reach it by hand.
        "host": "0.0.0.0" if env.app_env == "production" else "127.0.0.1",  # noqa: S104
        "port": env.port,
        "loop": _LOOP,
        "server_header": False,
        "proxy_headers": False,
        "access_log": False,
        "log_config": None,
        "timeout_graceful_shutdown": 5,
    }


def create_app() -> McpApp:
    """The gateway. `load_env` already refused to boot this process without its two secrets; the
    check here is for a caller that skipped it."""
    if env.github_mcp_pat is None or env.github_mcp_token is None:
        raise RuntimeError("the GitHub gateway needs GITHUB_MCP_PAT and GITHUB_MCP_TOKEN")
    return build_gateway(
        upstream_url=env.github_mcp_upstream_url, pat=env.github_mcp_pat, token=env.github_mcp_token
    )


def main() -> None:
    uvicorn.run(create_app(), **uvicorn_options())


if __name__ == "__main__":
    main()
