"""A scripted fake of the GitHub REST API the index reads, on its wire format, so the real
`services/github.py` runs against it: the backend tests point an `httpx2.AsyncClient` at this ASGI
app, and the e2e suite starts it on port 8102 (`python -m tests.fake_github`) and sets
`GITHUB_BASE_URL` for the API. No network.

The repository name picks the script:

- `missing` or `missing-<token>`: the repository lookup is a 404.
- `limited`: the lookup is a 403 with `x-ratelimit-remaining: 0`.
- `down`: the lookup is a 502.
- `emptyrepo`: the repository exists, but looking up a commit is a 409 (an empty repository).
- any name, with the ref `nope`: the commit lookup is a 422.
- `hostile-links`, `hostile-traversal`, `bomb`: the archive holds those members.
- `crafted`: an honest file and a file that makes tree-sitter run for minutes.
- `evil-redirect`: the archive redirect points at another host; `double-redirect`: the host it
  points at redirects again.
- `notar`: the archive is not a tarball.
- `embedfail-<key>`: the fixture, plus a file holding the fake Voyage's failure marker for
  `<key>`, so indexing fails as `embedding_unavailable` until `POST /release/<key>` on the fake
  Voyage.
- any owner is served; `GET /health` answers 200 (the e2e runner waits on it).
- anything else: the fixture repository. `octocat/hello-world` answers in GitHub's spelling,
  `octocat/Hello-World`.

`calls` records every request (method, raw path, headers), so a test can assert what was sent.
"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import unquote

from starlette.types import Receive, Scope, Send

from tests.fixture_repository import (
    FIXTURE_COMMIT,
    FIXTURE_FILES,
    bomb_tarball,
    build_tarball,
    crafted_tarball,
    fixture_tarball,
    links_tarball,
    traversal_tarball,
)

CANONICAL: Final = {"octocat/hello-world": "octocat/Hello-World"}
BOMB_BYTES: Final = 3 * 1024 * 1024
FAIL_MARKER_FILE: Final = "FAIL.txt"
EMBEDFAIL: Final = "embedfail-"
SHA_MEDIA_TYPE: Final = "application/vnd.github.sha"

_ROUTE: Final = re.compile(
    r"^/(?:repos/(?P<o>[^/]+)/(?P<r>[^/]+)(?:/(?P<kind>commits|tarball)/(?P<tail>[^/]+))?"
    r"|codeload/(?P<co>[^/]+)/(?P<cr>[^/]+)/(?P<cc>[^/]+))$"
)


@dataclass(frozen=True)
class Call:
    method: str
    raw_path: str
    headers: Mapping[str, str]


@dataclass
class State:
    calls: list[Call] = field(default_factory=list)


state: Final = State()


def reset() -> None:
    state.calls.clear()


def _json(
    status: int, body: object, headers: Mapping[str, str] | None = None
) -> tuple[int, bytes, dict[str, str]]:
    import json

    return (
        status,
        json.dumps(body).encode(),
        {"content-type": "application/json", **(headers or {})},
    )


def _archive(repo: str) -> bytes:
    match repo:
        case "hostile-links":
            return links_tarball()
        case "hostile-traversal":
            return traversal_tarball()
        case "bomb":
            return bomb_tarball(BOMB_BYTES)
        case "crafted":
            return crafted_tarball()
        case "notar":
            return b"this is not a tarball"
        case _ if repo.lower().startswith(EMBEDFAIL):
            key = repo[len(EMBEDFAIL) :]
            marker = f"text [[fail:{key}]] text\n".encode()
            return build_tarball({**FIXTURE_FILES, FAIL_MARKER_FILE: marker})
        case _:
            return fixture_tarball()


def _answer(scope: Scope, origin: str, accept: str) -> tuple[int, bytes, dict[str, str]]:
    raw = scope["raw_path"].decode()
    if raw == "/health":
        return _json(200, {"status": "ok"})
    found = _ROUTE.match(raw)
    if found is None:
        return _json(404, {"message": "Not Found"})
    if found["co"] is not None:
        repo = unquote(found["cr"]).lower()
        if repo == "double-redirect":
            return 302, b"", {"location": f"{origin}/codeload/{found['co']}/{found['cr']}/again"}
        return 200, _archive(repo), {"content-type": "application/x-gzip"}
    owner, repo = unquote(found["o"]), unquote(found["r"])
    name = repo.lower()
    if name == "missing" or name.startswith("missing-"):
        return _json(404, {"message": "Not Found"})
    if name == "limited":
        return _json(403, {"message": "API rate limit exceeded"}, {"x-ratelimit-remaining": "0"})
    if name == "down":
        return _json(502, {"message": "Bad Gateway"})
    kind, tail = found["kind"], found["tail"]
    if kind is None:
        full = CANONICAL.get(f"{owner}/{repo}".lower(), f"{owner}/{repo}")
        return _json(200, {"full_name": full, "default_branch": "main", "private": False})
    if kind == "commits":
        ref = unquote(tail)
        if name == "emptyrepo":
            return _json(409, {"message": "Git Repository is empty."})
        if ref == "nope":
            return _json(422, {"message": "No commit found for SHA: nope"})
        sha = ref if re.fullmatch(r"[0-9a-f]{40}", ref) else FIXTURE_COMMIT
        if accept == SHA_MEDIA_TYPE:
            # GitHub's documented media type for the commit's sha alone, as plain text.
            return 200, sha.encode(), {"content-type": "text/plain; charset=utf-8"}
        return _json(200, {"sha": sha})
    if name == "evil-redirect":
        return 302, b"", {"location": "https://evil.example.net/steal"}
    return 302, b"", {"location": f"{origin}/codeload/{owner}/{repo}/{tail}"}


async def app(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] != "http":
        return
    headers = {key.decode(): value.decode() for key, value in scope["headers"]}
    state.calls.append(Call(scope["method"], scope["raw_path"].decode(), headers))
    origin = f"http://{headers.get('host', 'fake-github')}"
    status, body, extra = _answer(scope, origin, headers.get("accept", ""))
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-length", str(len(body)).encode()),
                *((key.encode(), value.encode()) for key, value in extra.items()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("FAKE_GITHUB_PORT", "8102")))


if __name__ == "__main__":
    main()
