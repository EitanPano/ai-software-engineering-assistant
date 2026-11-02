"""A scripted fake of Voyage AI's `POST /v1/embeddings`, on its wire format, so the real
`services/voyage.py` runs against it: the backend tests point an `httpx2.AsyncClient` at this ASGI
app, and the e2e suite starts it on port 8103 (`python -m tests.fake_voyage`) and sets
`VOYAGE_BASE_URL` for the API. No network and no key (any bearer token is accepted).

Every text gets a deterministic dense unit vector seeded by its SHA-256. The search fixture is
scripted on top of that (`scripted_vector`): a document chunk holding an anchor of
`tests/fixture_repository.py` embeds as the anchor's vector, the paraphrase query as the vector of
its chunk, and the keyword and dotted queries as the negation of theirs.

A text holding `[[fail:KEY]]` fails the whole call with a 503 until `POST /release/KEY` releases
it, so a test (or an e2e journey) can fail an index and then let a retry succeed. `[[bad]]` makes
the call answer vectors of the wrong length. `requests` records each call's body and
`authorization` header.
"""

import hashlib
import math
import os
import re
from dataclasses import dataclass, field
from typing import Final

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from tests.fixture_repository import (
    DOTTED_ANCHOR,
    DOTTED_QUERY,
    KEYWORD_ANCHOR,
    KEYWORD_QUERY,
    SEMANTIC_ANCHOR,
    SEMANTIC_QUERY,
)

DIMENSION: Final = 1024
MARKER: Final = re.compile(r"\[\[fail:([A-Za-z0-9_-]+)\]\]")

type Json = dict[str, object]


@dataclass
class State:
    released: set[str] = field(default_factory=set)
    requests: list[Json] = field(default_factory=list)
    authorizations: list[str] = field(default_factory=list)


state: Final = State()


def reset() -> None:
    state.released.clear()
    state.requests.clear()
    state.authorizations.clear()


def vector_of(text: str) -> list[float]:
    """A dense unit vector seeded by the text's SHA-256: two texts are nearly orthogonal. (A
    one-hot vector made HNSW find the exact match 39 times in 100, a dense one 100 in 100.)"""
    seed = hashlib.sha256(text.encode()).digest()
    values: list[float] = []
    block = 0
    while len(values) < DIMENSION:
        digest = hashlib.sha256(seed + block.to_bytes(4, "big")).digest()
        values += [(byte - 127.5) / 127.5 for byte in digest]
        block += 1
    values = values[:DIMENSION]
    norm = math.sqrt(sum(x * x for x in values))
    return [x / norm for x in values]


def scripted_vector(text: str, input_type: str) -> list[float]:
    """The scripted ranking of the search fixture. A document holding an anchor embeds as that
    anchor's vector; the paraphrase embeds as its chunk's; the keyword and dotted queries embed as
    the negation of theirs, which puts those chunks last in the semantic search, so only keyword
    search can put them in the top 5. Anything else is its own vector."""
    if input_type == "query":
        if text == SEMANTIC_QUERY:
            return vector_of(SEMANTIC_ANCHOR)
        for query, anchor in ((KEYWORD_QUERY, KEYWORD_ANCHOR), (DOTTED_QUERY, DOTTED_ANCHOR)):
            if text == query:
                return [-x for x in vector_of(anchor)]
        return vector_of(text)
    for anchor in (SEMANTIC_ANCHOR, KEYWORD_ANCHOR, DOTTED_ANCHOR):
        if anchor in text:
            return vector_of(anchor)
    return vector_of(text)


async def embeddings(request: Request) -> Response:
    state.authorizations.append(request.headers.get("authorization", ""))
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"detail": "bad request"}, status_code=400)
    state.requests.append(body)
    texts = body.get("input")
    if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
        return JSONResponse({"detail": "input must be a list of strings"}, status_code=400)
    for text in texts:
        found = MARKER.search(text)
        if found is not None and found.group(1) not in state.released:
            return JSONResponse({"detail": "unavailable"}, status_code=503)
    wrong = any("[[bad]]" in text for text in texts)
    input_type = str(body.get("input_type", "document"))
    data = [
        {
            "object": "embedding",
            "index": index,
            "embedding": (vector_of(text)[:10] if wrong else scripted_vector(text, input_type)),
        }
        for index, text in enumerate(texts)
    ]
    return JSONResponse(
        {
            "object": "list",
            "data": data,
            "model": body.get("model"),
            "usage": {"total_tokens": sum(len(text) // 3 + 1 for text in texts)},
        }
    )


async def release(request: Request) -> Response:
    state.released.add(request.path_params["key"])
    return Response(status_code=204)


async def health(request: Request) -> Response:
    del request
    return JSONResponse({"status": "ok"})


app: Final = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/v1/embeddings", embeddings, methods=["POST"]),
        Route("/release/{key}", release, methods=["POST"]),
    ]
)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("FAKE_VOYAGE_PORT", "8103")))


if __name__ == "__main__":
    main()
