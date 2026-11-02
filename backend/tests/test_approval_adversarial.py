"""QA attacks on the approval decision: repeated rapid submission, racing opposite decisions,
malformed bodies, and a decision that must never reach a tool twice."""

import asyncio

import httpx
import pytest

from app.models.tool_policy.enums import PolicyEffect
from tests.agent_support import RecordingFake
from tests.approval_support import LabBacked, approvals_of, decide, resume, status_of
from tests.fake_mcp import Servers
from tests.fake_mcp import mcp_servers as mcp_servers
from tests.store import store_backed
from tests.support import error_of
from tests.test_agent import Journey

ASK = {"echo": PolicyEffect.ask}


@store_backed
class TestApprovalAttacks(LabBacked):
    async def _paused(
        self, client: httpx.AsyncClient, servers: Servers
    ) -> tuple[Journey, str, dict[str, object]]:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, frames = await journey.run("[[tool:lab__echo]]")
        asked = next(f for f in frames if f.event["type"] == "approval_requested")
        return journey, run_id, asked.event

    async def test_ten_rapid_identical_approvals_decide_once_and_run_the_tool_once(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        journey, run_id, asked = await self._paused(client, servers)

        responses = await asyncio.gather(
            *(
                decide(
                    client,
                    journey.headers,
                    str(asked["approvalId"]),
                    "approved",
                    str(asked["argumentsDigest"]),
                )
                for _ in range(10)
            )
        )
        await resume(journey, run_id)

        codes = sorted(r.status_code for r in responses)
        assert codes == [200] + [409] * 9
        assert servers.lab.calls == [("echo", {"text": "hi"})]
        assert await status_of(run_id) == "completed"

    async def test_an_approve_and_a_reject_racing_leave_one_winner(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        journey, run_id, asked = await self._paused(client, servers)

        responses = await asyncio.gather(
            *(
                decide(
                    client,
                    journey.headers,
                    str(asked["approvalId"]),
                    decision,
                    str(asked["argumentsDigest"]),
                )
                for decision in ("approved", "rejected")
            )
        )

        assert sorted(r.status_code for r in responses) == [200, 409]
        winner = next(r for r in responses if r.status_code == 200).json()["decision"]
        (row,) = await approvals_of(run_id)
        assert row.decision == winner

    @pytest.mark.parametrize(
        "payload",
        [{}, {"decision": "approved"}, {"argumentsDigest": "a" * 64}, [], "approved", None],
    )
    async def test_a_malformed_body_is_a_400_and_decides_nothing(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
        payload: object,
    ) -> None:
        journey, run_id, asked = await self._paused(client, servers)

        res = await client.post(
            f"/api/approval/{asked['approvalId']}/decision", headers=journey.headers, json=payload
        )

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"
        assert (await approvals_of(run_id))[0].decision is None
        assert await status_of(run_id) == "awaiting_approval"
        assert servers.lab.calls == []

    async def test_a_body_that_is_not_json_is_a_400_and_decides_nothing(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        journey, run_id, asked = await self._paused(client, servers)

        res = await client.post(
            f"/api/approval/{asked['approvalId']}/decision",
            headers={**journey.headers, "content-type": "application/json"},
            content=b"{not json",
        )

        assert res.status_code == 400
        assert (await approvals_of(run_id))[0].decision is None

    async def test_a_very_long_id_is_a_404_not_a_500(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        journey, _, asked = await self._paused(client, servers)

        res = await decide(
            client, journey.headers, "x" * 5000, "approved", str(asked["argumentsDigest"])
        )

        assert res.status_code in (404, 400)
        assert servers.lab.calls == []

    async def test_a_rejection_after_a_rejection_never_reaches_the_tool(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        journey, run_id, asked = await self._paused(client, servers)
        args = (journey.headers, str(asked["approvalId"]))

        first = await decide(client, args[0], args[1], "rejected", str(asked["argumentsDigest"]))
        again = await decide(client, args[0], args[1], "approved", str(asked["argumentsDigest"]))
        await resume(journey, run_id)

        assert (first.status_code, again.status_code) == (200, 409)
        assert servers.lab.calls == []
