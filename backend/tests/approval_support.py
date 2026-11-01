"""Helpers for the approval suites: pause a run on a scripted `ask` tool, decide through the
endpoint, resume in process (the bus is not connected in a test, so nothing reacts to
`run.resumed`), and read the rows a pause writes."""

from dataclasses import dataclass

import httpx
import pytest

from app.api.agent.controller import resume_run
from app.services.db import execute, fetch_all, fetch_one
from app.services.event import drain
from tests.agent_support import Frame, stream
from tests.fake_mcp import Servers
from tests.test_agent import Journey, StoreBacked

ZERO_DIGEST = "0" * 64


class LabBacked(StoreBacked):
    """A clean store with `knowledge` and `lab` up and the scripted Voyage and GitHub: what a run
    that lists its servers needs. The test module imports the `mcp_servers` fixture."""

    @pytest.fixture(autouse=True)
    async def environment(self, mcp_servers: Servers, fakes: None) -> None:
        del mcp_servers, fakes

    @pytest.fixture
    def servers(self, mcp_servers: Servers) -> Servers:
        return mcp_servers


@dataclass(frozen=True)
class ApprovalRow:
    id: str
    run_id: str
    user_id: str
    arguments_digest: str
    decision: str | None
    decided_at: object


@dataclass(frozen=True)
class _Status:
    status: str


@dataclass(frozen=True)
class _Pending:
    pending_turn: dict[str, object] | None


async def approvals_of(run_id: str) -> list[ApprovalRow]:
    return await fetch_all(
        ApprovalRow,
        "select id, run_id, user_id, arguments_digest, decision, decided_at from approval "
        "where run_id = %s order by created_at, id",
        (run_id,),
    )


async def status_of(run_id: str) -> str:
    row = await fetch_one(_Status, "select status from run where id = %s", (run_id,))
    assert row is not None
    return row.status


async def pending_turn_of(run_id: str) -> dict[str, object] | None:
    row = await fetch_one(_Pending, "select pending_turn from run where id = %s", (run_id,))
    assert row is not None
    return row.pending_turn


def requested_in(frames: list[Frame]) -> list[Frame]:
    return [f for f in frames if f.event["type"] == "approval_requested"]


async def decide(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    approval_id: str,
    decision: str,
    digest: str,
) -> httpx.Response:
    return await client.post(
        f"/api/approval/{approval_id}/decision",
        headers=headers,
        json={"decision": decision, "argumentsDigest": digest},
    )


async def decide_all(
    journey: Journey, run_id: str, decision: str = "approved"
) -> list[httpx.Response]:
    """Decides every approval the stream shows as requested and not yet decided, as the owner."""
    frames = await stream(journey.client, journey.headers, run_id)
    done = {f.event["approvalId"] for f in frames if f.event["type"] == "approval_decided"}
    responses = []
    for frame in requested_in(frames):
        if frame.event["approvalId"] in done:
            continue
        responses.append(
            await decide(
                journey.client,
                journey.headers,
                str(frame.event["approvalId"]),
                decision,
                str(frame.event["argumentsDigest"]),
            )
        )
    return responses


async def resume(journey: Journey, run_id: str) -> list[Frame]:
    """What the `run.resumed` reaction does, in this task, then the whole stream."""
    await drain()
    await resume_run(run_id)
    return await stream(journey.client, journey.headers, run_id)


async def settle(journey: Journey, run_id: str, decision: str = "approved") -> list[Frame]:
    """Decides what waits and resumes the run."""
    for response in await decide_all(journey, run_id, decision):
        assert response.status_code == 200, response.text
    return await resume(journey, run_id)


async def set_row(statement: str, params: tuple[object, ...]) -> None:
    await execute(statement, params)
