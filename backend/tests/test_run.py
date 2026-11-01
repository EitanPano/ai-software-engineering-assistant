import asyncio
from typing import ClassVar

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from app.api.run import service as run_service
from app.api.run.controller import (
    append_run_event,
    fail_lost_runs,
    finish_run,
    start_run,
)
from app.api.run.schema import EventSequence, RunEvent
from app.config.constants import RATE_LIMITS
from app.models.run.enums import RunErrorCode, RunEventType, RunStatus
from app.services.utils import clock
from tests.agent_support import (
    bearer,
    frames_of,
    send,
    start_conversation,
    stream,
    types_of,
)
from tests.store import reset_store, store_backed
from tests.support import error_of


class TestLastEventId:
    """The `Last-Event-ID` header is an integer of at least 0."""

    def test_accepts_zero_and_a_header_string(self) -> None:
        adapter = TypeAdapter(EventSequence)

        assert adapter.validate_python(0) == 0
        assert adapter.validate_python("12") == 12

    @pytest.mark.parametrize("value", [-1, "-1", "abc", "1.5", ""])
    def test_rejects_a_negative_or_non_integer_value(self, value: object) -> None:
        with pytest.raises(ValidationError):
            TypeAdapter(EventSequence).validate_python(value)


class TestRunEvent:
    def test_is_a_union_on_type(self) -> None:
        adapter = TypeAdapter(RunEvent)

        started = adapter.validate_python(
            {"type": "run_started", "sequence": 1, "createdAt": "2026-10-30T00:00:00.000Z"}
        )
        assert started.root.type == "run_started"

    def test_rejects_an_unknown_type(self) -> None:
        with pytest.raises(ValidationError):
            TypeAdapter(RunEvent).validate_python(
                {"type": "nope", "sequence": 1, "createdAt": "2026-10-30T00:00:00.000Z"}
            )

    def test_rejects_a_tool_status_outside_the_set(self) -> None:
        with pytest.raises(ValidationError):
            TypeAdapter(RunEvent).validate_python(
                {
                    "type": "tool_call_finished",
                    "sequence": 3,
                    "createdAt": "2026-10-30T00:00:00.000Z",
                    "toolUseId": "t",
                    "status": "maybe",
                    "output": "",
                }
            )


class TestMcpServerUnavailableEvent:
    base: ClassVar[dict[str, object]] = {
        "type": "mcp_server_unavailable",
        "sequence": 2,
        "createdAt": "2026-10-30T00:00:00.000Z",
    }

    def test_carries_the_server_name(self) -> None:
        event = TypeAdapter(RunEvent).validate_python({**self.base, "name": "knowledge"})

        assert event.root.type == "mcp_server_unavailable"
        assert event.model_dump(by_alias=True)["name"] == "knowledge"

    def test_requires_the_name(self) -> None:
        with pytest.raises(ValidationError):
            TypeAdapter(RunEvent).validate_python(self.base)

    def test_the_stored_type_exists(self) -> None:
        assert RunEventType("mcp_server_unavailable") is RunEventType.mcp_server_unavailable


class StoreBacked:
    @pytest.fixture(autouse=True)
    async def empty_store(self) -> None:
        await reset_store()


async def finished_run(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    """A completed run with a start, two text deltas and a finish: sequences 1 to 4."""
    conversation = await start_conversation(client, headers)
    run_id = await send(client, headers, conversation, "hello")
    assert await start_run(run_id)
    await append_run_event(run_id, RunEventType.text_delta, {"text": "Hel"})
    await append_run_event(run_id, RunEventType.text_delta, {"text": "lo"})
    assert await finish_run(run_id, RunStatus.completed, None)
    return run_id


@store_backed
class TestReplay(StoreBacked):
    async def test_streams_every_event_in_order_with_the_sequence_as_the_id(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        run_id = await finished_run(client, headers)

        res = await client.get(f"/api/run/{run_id}/event", headers=headers)
        frames = frames_of(res)

        assert res.headers["content-type"].startswith("text/event-stream")
        assert [frame.id for frame in frames] == [1, 2, 3, 4]
        assert [frame.event["sequence"] for frame in frames] == [1, 2, 3, 4]
        assert types_of(frames) == ["run_started", "text_delta", "text_delta", "run_finished"]
        assert frames[1].event["text"] == "Hel"
        assert frames[3].event["status"] == "completed"
        assert frames[3].event["errorCode"] is None
        assert isinstance(frames[0].event["createdAt"], str)

    async def test_resumes_after_last_event_id_once_each(self, client: httpx.AsyncClient) -> None:
        headers = bearer()
        run_id = await finished_run(client, headers)

        after_two = await stream(client, headers, run_id, last_event_id=2)
        after_zero = await stream(client, headers, run_id, last_event_id=0)
        after_last = await stream(client, headers, run_id, last_event_id=4)
        after_beyond = await stream(client, headers, run_id, last_event_id=99)

        assert [frame.id for frame in after_two] == [3, 4]
        assert [frame.id for frame in after_zero] == [1, 2, 3, 4]
        assert after_last == []
        assert after_beyond == []

    async def test_a_stream_open_during_the_run_gets_the_rest_in_order_and_closes(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        conversation = await start_conversation(client, headers)
        run_id = await send(client, headers, conversation, "hello")
        await start_run(run_id)

        reading = asyncio.create_task(stream(client, headers, run_id, last_event_id=1))
        await asyncio.sleep(0.3)  # the reader is polling an empty tail
        await append_run_event(run_id, RunEventType.text_delta, {"text": "a"})
        await append_run_event(run_id, RunEventType.text_delta, {"text": "b"})
        await finish_run(run_id, RunStatus.failed, RunErrorCode.refused)
        frames = await asyncio.wait_for(reading, timeout=5)

        assert [frame.id for frame in frames] == [2, 3, 4]
        assert frames[-1].event["status"] == "failed"
        assert frames[-1].event["errorCode"] == "refused"

    async def test_run_started_is_stored_before_anything_else_happens(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        conversation = await start_conversation(client, headers)
        run_id = await send(client, headers, conversation, "hello")

        await start_run(run_id)

        events = await run_service.list_events_after(run_id, 0, 10)
        assert [(event.sequence, event.type) for event in events] == [(1, RunEventType.run_started)]

    async def test_concurrent_appends_get_distinct_ordered_sequences(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        conversation = await start_conversation(client, headers)
        run_id = await send(client, headers, conversation, "hello")
        await start_run(run_id)

        await asyncio.gather(
            *(
                append_run_event(run_id, RunEventType.text_delta, {"text": str(i)})
                for i in range(20)
            )
        )

        events = await run_service.list_events_after(run_id, 0, 100)
        assert [event.sequence for event in events] == list(range(1, 22))

    async def test_a_run_finishes_once(self, client: httpx.AsyncClient) -> None:
        headers = bearer()
        run_id = await finished_run(client, headers)

        again = await finish_run(run_id, RunStatus.failed, RunErrorCode.internal)

        assert again is False
        frames = await stream(client, headers, run_id)
        assert types_of(frames).count("run_finished") == 1


@store_backed
class TestAccess(StoreBacked):
    async def test_answers_401_without_a_token(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/run/anything/event")

        assert res.status_code == 401
        assert error_of(res).code == "unauthenticated"
        assert res.json()["requestId"]

    async def test_another_users_run_and_a_missing_run_are_not_found(
        self, client: httpx.AsyncClient
    ) -> None:
        owner = bearer()
        run_id = await finished_run(client, owner)

        for headers, target in ((bearer(), run_id), (owner, "does-not-exist")):
            res = await client.get(f"/api/run/{target}/event", headers=headers)
            assert res.status_code == 404
            assert error_of(res).code == "not_found"
            assert res.json()["requestId"]

    @pytest.mark.parametrize("value", ["-1", "abc", "1.5"])
    async def test_a_bad_last_event_id_is_a_validation_failure(
        self, client: httpx.AsyncClient, value: str
    ) -> None:
        headers = bearer()
        run_id = await finished_run(client, headers)

        res = await client.get(
            f"/api/run/{run_id}/event", headers={**headers, "Last-Event-ID": value}
        )

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"
        assert error_of(res).message == "invalid header"
        assert error_of(res).details[0].path == "Last-Event-ID"
        assert res.json()["requestId"]


@store_backed
class TestStreamLimits(StoreBacked):
    async def test_opens_over_the_per_user_limit_are_rate_limited(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        run_id = await finished_run(client, headers)
        for _ in range(RATE_LIMITS.run_stream_per_user.limit):
            opened = await client.get(f"/api/run/{run_id}/event", headers=headers)
            assert opened.status_code == 200

        res = await client.get(f"/api/run/{run_id}/event", headers=headers)
        other = await client.get(f"/api/run/{run_id}/event", headers=bearer())

        assert res.status_code == 429
        assert error_of(res).code == "rate_limited"
        assert int(res.headers["retry-after"]) > 0
        assert res.json()["requestId"]
        assert other.status_code == 404  # another caller is not limited by this one's opens

    async def test_a_stream_closes_at_its_lifetime_and_a_reopen_carries_on(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.api.run.controller.AGENT_STREAM_MAX_SECONDS", 0.4)
        headers = bearer()
        conversation = await start_conversation(client, headers)
        run_id = await send(client, headers, conversation, "hello")
        await start_run(run_id)
        await append_run_event(run_id, RunEventType.text_delta, {"text": "a"})

        first = await asyncio.wait_for(stream(client, headers, run_id), timeout=5)
        await append_run_event(run_id, RunEventType.text_delta, {"text": "b"})
        await finish_run(run_id, RunStatus.completed, None)
        second = await stream(client, headers, run_id, last_event_id=first[-1].id)

        assert types_of(first) == ["run_started", "text_delta"]  # closed cleanly, run still active
        assert [frame.id for frame in second] == [3, 4]
        assert types_of(second) == ["text_delta", "run_finished"]


@store_backed
class TestRecovery(StoreBacked):
    async def test_fails_the_runs_started_before_the_boundary_with_one_run_finished_each(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        running = await send(client, headers, await start_conversation(client, headers), "a")
        queued = await send(client, headers, await start_conversation(client, headers), "b")
        await start_run(running)
        boundary = clock.now()
        after = await send(client, headers, await start_conversation(client, headers), "c")

        failed = await fail_lost_runs(boundary)
        again = await fail_lost_runs(boundary)

        assert (failed, again) == (2, 0)
        for run_id in (running, queued):
            frames = await stream(client, headers, run_id)
            assert types_of(frames).count("run_finished") == 1
            assert frames[-1].event["status"] == "failed"
            assert frames[-1].event["errorCode"] == "interrupted"
        untouched = await run_service.find_run(after)
        assert untouched is not None
        assert untouched.status is RunStatus.queued

    async def test_a_stream_open_on_a_lost_run_closes(self, client: httpx.AsyncClient) -> None:
        headers = bearer()
        run_id = await send(client, headers, await start_conversation(client, headers), "a")
        await start_run(run_id)
        reading = asyncio.create_task(stream(client, headers, run_id))
        await asyncio.sleep(0.3)

        await fail_lost_runs(clock.now())
        frames = await asyncio.wait_for(reading, timeout=5)

        assert types_of(frames) == ["run_started", "run_finished"]

    async def test_a_lost_run_frees_the_conversation_for_a_new_send(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        conversation = await start_conversation(client, headers)
        await send(client, headers, conversation, "a")

        await fail_lost_runs(clock.now())

        assert await send(client, headers, conversation, "again")
