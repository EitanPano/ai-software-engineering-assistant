import asyncio
from collections.abc import Iterator

import httpx
import pytest

from app.api.agent.controller import execute_run
from app.api.conversation.controller import read_history
from app.config.constants import AGENT_MAX_TURNS
from app.infra.pubsub import pubsub
from app.services import tool
from app.services.anthropic import ModelUnavailable
from app.services.event import drain
from app.services.logger import create_logger
from app.services.tool import Tool, ToolInput
from tests.agent_support import (
    Frame,
    RecordingFake,
    bearer,
    send,
    start_conversation,
    stream,
    types_of,
)
from tests.store import reset_store, store_backed


class EchoInput(ToolInput):
    text: str


async def echo(arguments: dict[str, object]) -> str:
    return f"echo:{arguments['text']}"


async def explode(arguments: dict[str, object]) -> str:
    raise RuntimeError("secret internal detail")


class Journey:
    """One signed-in caller, one conversation, and the run a message starts."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.headers = bearer()
        self.conversation = ""

    async def run(self, content: str) -> tuple[str, list[Frame]]:
        """Sends `content`, executes the run in this task, and reads the whole stream."""
        if not self.conversation:
            self.conversation = await start_conversation(self.client, self.headers)
        run_id = await send(self.client, self.headers, self.conversation, content)
        await execute_run(run_id)
        return run_id, await stream(self.client, self.headers, run_id)


def text_of(frames: list[Frame]) -> str:
    return "".join(str(f.event["text"]) for f in frames if f.event["type"] == "text_delta")


def finish_of(frames: list[Frame]) -> Frame:
    finishes = [f for f in frames if f.event["type"] == "run_finished"]
    assert len(finishes) == 1
    assert frames[-1] is finishes[0]
    return finishes[0]


@pytest.fixture(autouse=True)
def empty_registry() -> Iterator[None]:
    tool.clear_tools()
    yield
    tool.clear_tools()


class StoreBacked:
    @pytest.fixture(autouse=True)
    async def empty_store(self) -> None:
        await reset_store()


@store_backed
class TestAnswer(StoreBacked):
    async def test_streams_the_answer_and_completes(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)

        run_id, frames = await journey.run("hello")

        assert types_of(frames)[0] == "run_started"
        assert set(types_of(frames)[1:-1]) == {"text_delta"}
        assert text_of(frames) == "Hello! This is the **scripted** answer.\n\n- one\n- two\n"
        assert finish_of(frames).event["status"] == "completed"
        assert [f.id for f in frames] == list(range(1, len(frames) + 1))
        opened = await client.get(
            f"/api/conversation/{journey.conversation}", headers=journey.headers
        )
        assert opened.json()["latestRun"] == {
            "id": run_id,
            "status": "completed",
            "errorCode": None,
            "createdAt": opened.json()["latestRun"]["createdAt"],
        }
        assert len(fake_model.requests) == 1

    async def test_the_answer_survives_as_a_message_after_the_run(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)
        run_id, _ = await journey.run("hello")

        res = await client.get(
            f"/api/conversation/{journey.conversation}/message", headers=journey.headers
        )

        assert [(m["role"], m["runId"]) for m in res.json()["items"]] == [
            ("assistant", run_id),
            ("user", run_id),
        ]
        assert res.json()["items"][0]["text"].startswith("Hello! This is the **scripted**")
        assert fake_model.requests

    async def test_a_second_message_sends_the_whole_history(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)
        await journey.run("first")
        await journey.run("second")

        sent = fake_model.requests[1]["messages"]
        assert isinstance(sent, list)
        assert [turn["role"] for turn in sent] == ["user", "assistant", "user"]

    async def test_a_run_that_is_not_queued_is_left_alone(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)
        run_id, frames = await journey.run("hello")

        await execute_run(run_id)

        assert await stream(client, journey.headers, run_id) == frames
        assert len(fake_model.requests) == 1

    async def test_the_bus_hands_a_sent_message_to_the_agent(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        await pubsub.connect()
        try:
            journey = Journey(client)
            journey.conversation = await start_conversation(client, journey.headers)
            run_id = await send(client, journey.headers, journey.conversation, "hello")
            await drain()
            frames = await stream(client, journey.headers, run_id)
        finally:
            await pubsub.close()

        assert finish_of(frames).event["status"] == "completed"
        assert fake_model.requests


@store_backed
class TestTools(StoreBacked):
    async def test_an_unregistered_tool_is_denied_and_never_runs(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)
        _, frames = await journey.run("[[tool:ghost]]")

        assert tool.get_tool("ghost") is None
        assert types_of(frames)[:3] == ["run_started", "tool_call_started", "tool_call_finished"]
        assert frames[1].event["name"] == "ghost"
        assert frames[1].event["input"] == {"text": "hi"}
        assert frames[2].event["status"] == "denied"
        assert text_of(frames) == "Tool done."
        assert finish_of(frames).event["status"] == "completed"
        result = _tool_results(fake_model.requests[1])[0]
        assert result["is_error"] is True
        assert "tools" not in fake_model.requests[0]

    async def test_a_registered_tool_runs_and_its_result_goes_back(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        tool.register_tool(Tool("echo", "echoes", EchoInput, echo))
        journey = Journey(client)

        _, frames = await journey.run("[[tool:echo]]")

        assert frames[2].event["status"] == "succeeded"
        assert frames[2].event["output"] == "echo:hi"
        assert frames[1].event["toolUseId"] == frames[2].event["toolUseId"]
        first, second = fake_model.requests
        assert [d["name"] for d in first["tools"]] == ["echo"]  # type: ignore[attr-defined]
        assert first["tools"][0]["strict"] is True  # type: ignore[index]
        sent = second["messages"]
        assert isinstance(sent, list)
        assert [turn["role"] for turn in sent] == ["user", "assistant", "user"]
        result = _tool_results(second)[0]
        assert result["content"] == "echo:hi"
        assert result["is_error"] is False

    async def test_parallel_calls_run_concurrently_and_return_in_one_user_turn(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        started = {"first": asyncio.Event(), "second": asyncio.Event()}

        def meeting(me: str, other: str) -> Tool:
            async def run(arguments: dict[str, object]) -> str:
                started[me].set()
                # Each waits for the other: serial execution would never get past here.
                await asyncio.wait_for(started[other].wait(), timeout=5)
                return f"{me} done"

            return Tool(me, me, EchoInput, run)

        tool.register_tool(meeting("first", "second"))
        tool.register_tool(meeting("second", "first"))
        journey = Journey(client)

        _, frames = await journey.run("[[parallel]]")

        assert finish_of(frames).event["status"] == "completed"
        results = _tool_results(fake_model.requests[1])
        assert [r["content"] for r in results] == ["first done", "second done"]
        sent = fake_model.requests[1]["messages"]
        assert isinstance(sent, list)
        assert len(sent) == 3  # user, assistant, ONE user turn with both results

    async def test_an_input_that_fails_validation_is_an_error_result_and_never_runs(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        tool.register_tool(Tool("echo", "echoes", EchoInput, echo))
        journey = Journey(client)

        _, frames = await journey.run("[[badtool:echo]]")

        assert frames[2].event["status"] == "failed"
        assert str(frames[2].event["output"]).startswith("invalid input")
        result = _tool_results(fake_model.requests[1])[0]
        assert result["is_error"] is True
        assert finish_of(frames).event["status"] == "completed"

    async def test_a_tool_that_raises_gives_the_model_a_fixed_message(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        tool.register_tool(Tool("boom", "fails", EchoInput, explode))
        journey = Journey(client)

        _, frames = await journey.run("[[tool:boom]]")

        assert frames[2].event["status"] == "failed"
        assert "secret" not in str(frames[2].event["output"])
        assert finish_of(frames).event["status"] == "completed"
        assert fake_model.requests

    async def test_every_stored_tool_use_has_its_result(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)
        await journey.run("[[tool:ghost]]")

        history = await read_history(journey.conversation)

        assert [turn.role for turn in history] == ["user", "assistant", "user", "assistant"]
        uses = [b for b in history[1].content if isinstance(b, dict) and b["type"] == "tool_use"]
        results = [b for b in history[2].content if isinstance(b, dict)]
        assert [r["tool_use_id"] for r in results] == [u["id"] for u in uses]
        assert fake_model.requests


@store_backed
class TestStopReason(StoreBacked):
    @pytest.mark.parametrize(
        ("marker", "code"),
        [
            ("[[refuse]]", "refused"),
            ("[[truncate]]", "truncated"),
            ("[[stream_error]]", "upstream_unavailable"),
        ],
    )
    async def test_ends_the_run_failed_with_one_run_finished(
        self, client: httpx.AsyncClient, fake_model: RecordingFake, marker: str, code: str
    ) -> None:
        journey = Journey(client)

        run_id, frames = await journey.run(marker)

        assert finish_of(frames).event["status"] == "failed"
        assert finish_of(frames).event["errorCode"] == code
        opened = await client.get(
            f"/api/conversation/{journey.conversation}", headers=journey.headers
        )
        assert opened.json()["latestRun"]["errorCode"] == code
        assert opened.json()["latestRun"]["id"] == run_id
        assert fake_model.requests

    async def test_a_failed_run_keeps_its_partial_text_events_but_stores_no_answer(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)
        _, frames = await journey.run("[[truncate]]")

        listed = await client.get(
            f"/api/conversation/{journey.conversation}/message", headers=journey.headers
        )

        assert text_of(frames) != ""
        assert [m["role"] for m in listed.json()["items"]] == ["user"]
        assert fake_model.requests

    async def test_a_run_that_keeps_asking_for_tools_stops_at_the_turn_limit(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)

        _, frames = await journey.run("[[loop]]")

        assert finish_of(frames).event["errorCode"] == "turn_limit"
        assert len(fake_model.requests) == AGENT_MAX_TURNS
        # Every stored tool_use still has its result, so the conversation can go on.
        history = await read_history(journey.conversation)
        assert len(history) == 1 + 2 * AGENT_MAX_TURNS

    async def test_an_unexpected_error_ends_the_run_as_internal(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def broken(*_: object) -> None:
            raise RuntimeError("detail that must not leave the server")

        monkeypatch.setattr("app.api.agent.controller.stream_turn", broken)
        journey = Journey(client)

        _, frames = await journey.run("hello")

        assert finish_of(frames).event["errorCode"] == "internal"
        assert "detail" not in str(frames)

    async def test_a_fallback_block_is_stored_and_echoed_from_its_position(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)
        _, frames = await journey.run("[[fallback]]")
        await journey.run("again")

        assert finish_of(frames).event["status"] == "completed"
        assert text_of(frames) == "Hello! This is the **scripted** answer.\n\n- one\n- two\n"
        history = await read_history(journey.conversation)
        assert [b["type"] for b in history[1].content if isinstance(b, dict)] == [
            "fallback",
            "text",
        ]
        echoed = fake_model.requests[1]["messages"][1]["content"]  # type: ignore[index]
        assert [b["type"] for b in echoed] == ["fallback", "text"]


class OptionalInput(ToolInput):
    """Every field optional: an empty object passes this schema, which a non-object must not."""

    text: str = "default"


@store_backed
class TestToolInput(StoreBacked):
    async def test_an_input_that_is_not_an_object_fails_the_run_and_is_never_stored_or_run(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        ran: list[dict[str, object]] = []

        async def optional(arguments: dict[str, object]) -> str:
            ran.append(arguments)
            return "ran"

        tool.register_tool(Tool("loose", "all optional", OptionalInput, optional))
        journey = Journey(client)

        _, frames = await journey.run("[[stringinput:loose]]")
        _, followup = await journey.run("hello again")

        assert ran == []
        # Nothing was started, so nothing dangles; the run ends once, as internal.
        assert types_of(frames) == ["run_started", "run_finished"]
        assert finish_of(frames).event["errorCode"] == "internal"
        # The turn was not stored: the history stays valid and the conversation goes on.
        assert finish_of(followup).event["status"] == "completed"
        assert [turn.role for turn in await read_history(journey.conversation)] == [
            "user",
            "user",
            "assistant",
        ]
        assert len(fake_model.requests) == 2


class CapturingSink:
    """A logger sink that keeps the exception, which the line-only test sink drops."""

    def __init__(self) -> None:
        self.errors: list[tuple[str, BaseException | None]] = []

    def info(self, message: str) -> None:
        del message

    def warning(self, message: str) -> None:
        del message

    def error(self, message: str, *, exc_info: BaseException | None = None) -> None:
        self.errors.append((message, exc_info))


@store_backed
class TestScripts(StoreBacked):
    """The stop reasons beyond the three in TestStopReason, and the failures worth a log line."""

    async def test_a_model_outage_is_logged_with_its_cause(
        self,
        client: httpx.AsyncClient,
        fake_model: RecordingFake,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sink = CapturingSink()
        monkeypatch.setattr("app.api.agent.controller.log", create_logger(quiet=False, sink=sink))
        journey = Journey(client)

        run_id, frames = await journey.run("[[stream_error]]")

        assert finish_of(frames).event["errorCode"] == "upstream_unavailable"
        logged = [(m, e) for m, e in sink.errors if m.startswith("model unavailable")]
        assert len(logged) == 1
        message, error = logged[0]
        assert run_id in message
        assert isinstance(error, ModelUnavailable)
        assert error.__cause__ is not None
        assert fake_model.requests

    async def test_pause_turn_stores_the_turn_and_calls_the_model_again(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)

        _, frames = await journey.run("[[pause]]")

        assert finish_of(frames).event["status"] == "completed"
        assert len(fake_model.requests) == 2
        sent = fake_model.requests[1]["messages"]
        assert isinstance(sent, list)
        assert [turn["role"] for turn in sent] == ["user", "assistant"]
        history = await read_history(journey.conversation)
        assert [turn.role for turn in history] == ["user", "assistant", "assistant"]

    async def test_a_stop_sequence_completes_like_an_end_turn(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)

        _, frames = await journey.run("[[stop_sequence]]")

        assert finish_of(frames).event["status"] == "completed"
        assert len(fake_model.requests) == 1

    async def test_a_full_context_window_ends_truncated(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)

        _, frames = await journey.run("[[context_limit]]")

        assert finish_of(frames).event["errorCode"] == "truncated"
        assert fake_model.requests

    async def test_an_unknown_stop_reason_ends_internal(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)

        _, frames = await journey.run("[[unknown_stop]]")

        assert finish_of(frames).event["errorCode"] == "internal"
        assert fake_model.requests

    async def test_an_empty_answer_fails_the_run_and_never_poisons_the_history(
        self, client: httpx.AsyncClient, fake_model: RecordingFake
    ) -> None:
        journey = Journey(client)

        _, frames = await journey.run("[[empty]]")
        _, followup = await journey.run("hello again")

        assert finish_of(frames).event["errorCode"] == "internal"
        assert finish_of(followup).event["status"] == "completed"
        for request in fake_model.requests:
            sent = request["messages"]
            assert isinstance(sent, list)
            for turn in sent:
                assert turn["content"] != []


def _tool_results(request: dict[str, object]) -> list[dict[str, object]]:
    messages = request["messages"]
    assert isinstance(messages, list)
    last = messages[-1]
    assert last["role"] == "user"
    return [block for block in last["content"] if block["type"] == "tool_result"]
