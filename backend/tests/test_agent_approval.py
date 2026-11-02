"""A tool call whose policy says `ask` stops its run at `awaiting_approval`, runs only after a
person approves, reaches the model as a rejection otherwise, and survives a lost process. The model
is `tests/fake_anthropic.py`, the servers `tests/fake_mcp.py`'s `lab`; the bus is not connected, so
`tests/approval_support.py` `resume` does what the `run.resumed` reaction does."""

import asyncio
import json
import re

import httpx
import pytest

from app.api.agent.controller import _DENIED_OUTPUT, _REJECTED_OUTPUT, resume_run
from app.api.conversation.controller import read_history
from app.api.run.controller import fail_lost_runs
from app.config.constants import AGENT_MAX_TURNS, AGENT_TOOL_CALLS_PER_RUN
from app.models.tool_policy.enums import PolicyEffect
from app.services import tool
from app.services.event import drain
from app.services.utils import clock
from tests import fake_anthropic
from tests.agent_support import RecordingFake, stream, types_of
from tests.approval_support import (
    ZERO_DIGEST,
    LabBacked,
    approvals_of,
    decide,
    decide_all,
    pending_turn_of,
    requested_in,
    resume,
    set_row,
    settle,
    status_of,
)
from tests.fake_mcp import Servers
from tests.fake_mcp import mcp_servers as mcp_servers
from tests.store import store_backed
from tests.test_agent import Journey, finish_of, text_of
from tests.test_agent_knowledge import calls_of, events_named

ASK = {"echo": PolicyEffect.ask}


def results_of(request: dict[str, object]) -> list[dict[str, object]]:
    """The `tool_result` blocks of the request's last message."""
    messages = request["messages"]
    assert isinstance(messages, list)
    last = messages[-1]
    assert last["role"] == "user"
    return [block for block in last["content"] if block["type"] == "tool_result"]


async def conversation_status(journey: Journey) -> str:
    res = await journey.client.get(
        f"/api/conversation/{journey.conversation}", headers=journey.headers
    )
    assert res.status_code == 200
    return str(res.json()["latestRun"]["status"])


@store_backed
class TestPause(LabBacked):
    async def test_an_ask_call_stops_the_run_and_reaches_no_server(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)

        run_id, frames = await journey.run("[[tool:lab__echo]]")

        assert types_of(frames) == ["run_started", "tool_call_started", "approval_requested"]
        assert frames[1].event["input"] == {"text": "hi"}
        assert frames[2].event["toolUseId"] == frames[1].event["toolUseId"]
        assert servers.lab.calls == []
        assert await conversation_status(journey) == "awaiting_approval"
        (call,) = await calls_of(run_id)
        assert (call.status, call.result, call.arguments) == (
            "awaiting_approval",
            "",
            {"text": "hi"},
        )
        (approval,) = await approvals_of(run_id)
        assert approval.decision is None
        assert approval.id == frames[2].event["approvalId"]
        assert approval.arguments_digest == frames[2].event["argumentsDigest"]
        assert approval.arguments_digest == tool.arguments_digest({"text": "hi"})
        assert len(fake_model.requests) == 1

    async def test_the_assistant_turn_waits_in_the_pending_turn_not_in_the_history(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)

        run_id, _ = await journey.run("[[tool:lab__echo]]")

        history = await read_history(journey.conversation)
        assert [turn.role for turn in history] == ["user"]
        pending = await pending_turn_of(run_id)
        assert pending is not None
        content = pending["content"]
        assert isinstance(content, list)
        assert [block["type"] for block in content] == ["tool_use"]
        assert pending["results"] == []

    @pytest.mark.parametrize(
        ("effects", "default"),
        [({"echo": PolicyEffect.deny}, PolicyEffect.ask), (None, None)],
        ids=["deny", "no row"],
    )
    async def test_a_denied_call_is_answered_with_no_question(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
        effects: dict[str, PolicyEffect] | None,
        default: PolicyEffect | None,
    ) -> None:
        await servers.register_lab(effects, default=default)
        journey = Journey(client)

        run_id, frames = await journey.run("[[tool:lab__echo]]")

        assert "approval_requested" not in types_of(frames)
        assert frames[2].event["status"] == "denied"
        assert finish_of(frames).event["status"] == "completed"
        assert await approvals_of(run_id) == []

    async def test_an_invalid_input_is_answered_with_no_question(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)

        run_id, frames = await journey.run("[[badtool:lab__echo]]")

        assert "approval_requested" not in types_of(frames)
        assert frames[2].event["status"] == "failed"
        assert await approvals_of(run_id) == []
        assert servers.lab.calls == []

    async def test_a_tool_the_conversation_was_not_offered_is_answered_with_no_question(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        journey = Journey(client)
        await journey.run("hello")  # freezes the prefix before `lab` exists
        await servers.register_lab(ASK)

        run_id, frames = await journey.run("[[tool:lab__echo]]")

        assert "approval_requested" not in types_of(frames)
        assert events_named(frames, "tool_call_finished")[0].event["status"] == "denied"
        assert await approvals_of(run_id) == []
        assert servers.lab.calls == []

    async def test_a_call_past_the_budget_is_answered_with_no_question(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)

        run_id, frames = await journey.run("[[many:lab__echo]]")

        asked = requested_in(frames)
        assert len(asked) == AGENT_TOOL_CALLS_PER_RUN
        finished = events_named(frames, "tool_call_finished")
        assert [f.event["status"] for f in finished] == ["denied"] * (
            fake_anthropic.MANY_CALLS - AGENT_TOOL_CALLS_PER_RUN
        )
        assert len(await calls_of(run_id)) == fake_anthropic.MANY_CALLS
        assert await status_of(run_id) == "awaiting_approval"


@store_backed
class TestApprove(LabBacked):
    async def test_the_approved_call_runs_once_with_its_stored_arguments(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")

        frames = await settle(journey, run_id)

        assert servers.lab.calls == [("echo", {"text": "hi"})]
        assert types_of(frames) == [
            "run_started",
            "tool_call_started",
            "approval_requested",
            "approval_decided",
            "tool_call_finished",
            "text_delta",
            "run_finished",
        ]
        assert frames[3].event["decision"] == "approved"
        assert frames[4].event["status"] == "succeeded"
        assert frames[4].event["output"] == "echo:hi"
        assert text_of(frames) == "Tool done."
        assert finish_of(frames).event["status"] == "completed"
        (call,) = await calls_of(run_id)
        assert (call.status, call.result) == ("succeeded", "echo:hi")
        (result,) = results_of(fake_model.requests[1])
        assert (result["content"], result["is_error"]) == ("echo:hi", False)
        history = await read_history(journey.conversation)
        assert [turn.role for turn in history] == ["user", "assistant", "user", "assistant"]

    async def test_a_second_pause_in_one_run_works(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[twice:lab__echo]]")

        paused = await settle(journey, run_id)

        assert await status_of(run_id) == "awaiting_approval"
        assert len(requested_in(paused)) == 2
        done = await settle(journey, run_id)

        assert finish_of(done).event["status"] == "completed"
        assert servers.lab.calls == [("echo", {"text": "hi"}), ("echo", {"text": "hi2"})]

    async def test_the_same_tool_with_other_arguments_needs_its_own_approval(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[twice:lab__echo]]")
        await settle(journey, run_id)

        first, second = await approvals_of(run_id)

        assert first.decision == "approved"
        assert second.decision is None
        assert first.arguments_digest != second.arguments_digest
        assert servers.lab.calls == [("echo", {"text": "hi"})]


@store_backed
class TestMixedTurn(LabBacked):
    async def test_the_other_calls_run_at_once_and_every_result_returns_in_the_models_order(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(
            {"echo": PolicyEffect.allow, "lookup": PolicyEffect.ask, "loose": PolicyEffect.deny}
        )
        journey = Journey(client)

        run_id, frames = await journey.run("[[trio]]")

        assert servers.lab.calls == [("echo", {"text": "a"})]
        assert len(requested_in(frames)) == 1
        assert len(events_named(frames, "tool_call_finished")) == 2
        assert await status_of(run_id) == "awaiting_approval"
        done = await settle(journey, run_id)

        assert finish_of(done).event["status"] == "completed"
        assert servers.lab.calls == [("echo", {"text": "a"}), ("lookup", {"text": "a"})]
        results = results_of(fake_model.requests[1])
        assistant = fake_model.requests[1]["messages"][-2]["content"]  # type: ignore[index]
        asked = [block["id"] for block in assistant if block["type"] == "tool_use"]
        assert [r["tool_use_id"] for r in results] == asked
        assert [r["content"] for r in results] == ["echo:a", "echo:a", _DENIED_OUTPUT]

    async def test_the_run_resumes_after_the_last_decision_only(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(
            {"echo": PolicyEffect.ask, "lookup": PolicyEffect.ask, "loose": PolicyEffect.allow}
        )
        journey = Journey(client)
        run_id, frames = await journey.run("[[trio]]")
        first, second = requested_in(frames)

        one = await decide(
            client,
            journey.headers,
            str(first.event["approvalId"]),
            "approved",
            str(first.event["argumentsDigest"]),
        )

        assert one.status_code == 200
        assert await status_of(run_id) == "awaiting_approval"
        send = await client.post(
            f"/api/conversation/{journey.conversation}/message",
            headers=journey.headers,
            json={"content": "hello"},
        )
        assert send.status_code == 409
        two = await decide(
            client,
            journey.headers,
            str(second.event["approvalId"]),
            "rejected",
            str(second.event["argumentsDigest"]),
        )
        assert two.status_code == 200
        assert await status_of(run_id) == "running"
        done = await resume(journey, run_id)
        assert finish_of(done).event["status"] == "completed"
        assert servers.lab.calls == [("loose", {"text": "a"}), ("echo", {"text": "a"})]


@store_backed
class TestBudget(LabBacked):
    async def test_the_turn_limit_holds_across_resumes(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[loop]][[tool:lab__echo]]")

        for _ in range(AGENT_MAX_TURNS):
            assert await status_of(run_id) == "awaiting_approval"
            frames = await settle(journey, run_id)

        assert finish_of(frames).event["status"] == "failed"
        assert finish_of(frames).event["errorCode"] == "turn_limit"
        assert len(fake_model.requests) == AGENT_MAX_TURNS
        assert len(await approvals_of(run_id)) == AGENT_MAX_TURNS

    async def test_the_tool_call_limit_holds_across_resumes_and_counts_denied_calls(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("app.api.agent.controller.AGENT_TOOL_CALLS_PER_RUN", 2)
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[loop]][[tool:lab__echo]]")

        await settle(journey, run_id)
        frames = await settle(journey, run_id)

        assert finish_of(frames).event["errorCode"] == "turn_limit"
        assert len(await approvals_of(run_id)) == 2
        statuses = [call.status for call in await calls_of(run_id)]
        assert statuses.count("succeeded") == 2
        assert statuses.count("denied") == AGENT_MAX_TURNS - 2
        assert len(servers.lab.calls) == 2


@store_backed
class TestReject(LabBacked):
    async def test_a_rejection_reaches_the_model_as_a_fixed_error_and_the_run_goes_on(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")

        frames = await settle(journey, run_id, "rejected")

        assert servers.lab.calls == []
        assert frames[3].event["decision"] == "rejected"
        assert frames[4].event["status"] == "denied"
        assert frames[4].event["output"] == _REJECTED_OUTPUT
        (result,) = results_of(fake_model.requests[1])
        assert (result["content"], result["is_error"]) == (_REJECTED_OUTPUT, True)
        assert len({_REJECTED_OUTPUT, _DENIED_OUTPUT}) == 2
        assert "hi" not in _REJECTED_OUTPUT.split()
        (call,) = await calls_of(run_id)
        assert (call.status, call.result) == ("denied", _REJECTED_OUTPUT)
        assert finish_of(frames).event["status"] == "completed"
        assert text_of(frames) == "Tool done."


@store_backed
class TestLostDecision(LabBacked):
    async def test_a_waiting_run_survives_the_boot_sweep(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")

        failed = await fail_lost_runs(clock.now())

        assert failed == 0
        assert await status_of(run_id) == "awaiting_approval"

    async def test_a_run_lost_after_the_last_decision_ends_interrupted_and_runs_nothing(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")
        for response in await decide_all(journey, run_id):
            assert response.status_code == 200
        assert await status_of(run_id) == "running"

        failed = await fail_lost_runs(clock.now())

        assert failed == 1
        frames = await stream(client, journey.headers, run_id)
        assert finish_of(frames).event["errorCode"] == "interrupted"
        assert servers.lab.calls == []


@store_backed
class TestResumeClaim(LabBacked):
    """`resume_run` claims the pending turn in one statement and does nothing without it."""

    async def test_an_ended_run_reaches_no_server_and_writes_nothing(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")
        for response in await decide_all(journey, run_id):
            assert response.status_code == 200
        await fail_lost_runs(clock.now())
        before = types_of(await stream(client, journey.headers, run_id))
        turns = len(await read_history(journey.conversation))

        await resume_run(run_id)

        assert servers.lab.calls == []
        assert len(await read_history(journey.conversation)) == turns
        assert types_of(await stream(client, journey.headers, run_id)) == before
        assert await status_of(run_id) == "failed"

    async def test_one_flip_delivered_twice_runs_the_tool_and_stores_the_turns_once(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")
        for response in await decide_all(journey, run_id):
            assert response.status_code == 200
        await drain()

        await asyncio.gather(resume_run(run_id), resume_run(run_id))

        assert servers.lab.calls == [("echo", {"text": "hi"})]
        history = await read_history(journey.conversation)
        assert [turn.role for turn in history] == ["user", "assistant", "user", "assistant"]
        frames = await stream(client, journey.headers, run_id)
        assert len(events_named(frames, "run_finished")) == 1
        assert len(events_named(frames, "tool_call_finished")) == 1

    async def test_a_paused_turn_lacking_an_answer_fails_internal_before_any_server_is_reached(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")
        await set_row(
            "update run set pending_turn = jsonb_set(pending_turn, '{content}', "
            "(pending_turn->'content') || %s::jsonb) where id = %s",
            (
                json.dumps(
                    [{"type": "tool_use", "id": "toolu_gone", "name": "lab__echo", "input": {}}]
                ),
                run_id,
            ),
        )

        frames = await settle(journey, run_id)

        assert servers.lab.calls == []
        assert finish_of(frames).event["status"] == "failed"
        assert finish_of(frames).event["errorCode"] == "internal"
        assert [turn.role for turn in await read_history(journey.conversation)] == ["user"]

    async def test_an_undecided_approval_is_denied_with_the_policy_text_and_never_runs(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(
            {"echo": PolicyEffect.ask, "lookup": PolicyEffect.ask, "loose": PolicyEffect.allow}
        )
        journey = Journey(client)
        run_id, frames = await journey.run("[[trio]]")
        first, _ = requested_in(frames)
        res = await decide(
            client,
            journey.headers,
            str(first.event["approvalId"]),
            "approved",
            str(first.event["argumentsDigest"]),
        )
        assert res.status_code == 200
        # The flip a database write could fake: running again with one approval undecided.
        await set_row("update run set status = 'running' where id = %s", (run_id,))

        await resume_run(run_id)

        assert ("lookup", {"text": "a"}) not in servers.lab.calls
        done = await stream(client, journey.headers, run_id)
        denied = [
            f for f in events_named(done, "tool_call_finished") if f.event["status"] == "denied"
        ]
        assert [f.event["output"] for f in denied] == [_DENIED_OUTPUT]

    @pytest.mark.parametrize(
        "pending",
        ['{"content": "gone", "results": []}', "{}", '{"content": [], "results": []}'],
        ids=["content not a list", "empty object", "no tool_use"],
    )
    async def test_an_unreadable_pending_turn_fails_internal_and_stores_no_turn(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
        pending: str,
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")
        await set_row("update run set pending_turn = %s::jsonb where id = %s", (pending, run_id))

        frames = await settle(journey, run_id)

        assert servers.lab.calls == []
        assert finish_of(frames).event["errorCode"] == "internal"
        assert [turn.role for turn in await read_history(journey.conversation)] == ["user"]

    async def test_a_model_failure_on_the_turn_after_a_resume_ends_upstream_unavailable(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]][[stream_error]]")

        frames = await settle(journey, run_id)

        assert servers.lab.calls == [("echo", {"text": "hi"})]
        assert finish_of(frames).event["status"] == "failed"
        assert finish_of(frames).event["errorCode"] == "upstream_unavailable"


@store_backed
class TestBinding(LabBacked):
    @pytest.mark.parametrize(
        "changed",
        [
            "update tool_call set mcp_server_id = 'knowledge' where run_id = %s",
            "update tool_call set tool_name = 'lookup' where run_id = %s",
        ],
        ids=["server", "tool"],
    )
    async def test_a_row_naming_another_server_or_tool_is_denied_at_execution(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
        changed: str,
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")
        await set_row(changed, (run_id,))

        frames = await settle(journey, run_id)

        assert servers.lab.calls == []
        assert frames[4].event["status"] == "denied"
        assert frames[4].event["output"] == _DENIED_OUTPUT

    async def test_a_different_digest_is_a_409_that_runs_nothing(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, frames = await journey.run("[[tool:lab__echo]]")

        res = await decide(
            client, journey.headers, str(frames[2].event["approvalId"]), "approved", ZERO_DIGEST
        )

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "conflict"
        assert (await approvals_of(run_id))[0].decision is None
        assert await status_of(run_id) == "awaiting_approval"
        assert servers.lab.calls == []

    async def test_arguments_changed_after_the_request_are_denied_at_execution(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")
        await set_row(
            "update tool_call set arguments = %s::jsonb where run_id = %s",
            (json.dumps({"text": "other"}), run_id),
        )

        frames = await settle(journey, run_id)

        assert servers.lab.calls == []
        assert frames[4].event["status"] == "denied"
        assert frames[4].event["output"] == _DENIED_OUTPUT

    async def test_a_policy_turned_deny_is_denied_at_execution(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")
        await set_row("update tool_policy set effect = 'deny' where id = %s", ("lab-echo",))

        frames = await settle(journey, run_id)

        assert servers.lab.calls == []
        assert frames[4].event["status"] == "denied"
        assert finish_of(frames).event["status"] == "completed"

    async def test_a_disabled_server_is_denied_at_execution(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab(ASK)
        journey = Journey(client)
        run_id, _ = await journey.run("[[tool:lab__echo]]")
        await set_row("update mcp_server set enabled = false where id = %s", ("lab",))

        frames = await settle(journey, run_id)

        assert servers.lab.calls == []
        assert frames[4].event["status"] == "denied"


def signed(requests: list[dict[str, object]], index: int) -> dict[str, object]:
    """A request without the ids the fake generates, so two runs compare."""
    text = json.dumps(
        {key: requests[index][key] for key in ("system", "tools", "messages")}, sort_keys=True
    )
    ids = list(dict.fromkeys(re.findall(r"toolu_[0-9a-f]+", text)))
    for position, identifier in enumerate(ids):
        text = text.replace(identifier, f"ID{position}")
    parsed = json.loads(text)
    assert isinstance(parsed, dict)
    return parsed


@store_backed
class TestThinkingReplay(LabBacked):
    @pytest.mark.parametrize(
        ("script", "first_block"),
        [
            ("[[think]][[tool:lab__echo]]", "thinking"),
            # The thinking and the stored `tool_use` before the `fallback` are dropped at send.
            ("[[think]][[fallback_tool:lab__echo]]", "fallback"),
        ],
    )
    async def test_a_resumed_run_sends_what_the_unpaused_script_sends(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        servers: Servers,
        script: str,
        first_block: str,
    ) -> None:
        await servers.register_lab({"echo": PolicyEffect.allow})
        unpaused = Journey(client)
        await unpaused.run(script)
        reference = signed(fake_model.requests, 1)
        fake_model.requests.clear()
        await set_row("update tool_policy set effect = 'ask' where id = %s", ("lab-echo",))
        paused = Journey(client)
        run_id, _ = await paused.run(script)

        frames = await settle(paused, run_id)

        assert finish_of(frames).event["status"] == "completed"
        assert signed(fake_model.requests, 1) == reference
        resumed = fake_model.requests[1]
        assert resumed["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "error"}  # type: ignore[index]
        assistant = resumed["messages"][1]["content"]  # type: ignore[index]
        assert assistant[0]["type"] == first_block
        assert servers.lab.calls.count(("echo", {"text": "hi"})) == 2


@store_backed
class TestFakeBinding(LabBacked):
    async def test_the_fake_refuses_an_edited_prefix_and_an_unanswered_tool_use(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, servers: Servers
    ) -> None:
        await servers.register_lab({"echo": PolicyEffect.allow})
        journey = Journey(client)
        await journey.run("[[think]][[tool:lab__echo]]")
        body = fake_model.requests[1]
        transport = httpx.ASGITransport(app=fake_anthropic.app)

        async with httpx.AsyncClient(transport=transport, base_url="http://fake") as fake:
            intact = await fake.post("/v1/messages", json=body)
            edited_system = await fake.post("/v1/messages", json={**body, "system": "other"})
            messages = body["messages"]
            assert isinstance(messages, list)
            unanswered = await fake.post(
                "/v1/messages",
                json={
                    **body,
                    "messages": [
                        *messages[:2],
                        {"role": "user", "content": [{"type": "text", "text": "and?"}]},
                    ],
                },
            )

        assert intact.status_code == 200
        assert edited_system.status_code == 400
        assert "thinking block signature" in edited_system.text
        assert unanswered.status_code == 400
        assert "tool_result" in unanswered.text
