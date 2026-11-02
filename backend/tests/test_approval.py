import asyncio

import httpx
import pytest
from pydantic import ValidationError

from app.api.approval.schema import Approval, DecideApprovalBody
from app.infra.pubsub import pubsub
from app.models.approval.enums import ApprovalDecision
from app.models.tool_policy.enums import PolicyEffect
from app.services.event import RUN_RESUMED, drain, subscribe
from tests.agent_support import RecordingFake, bearer, stream
from tests.approval_support import (
    ZERO_DIGEST,
    LabBacked,
    approvals_of,
    decide,
    requested_in,
    set_row,
    status_of,
)
from tests.fake_mcp import Servers
from tests.fake_mcp import mcp_servers as mcp_servers
from tests.source_support import admin_bearer
from tests.store import store_backed
from tests.support import error_of
from tests.test_agent import Journey, finish_of

DIGEST = "a" * 64


class TestDecideApprovalBody:
    """The request-schema rules of `POST /api/approval/{id}/decision`."""

    @pytest.mark.parametrize("decision", ["approved", "rejected"])
    def test_accepts_each_decision(self, decision: str) -> None:
        body = DecideApprovalBody.model_validate({"decision": decision, "argumentsDigest": DIGEST})

        assert body.decision == decision
        assert body.arguments_digest == DIGEST

    @pytest.mark.parametrize("decision", ["approve", "reject", "Approved", "", None, 1, True])
    def test_rejects_a_decision_outside_the_set(self, decision: object) -> None:
        with pytest.raises(ValidationError):
            DecideApprovalBody.model_validate({"decision": decision, "argumentsDigest": DIGEST})

    def test_requires_the_decision(self) -> None:
        with pytest.raises(ValidationError):
            DecideApprovalBody.model_validate({"argumentsDigest": DIGEST})

    def test_requires_the_digest(self) -> None:
        with pytest.raises(ValidationError):
            DecideApprovalBody.model_validate({"decision": "approved"})

    @pytest.mark.parametrize(
        "digest",
        [
            "",
            "a" * 63,
            "a" * 65,
            "A" * 64,
            "g" * 64,
            "a" * 63 + "\n",
            chr(0x661) * 64,
            " " + "a" * 63,
            None,
            12,
        ],
    )
    def test_rejects_a_digest_that_is_not_64_lowercase_hex_characters(self, digest: object) -> None:
        with pytest.raises(ValidationError):
            DecideApprovalBody.model_validate({"decision": "approved", "argumentsDigest": digest})

    def test_has_no_reason(self) -> None:
        body = DecideApprovalBody.model_validate(
            {"decision": "rejected", "argumentsDigest": DIGEST, "reason": "no"}
        )

        assert not hasattr(body, "reason")


class TestApprovalResponse:
    def test_is_the_four_fields_on_the_wire(self) -> None:
        approval = Approval(
            id="a1",
            tool_use_id="toolu_1",
            decision="approved",
            decided_at="2026-11-01T00:00:00.000Z",
        )

        assert approval.model_dump(by_alias=True) == {
            "id": "a1",
            "toolUseId": "toolu_1",
            "decision": "approved",
            "decidedAt": "2026-11-01T00:00:00.000Z",
        }


class TestApprovalDecision:
    def test_is_approved_or_rejected(self) -> None:
        assert {member.value for member in ApprovalDecision} == {"approved", "rejected"}


ASK = {"echo": PolicyEffect.ask}


@store_backed
class TestDecisionEndpoint(LabBacked):
    async def test_answers_the_decision_in_its_shape(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, frames = await journey.run("[[tool:lab__echo]]")
        (asked,) = requested_in(frames)

        res = await decide(
            client,
            journey.headers,
            str(asked.event["approvalId"]),
            "approved",
            str(asked.event["argumentsDigest"]),
        )

        assert res.status_code == 200
        body = res.json()
        assert set(body) == {"id", "toolUseId", "decision", "decidedAt"}
        assert body["id"] == asked.event["approvalId"]
        assert body["toolUseId"] == asked.event["toolUseId"]
        assert body["decision"] == "approved"
        assert body["decidedAt"].endswith("Z")
        assert (await approvals_of(run_id))[0].decision == "approved"

    async def test_a_bad_body_is_a_400_naming_the_field(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        _, frames = await journey.run("[[tool:lab__echo]]")

        res = await client.post(
            f"/api/approval/{frames[2].event['approvalId']}/decision",
            headers=journey.headers,
            json={"decision": "approved", "argumentsDigest": "XYZ"},
        )

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"
        assert res.json()["requestId"]
        assert any("argumentsDigest" in detail.path for detail in error_of(res).details)

    async def test_no_token_is_a_401(self, client: httpx.AsyncClient) -> None:
        res = await client.post(
            "/api/approval/x/decision", json={"decision": "approved", "argumentsDigest": DIGEST}
        )

        assert res.status_code == 401
        assert error_of(res).code == "unauthenticated"

    async def test_a_missing_id_is_a_404(self, client: httpx.AsyncClient) -> None:
        res = await decide(client, bearer(), "missing", "approved", DIGEST)

        assert res.status_code == 404
        assert error_of(res).code == "not_found"

    @pytest.mark.parametrize("caller", ["another user", "an admin"])
    async def test_another_users_approval_is_a_404_and_stays_undecided(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
        caller: str,
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, frames = await journey.run("[[tool:lab__echo]]")
        headers = bearer() if caller == "another user" else admin_bearer()

        res = await decide(
            client,
            headers,
            str(frames[2].event["approvalId"]),
            "approved",
            str(frames[2].event["argumentsDigest"]),
        )

        assert res.status_code == 404
        assert (await approvals_of(run_id))[0].decision is None
        assert await status_of(run_id) == "awaiting_approval"

    async def test_a_second_decision_is_a_409(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        _, frames = await journey.run("[[tool:lab__echo]]")
        approval_id = str(frames[2].event["approvalId"])
        digest = str(frames[2].event["argumentsDigest"])
        first = await decide(client, journey.headers, approval_id, "rejected", digest)

        again = await decide(client, journey.headers, approval_id, "approved", digest)

        assert first.status_code == 200
        assert again.status_code == 409
        assert error_of(again).code == "conflict"

    async def test_a_wrong_digest_is_a_409(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        _, frames = await journey.run("[[tool:lab__echo]]")

        res = await decide(
            client, journey.headers, str(frames[2].event["approvalId"]), "approved", ZERO_DIGEST
        )

        assert res.status_code == 409

    async def test_a_decision_for_a_run_that_no_longer_waits_is_a_409(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, frames = await journey.run("[[tool:lab__echo]]")
        await set_row("update run set status = 'failed' where id = %s", (run_id,))

        res = await decide(
            client,
            journey.headers,
            str(frames[2].event["approvalId"]),
            "approved",
            str(frames[2].event["argumentsDigest"]),
        )

        assert res.status_code == 409
        assert (await approvals_of(run_id))[0].decision is None

    async def test_two_concurrent_last_decisions_resume_the_run_once(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(
            {"echo": PolicyEffect.ask, "lookup": PolicyEffect.ask, "loose": PolicyEffect.allow}
        )
        journey = Journey(client)
        run_id, frames = await journey.run("[[trio]]")
        resumed: list[object] = []
        unsubscribe = subscribe(RUN_RESUMED, resumed.append)

        try:
            responses = await asyncio.gather(
                *(
                    decide(
                        client,
                        journey.headers,
                        str(asked.event["approvalId"]),
                        "approved",
                        str(asked.event["argumentsDigest"]),
                    )
                    for asked in requested_in(frames)
                )
            )
            await drain()
        finally:
            unsubscribe()

        assert [r.status_code for r in responses] == [200, 200]
        assert resumed == [{"run_id": run_id}]
        assert await status_of(run_id) == "running"

    async def test_a_send_during_a_pause_is_a_409_that_stores_nothing(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        await journey.run("[[tool:lab__echo]]")
        before = await client.get(
            f"/api/conversation/{journey.conversation}/message", headers=journey.headers
        )

        res = await client.post(
            f"/api/conversation/{journey.conversation}/message",
            headers=journey.headers,
            json={"content": "and another thing"},
        )

        after = await client.get(
            f"/api/conversation/{journey.conversation}/message", headers=journey.headers
        )
        assert res.status_code == 409
        assert error_of(res).code == "conflict"
        assert after.json() == before.json()

    async def test_the_bus_resumes_a_run_after_its_last_decision(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, frames = await journey.run("[[tool:lab__echo]]")
        await pubsub.connect()
        try:
            await decide(
                client,
                journey.headers,
                str(frames[2].event["approvalId"]),
                "approved",
                str(frames[2].event["argumentsDigest"]),
            )
            await drain()
            done = await stream(client, journey.headers, run_id)
        finally:
            await pubsub.close()

        assert finish_of(done).event["status"] == "completed"
        assert servers.lab.calls == [("echo", {"text": "hi"})]
