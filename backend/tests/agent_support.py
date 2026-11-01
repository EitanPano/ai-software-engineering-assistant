"""Helpers for the conversation, run and agent suites: callers minted for the gates, the scripted
Anthropic fake reached in process, and a reader for the SSE stream."""

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import httpx2
import pytest
from anthropic import AsyncAnthropic
from starlette.types import Message, Receive, Scope, Send

from app.models.user.enums import UserRole
from app.services import anthropic as model_client
from app.services.security.jwt import AccessClaims, sign_access
from tests import fake_anthropic

type Json = dict[str, object]


def bearer(user_id: str | None = None) -> dict[str, str]:
    """A caller for the route gates, which read only the access token."""
    claims = AccessClaims(
        sub=user_id or str(uuid.uuid4()), role=UserRole.user, sid=str(uuid.uuid4())
    )
    return {"Authorization": f"Bearer {sign_access(claims).token}"}


class RecordingFake:
    """The fake, remembering the body of each request the SDK sent."""

    def __init__(self) -> None:
        self.requests: list[Json] = []
        # The `anthropic-beta` header of each request, split into its flags.
        self.betas: list[list[str]] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != "/v1/messages":
            await fake_anthropic.app(scope, receive, send)
            return
        header = next(
            (value.decode() for name, value in scope["headers"] if name == b"anthropic-beta"), ""
        )
        self.betas.append([flag.strip() for flag in header.split(",") if flag.strip()])
        chunks: list[bytes] = []
        more = True
        while more:
            message = await receive()
            chunks.append(message.get("body", b""))
            more = bool(message.get("more_body", False))
        body = b"".join(chunks)
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            self.requests.append(parsed)
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if sent:
                # After the body, the transport's own receive: it waits for the response to end,
                # then reports the disconnect, as a real server does.
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await fake_anthropic.app(scope, replay, send)


@pytest.fixture
async def fake_model() -> AsyncIterator[RecordingFake]:
    """The app's model client pointed at the scripted fake, with no delay between chunks."""
    fake_anthropic.timings["chunk_delay"] = 0
    recording = RecordingFake()
    transport = httpx2.ASGITransport(app=recording)
    http = httpx2.AsyncClient(transport=transport, base_url="http://fake")
    model_client.use_client(
        AsyncAnthropic(api_key="test", base_url="http://fake", http_client=http, max_retries=0)
    )
    try:
        yield recording
    finally:
        model_client.use_client(None)
        fake_anthropic.timings["chunk_delay"] = 0.01
        await http.aclose()


@dataclass(frozen=True)
class Frame:
    id: int
    event: Json


def frames_of(response: httpx.Response) -> list[Frame]:
    """The SSE frames of a finished stream: each has an `id:` and a JSON `data:`."""
    found: list[Frame] = []
    for block in response.text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "data" in fields:
            payload = json.loads(fields["data"])
            assert isinstance(payload, dict)
            found.append(Frame(id=int(fields["id"]), event=payload))
    return found


async def start_conversation(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    res = await client.post("/api/conversation", headers=headers)
    assert res.status_code == 201
    return str(res.json()["id"])


async def send(
    client: httpx.AsyncClient, headers: dict[str, str], conversation_id: str, content: str
) -> str:
    """Sends a message; with the bus not connected nothing executes the run. Returns its id."""
    res = await client.post(
        f"/api/conversation/{conversation_id}/message", headers=headers, json={"content": content}
    )
    assert res.status_code == 201, res.text
    return str(res.json()["run"]["id"])


async def stream(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    run_id: str,
    last_event_id: int | None = None,
) -> list[Frame]:
    extra = {} if last_event_id is None else {"Last-Event-ID": str(last_event_id)}
    res = await client.get(f"/api/run/{run_id}/event", headers={**headers, **extra})
    assert res.status_code == 200, res.text
    return frames_of(res)


def types_of(frames: list[Frame]) -> list[object]:
    return [frame.event["type"] for frame in frames]
