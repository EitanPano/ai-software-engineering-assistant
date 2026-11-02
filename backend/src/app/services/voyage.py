"""voyage.py belongs: the Voyage AI client, the only caller of its embeddings API. It is paid
($0.12 per million tokens for `voyage-code-4`), so it is careful: a request is made only for texts
the index will store, `truncation` is off (a text over the model's context fails the call instead of
being silently cut), and a failure is retried a bounded number of times, only where it can help.

A request is at most `EMBEDDING.batch_texts` texts and about `EMBEDDING.batch_tokens` tokens
(Voyage publishes no per-request token limit for this model, so it stays under the 120,000 of the
previous one); the token count is estimated from the characters, erring high. A 429, a 5xx or a
transport failure is retried `ATTEMPTS` times in all with exponential backoff; any other answer
(a 400 for a text that is too long) is not, since the same request would fail the same way. A 429
on the index path waits what `Retry-After` says (whole seconds, at most two minutes; about a minute
with none usable), because the short backoff cannot outlast a per-minute limit and a failed index
embeds everything again. `embed_query` runs on a request path: 3 attempts, each phase of one
bounded by 5 s, the short backoff only, never a throttle's wait (the caller answers 503). After
that, and for an answer that is not what was asked for, `EmbeddingUnavailable` is raised with a
fixed message: no text, key or provider payload leaves this module.

It does not belong: deciding what to embed (the source controller) or storage.
"""

import asyncio
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import httpx2

from app.config.constants import EMBEDDING, SEARCH
from app.config.env import env
from app.services.logger import log

DEFAULT_BASE_URL: Final = "https://api.voyageai.com"
ATTEMPTS: Final = 4
_BASE_DELAY_SECONDS: Final = 0.5
_MAX_DELAY_SECONDS: Final = 4.0
_RETRYABLE: Final = frozenset({429, 500, 502, 503, 504})


class EmbeddingUnavailable(Exception):  # noqa: N818  # named for what the index reports
    """Voyage could not embed these texts: safe to try the whole index again later."""


_state: dict[str, httpx2.AsyncClient] = {}


def _client() -> httpx2.AsyncClient:
    client = _state.get("client")
    if client is None:
        # No timeout here: every request carries its budget's whole `httpx2.Timeout`.
        client = httpx2.AsyncClient(base_url=env.voyage_base_url or DEFAULT_BASE_URL)
        _state["client"] = client
    return client


def use_client(client: httpx2.AsyncClient | None) -> None:
    """Replaces the client (a test points it at the scripted fake); `None` forgets it."""
    if client is None:
        _state.pop("client", None)
    else:
        _state["client"] = client


async def pause(seconds: float) -> None:
    """Waits between two attempts; a test replaces it so retries cost no time."""
    await asyncio.sleep(seconds)


def _estimated_tokens(text: str) -> int:
    return len(text) // 2 + 1


def _batches(texts: Sequence[str]) -> list[list[str]]:
    batches: list[list[str]] = []
    current: list[str] = []
    tokens = 0
    for text in texts:
        cost = _estimated_tokens(text)
        if current and (
            len(current) >= EMBEDDING.batch_texts or tokens + cost > EMBEDDING.batch_tokens
        ):
            batches.append(current)
            current, tokens = [], 0
        current.append(text)
        tokens += cost
    if current:
        batches.append(current)
    return batches


async def embed_documents(texts: Sequence[str]) -> list[list[float]]:
    """One vector per text, in order, of `EMBEDDING.dimension` floats."""
    vectors: list[list[float]] = []
    for batch in _batches(texts):
        vectors += await _embed(batch)
    return vectors


async def embed_query(text: str) -> list[float]:
    """The vector of one search text, embedded with the model's query prompt. It runs on a request
    path, so it keeps a short budget (`SEARCH.embed_attempts` tries, each phase of a try bounded by
    `SEARCH.embed_attempt_seconds`) and never waits out a throttle: a 429 spends an attempt like
    any failure, and the caller answers 503."""
    budget = _Budget(
        attempts=SEARCH.embed_attempts,
        timeout=httpx2.Timeout(SEARCH.embed_attempt_seconds),
        waits_out_throttle=False,
    )
    return (await _embed([text], "query", budget))[0]


@dataclass(frozen=True)
class _Budget:
    attempts: int
    timeout: httpx2.Timeout
    # Only the index waits for a per-minute limit to lift; a request would hold its caller.
    waits_out_throttle: bool


_INDEX_BUDGET: Final = _Budget(
    attempts=ATTEMPTS, timeout=httpx2.Timeout(60.0, connect=10.0), waits_out_throttle=True
)
# What a 429 without a usable `Retry-After` waits, and the most it ever waits: the limits are per
# minute, and a failed index re-embeds everything.
_THROTTLE_DEFAULT_SECONDS: Final = 60.0
_THROTTLE_MAX_SECONDS: Final = 120.0
_SECONDS: Final = re.compile(r"[0-9]{1,6}")


def _throttle_wait(response: httpx2.Response) -> float:
    """What `Retry-After` says in seconds, at most two minutes; an HTTP-date or anything else
    counts as no usable header."""
    value = response.headers.get("retry-after", "").strip()
    if _SECONDS.fullmatch(value) is None:
        return _THROTTLE_DEFAULT_SECONDS
    return min(float(value), _THROTTLE_MAX_SECONDS)


async def _embed(
    batch: list[str], input_type: str = "document", budget: _Budget = _INDEX_BUDGET
) -> list[list[float]]:
    body = {
        "input": batch,
        "model": EMBEDDING.model,
        "input_type": input_type,
        "truncation": False,
        "output_dimension": EMBEDDING.dimension,
        "output_dtype": "float",
    }
    headers = {"Authorization": f"Bearer {env.voyage_api_key}"}
    for attempt in range(1, budget.attempts + 1):
        delay = min(_BASE_DELAY_SECONDS * 2 ** (attempt - 1), _MAX_DELAY_SECONDS)
        try:
            response = await _client().post(
                "/v1/embeddings", json=body, headers=headers, timeout=budget.timeout
            )
        except httpx2.HTTPError as error:
            log.warning("voyage unreachable", {"attempt": attempt, "reason": type(error).__name__})
        else:
            if response.status_code == 200:
                return _vectors(response, len(batch))
            log.warning("voyage refused", {"attempt": attempt, "status": response.status_code})
            if response.status_code not in _RETRYABLE:
                raise EmbeddingUnavailable("voyage rejected the request")
            if response.status_code == 429 and budget.waits_out_throttle:
                delay = max(delay, _throttle_wait(response))
        if attempt < budget.attempts:
            await pause(delay)
    raise EmbeddingUnavailable("voyage is unavailable")


def _vectors(response: httpx2.Response, expected: int) -> list[list[float]]:
    try:
        data = response.json()["data"]
        ordered = sorted(data, key=lambda item: item["index"])
        vectors = [[float(x) for x in item["embedding"]] for item in ordered]
    except ValueError, KeyError, TypeError, AttributeError:
        raise EmbeddingUnavailable("voyage answered something unexpected") from None
    if len(vectors) != expected or any(
        len(vector) != EMBEDDING.dimension or not all(math.isfinite(x) for x in vector)
        for vector in vectors
    ):
        raise EmbeddingUnavailable("voyage answered something unexpected")
    return vectors
