"""A pending approval survives a real restart: the API process is killed hard during the pause, a
second one boots (and sweeps), leaves the run at `awaiting_approval`, takes the decision and
finishes the run. Real processes, because only a process that is gone proves that nothing waited
in memory: the API (`python -m app.main`) and the fake Anthropic with the `fixture` MCP server
(`python -m tests.fake_anthropic`), both on the test database. A synchronous child management under
an async test: Windows' selector loop cannot run asyncio subprocesses.

Windows ends only the venv launcher with `Popen.kill`, so the tree is stopped as
`tests/services/test_parse.py` does: `taskkill /F /T`.
"""

import asyncio
import contextlib
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final

import httpx
import jwt as pyjwt
import pytest

from app.config.env import env
from tests.fake_note import SERVER_NAME, TOOL_NAME
from tests.seed_ask_tool import seed
from tests.store import reset_store, store_backed

PACKAGE_ROOT: Final = Path(__file__).resolve().parents[1]
SECRET: Final = "restart-test-access-secret-0123456789abcdef"
BOOT_SECONDS: Final = 60.0
WAIT_SECONDS: Final = 30.0


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class Child:
    """One server process and everything under it."""

    def __init__(self, args: list[str], environment: dict[str, str]) -> None:
        self.process = subprocess.Popen(  # noqa: S603  # our own interpreter, fixed modules
            [sys.executable, *args],
            cwd=PACKAGE_ROOT,
            env={**os.environ, **environment, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
        )

    def kill(self) -> None:
        if self.process.poll() is not None:
            return
        if sys.platform == "win32":
            subprocess.run(  # noqa: S603
                ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],  # noqa: S607
                capture_output=True,
                check=False,
            )
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGKILL)
        self.process.wait(timeout=15)


def wait_for(url: str, seconds: float = BOOT_SECONDS) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with contextlib.suppress(httpx.HTTPError):
            if httpx.get(url, timeout=2).status_code == 200:
                return
        time.sleep(0.25)
    raise AssertionError(f"{url} did not answer in {seconds} s")


def access_token(user_id: str) -> str:
    now = int(time.time())
    claims = {
        "sub": user_id,
        "role": "user",
        "sid": str(uuid.uuid4()),
        "iat": now,
        "exp": now + 600,
    }
    return pyjwt.encode(claims, SECRET, algorithm="HS256")


class Servers:
    def __init__(self, api_port: int, model_port: int) -> None:
        self.api_port = api_port
        self.model_port = model_port
        self.api: Child | None = None
        self.model: Child | None = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    def start_model(self) -> None:
        self.model = Child(
            ["-m", "tests.fake_anthropic"], {"FAKE_ANTHROPIC_PORT": str(self.model_port)}
        )
        wait_for(f"http://127.0.0.1:{self.model_port}/health")

    def start_api(self) -> None:
        self.api = Child(
            ["-m", "app.main"],
            {
                "APP_ENV": "development",
                "PORT": str(self.api_port),
                "DATABASE_URL": env.database_url,
                "JWT_ACCESS_SECRET": SECRET,
                "RATE_LIMIT_SCALE": "100",
                "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{self.model_port}",
                "ANTHROPIC_API_KEY": "restart-test-placeholder-not-a-key",
                # Nothing listens here: `knowledge` is reported unavailable, which the run allows.
                "KNOWLEDGE_MCP_URL": f"http://127.0.0.1:{free_port()}/mcp",
            },
        )
        wait_for(f"{self.base}/api/health")

    def stop_all(self) -> None:
        for child in (self.api, self.model):
            if child is not None:
                child.kill()


@pytest.fixture
async def servers() -> AsyncIterator[Servers]:
    await reset_store()
    running = Servers(free_port(), free_port())
    await seed(f"http://127.0.0.1:{running.model_port}")
    try:
        running.start_model()
        running.start_api()
        yield running
    finally:
        running.stop_all()


async def poll_status(
    client: httpx.AsyncClient, conversation: str, wanted: str
) -> dict[str, object]:
    deadline = time.monotonic() + WAIT_SECONDS
    seen = ""
    while time.monotonic() < deadline:
        res = await client.get(f"/api/conversation/{conversation}")
        run = res.json().get("latestRun")
        seen = "" if run is None else str(run["status"])
        if seen == wanted:
            assert isinstance(run, dict)
            return run
        await asyncio.sleep(0.2)
    raise AssertionError(f"the run never reached {wanted}; last seen {seen!r}")


def events_of(text: str) -> list[dict[str, object]]:
    import json

    found = []
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                found.append(json.loads(line.removeprefix("data: ")))
    return found


@store_backed
class TestRealRestart:
    async def test_a_pending_approval_survives_a_hard_kill_and_the_run_finishes(
        self, servers: Servers
    ) -> None:
        headers = {"Authorization": f"Bearer {access_token(str(uuid.uuid4()))}"}
        async with httpx.AsyncClient(base_url=servers.base, headers=headers, timeout=30) as client:
            created = await client.post("/api/conversation")
            conversation = created.json()["id"]
            sent = await client.post(
                f"/api/conversation/{conversation}/message",
                json={"content": f"[[tool:{SERVER_NAME}__{TOOL_NAME}]]"},
            )
            run_id = sent.json()["run"]["id"]
            await poll_status(client, conversation, "awaiting_approval")
            requested = next(
                event
                for event in events_of((await client.get(f"/api/run/{run_id}/event")).text)
                if event["type"] == "approval_requested"
            )

            assert servers.api is not None
            servers.api.kill()
            servers.start_api()

            still = await poll_status(client, conversation, "awaiting_approval")
            decided = await client.post(
                f"/api/approval/{requested['approvalId']}/decision",
                json={"decision": "approved", "argumentsDigest": requested["argumentsDigest"]},
            )
            done = await poll_status(client, conversation, "completed")
            events = events_of((await client.get(f"/api/run/{run_id}/event")).text)

        assert still["id"] == run_id
        assert decided.status_code == 200
        assert done["id"] == run_id
        finished = [e for e in events if e["type"] == "tool_call_finished"]
        assert [(e["status"], e["output"]) for e in finished] == [("succeeded", "noted:hi")]
        assert events[-1]["type"] == "run_finished"
        assert events[-1]["status"] == "completed"
