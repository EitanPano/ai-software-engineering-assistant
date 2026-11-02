import contextlib
import json
import traceback
from collections.abc import AsyncIterator, Callable

import httpx2
import pytest
from anthropic import AsyncAnthropic, BadRequestError
from pydantic import BaseModel

from app.models.conversation.type import HistoryTurn
from app.services.anthropic import (
    Block,
    InvalidModelOutput,
    ModelUnavailable,
    SideCallCutOff,
    SideCallInvalid,
    SideCallRefused,
    TurnResult,
    count_tokens,
    echo_blocks,
    parse_turn,
    served_blocks,
    stream_turn,
    use_client,
)
from tests import fake_anthropic
from tests.agent_support import RecordingFake

SYSTEM = "You are a test double of a system prompt."
SEARCH_DEFINITION: dict[str, object] = {
    "name": "knowledge__search",
    "description": "Searches.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
    "eager_input_streaming": True,
}


async def collect(
    history: list[HistoryTurn],
    tools: list[dict[str, object]] | None = None,
    system: str = SYSTEM,
) -> tuple[list[str], TurnResult]:
    seen: list[str] = []

    async def on_text(text: str) -> None:
        seen.append(text)

    result = await stream_turn(history, tools or [], on_text, system=system)
    return seen, result


MARKED: dict[str, object] = {"role": "user", "content": [{"type": "text", "text": "[[fallback]]"}]}


def user(text: str) -> HistoryTurn:
    return HistoryTurn(role="user", content=[{"type": "text", "text": text}])


class TestStreamTurn:
    async def test_streams_text_and_returns_the_stop_reason_and_blocks(
        self, fake_model: RecordingFake
    ) -> None:
        seen, result = await collect([user("hello")])

        assert "".join(seen) == "Hello! This is the **scripted** answer.\n\n- one\n- two\n"
        assert result.stop_reason == "end_turn"
        assert result.content[0]["type"] == "text"
        assert result.content[0]["text"] == "".join(seen)
        assert result.input_tokens > 0
        assert fake_model.requests

    async def test_sends_the_conventions_request(self, fake_model: RecordingFake) -> None:
        await collect([user("hello")])

        request = fake_model.requests[0]
        assert request["model"] == "claude-opus-5-5"
        assert request["output_config"] == {"effort": "high"}
        assert request["cache_control"] == {"type": "ephemeral"}
        assert request["fallbacks"] == "default"
        assert request["stream"] is True
        assert request["max_tokens"] == 64000
        for forbidden in ("temperature", "top_p", "top_k", "tool_choice", "tools"):
            assert forbidden not in request

    async def test_sends_the_system_it_is_given_unchanged(self, fake_model: RecordingFake) -> None:
        await collect([user("hello")], system="line one\nline two ")

        assert fake_model.requests[0]["system"] == "line one\nline two "

    async def test_sends_adaptive_thinking_whose_binding_errors_on_a_changed_prefix(
        self, fake_model: RecordingFake
    ) -> None:
        await collect([user("hello")])

        assert fake_model.requests[0]["thinking"] == {
            "type": "adaptive",
            "block_binding": {"prefix_mismatch_behavior": "error"},
        }
        assert set(fake_model.betas[0]) == {
            "server-side-fallback-2026-07-01",
            "thinking-binding-controls-2026-08-01",
        }

    async def test_sends_the_tools_it_is_given_as_they_are(self, fake_model: RecordingFake) -> None:
        await collect([user("hello")], [SEARCH_DEFINITION])

        assert fake_model.requests[0]["tools"] == [SEARCH_DEFINITION]

    async def test_two_requests_of_one_prefix_are_byte_identical_in_system_and_tools(
        self, fake_model: RecordingFake
    ) -> None:
        await collect([user("one")], [SEARCH_DEFINITION])
        await collect([user("one"), user("two")], [SEARCH_DEFINITION])

        first, second = fake_model.requests
        assert json.dumps([first["system"], first["tools"]]) == json.dumps(
            [second["system"], second["tools"]]
        )

    async def test_the_fake_refuses_a_strict_schema_the_api_would(
        self, fake_model: RecordingFake
    ) -> None:
        """`strict` refuses `minimum` and `maxLength`, and an object that allows extra fields; a
        fake that took them would hide the error a real key meets."""
        bounded = {
            **SEARCH_DEFINITION,
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string", "maxLength": 500}},
                "required": ["query"],
                "additionalProperties": False,
            },
        }
        open_object = {
            **SEARCH_DEFINITION,
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }

        for definition in (bounded, open_object):
            with pytest.raises(BadRequestError):
                await collect([user("hello")], [definition])
        assert len(fake_model.requests) == 2

    async def test_reports_a_refusal_by_its_stop_reason(self, fake_model: RecordingFake) -> None:
        _, result = await collect([user("[[refuse]]")])

        assert result.stop_reason == "refusal"
        assert fake_model.requests

    async def test_a_stream_error_event_is_model_unavailable(
        self, fake_model: RecordingFake
    ) -> None:
        with pytest.raises(ModelUnavailable):
            await collect([user("[[stream_error]]")])
        assert fake_model.requests

    async def test_keeps_a_fallback_block_and_echoes_from_it(
        self, fake_model: RecordingFake
    ) -> None:
        seen, result = await collect([user("[[fallback]]")])

        assert [block["type"] for block in result.content] == ["fallback", "text"]
        assert "".join(seen) == result.content[1]["text"]
        assert fake_model.requests


class BrokenStream(httpx2.AsyncByteStream):
    """A response body that delivers `message_start` and then loses the connection."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield fake_anthropic.message_start_event("claude-opus-5-5")
        raise self._error


class TestStreamFailure:
    @pytest.mark.parametrize(
        "error",
        [
            httpx2.ReadError("connection reset"),
            httpx2.ReadTimeout("timed out"),
            httpx2.RemoteProtocolError("peer closed"),
        ],
    )
    async def test_a_transport_error_mid_stream_is_model_unavailable(
        self, error: Exception
    ) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200, headers={"content-type": "text/event-stream"}, stream=BrokenStream(error)
            )

        http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        use_client(
            AsyncAnthropic(api_key="test", base_url="http://fake", http_client=http, max_retries=0)
        )
        try:
            with pytest.raises(ModelUnavailable) as failure:
                await collect([user("hello")])
        finally:
            use_client(None)
            await http.aclose()

        assert failure.value.__cause__ is not None


class MalformedToolInput(httpx2.AsyncByteStream):
    """A stream whose tool input is not JSON: the SDK's error holds the raw input."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield fake_anthropic.message_start_event("claude-opus-5-5")
        for event, data in (
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "tool_use", "id": "t", "name": "x", "input": {}},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"query": SECRET-QUERY-TEXT',
                    },
                },
            ),
        ):
            yield f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


class TestMalformedToolInput:
    async def test_raises_a_fixed_error_that_carries_none_of_the_input(self) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200, headers={"content-type": "text/event-stream"}, stream=MalformedToolInput()
            )

        http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        use_client(
            AsyncAnthropic(api_key="test", base_url="http://fake", http_client=http, max_retries=0)
        )
        try:
            with pytest.raises(InvalidModelOutput) as failure:
                await collect([user("hello")])
        finally:
            use_client(None)
            await http.aclose()

        rendered = "".join(traceback.format_exception(failure.value))
        assert "SECRET-QUERY-TEXT" not in rendered
        assert failure.value.__cause__ is None
        assert failure.value.__suppress_context__ is True


class TestCountTokens:
    @staticmethod
    def client(handler: httpx2.MockTransport) -> tuple[AsyncAnthropic, httpx2.AsyncClient]:
        http = httpx2.AsyncClient(transport=handler, base_url="http://fake")
        return AsyncAnthropic(
            api_key="test", base_url="http://fake", http_client=http, max_retries=0
        ), http

    async def test_sends_the_system_and_the_tools_as_given_and_returns_the_count(self) -> None:
        seen: list[dict[str, object]] = []

        def respond(request: httpx2.Request) -> httpx2.Response:
            seen.append(json.loads(request.content))
            assert request.url.path == "/v1/messages/count_tokens"
            return httpx2.Response(200, json={"input_tokens": 4321})

        client, http = self.client(httpx2.MockTransport(respond))
        use_client(client)
        try:
            counted = await count_tokens([SEARCH_DEFINITION], system=SYSTEM)
        finally:
            use_client(None)
            await http.aclose()

        assert counted == 4321
        assert seen[0]["system"] == SYSTEM
        assert seen[0]["tools"] == [SEARCH_DEFINITION]
        assert "max_tokens" not in seen[0]

    async def test_a_refused_request_propagates(self) -> None:
        def refuse(request: httpx2.Request) -> httpx2.Response:
            del request
            body = {"type": "error", "error": {"type": "invalid_request_error", "message": "no"}}
            return httpx2.Response(400, json=body)

        client, http = self.client(httpx2.MockTransport(refuse))
        use_client(client)
        try:
            with pytest.raises(BadRequestError):
                await count_tokens([SEARCH_DEFINITION], system=SYSTEM)
        finally:
            use_client(None)
            await http.aclose()


class TestBlocks:
    def test_echo_keeps_everything_when_there_is_no_fallback(self) -> None:
        blocks: list[object] = [{"type": "thinking"}, {"type": "text", "text": "a"}]

        assert echo_blocks(blocks) == blocks

    def test_echo_drops_what_precedes_the_last_fallback_block(self) -> None:
        blocks: list[object] = [
            {"type": "tool_use", "id": "t"},
            {"type": "fallback"},
            {"type": "text", "text": "a"},
        ]

        assert echo_blocks(blocks) == [{"type": "fallback"}, {"type": "text", "text": "a"}]

    def test_echo_single_hop_keeps_text_and_the_boundary_and_drops_the_refused_attempt(
        self,
    ) -> None:
        blocks: list[object] = [
            {"type": "thinking", "thinking": "t", "signature": "s"},
            {"type": "text", "text": "partial"},
            {"type": "tool_use", "id": "t1", "name": "x", "input": {}},
            {"type": "fallback", "from": {"model": "a"}},
            {"type": "thinking", "thinking": "u", "signature": "v"},
            {"type": "text", "text": "answer"},
            {"type": "tool_use", "id": "t2", "name": "x", "input": {}},
        ]

        assert echo_blocks(blocks) == [
            {"type": "text", "text": "partial"},
            {"type": "fallback", "from": {"model": "a"}},
            {"type": "thinking", "thinking": "u", "signature": "v"},
            {"type": "text", "text": "answer"},
            {"type": "tool_use", "id": "t2", "name": "x", "input": {}},
        ]

    def test_echo_multi_hop_keeps_every_fallback_and_text_in_order(self) -> None:
        blocks: list[object] = [
            {"type": "thinking", "thinking": "1"},
            {"type": "text", "text": "one"},
            {"type": "fallback", "n": 1},
            {"type": "redacted_thinking", "data": "x"},
            {"type": "text", "text": "two"},
            {"type": "tool_use", "id": "t1", "name": "x", "input": {}},
            {"type": "fallback", "n": 2},
            {"type": "thinking", "thinking": "3"},
            {"type": "text", "text": "three"},
        ]

        assert echo_blocks(blocks) == [
            {"type": "text", "text": "one"},
            {"type": "fallback", "n": 1},
            {"type": "text", "text": "two"},
            {"type": "fallback", "n": 2},
            {"type": "thinking", "thinking": "3"},
            {"type": "text", "text": "three"},
        ]

    @pytest.mark.parametrize(
        "assistant",
        [
            [{"type": "text", "text": "a"}],
            [{"type": "text", "text": "a"}, {"type": "fallback"}],
            [{"type": "thinking", "thinking": "t"}, {"type": "fallback"}, {"type": "text"}],
            [{"type": "tool_use", "id": "t", "name": "x", "input": {}}, {"type": "fallback"}],
        ],
    )
    def test_the_fake_refuses_an_assistant_turn_that_breaks_the_fallback_rule(
        self, assistant: list[dict[str, object]]
    ) -> None:
        messages = [MARKED, {"role": "assistant", "content": assistant}]

        assert fake_anthropic.request_problem(messages) is not None

    def test_the_fake_accepts_the_echo_of_a_fallback_turn(self) -> None:
        turn = [{"type": "fallback"}, {"type": "text", "text": "a"}]
        messages = [MARKED, {"role": "assistant", "content": turn}]

        assert fake_anthropic.request_problem(messages) is None

    def test_echo_drops_an_unknown_block_before_the_boundary(self) -> None:
        blocks: list[object] = [{"type": "model_internal"}, {"type": "fallback"}]

        assert echo_blocks(blocks) == [{"type": "fallback"}]

    def test_served_blocks_are_those_after_the_last_fallback(self) -> None:
        blocks: list[Block] = [
            {"type": "tool_use", "id": "t"},
            {"type": "fallback"},
            {"type": "text"},
        ]

        assert served_blocks(blocks) == [{"type": "text"}]
        assert served_blocks([{"type": "text"}]) == [{"type": "text"}]


class Facts(BaseModel):
    facts: list[str]


def side_requests(fake: RecordingFake) -> list[dict[str, object]]:
    """The requests that were not streamed: the side calls."""
    return [request for request in fake.requests if not request.get("stream")]


async def extract(text: str) -> Facts:
    return await parse_turn(
        Facts, system="Extract.", content=text, model="claude-haiku-5-5", effort="low"
    )


def message_json(
    content: list[dict[str, object]], stop_reason: str = "end_turn"
) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_x",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": 11,
                "output_tokens": 7,
                "cache_creation_input_tokens": 2,
                "cache_read_input_tokens": 3,
            },
        },
    )


@contextlib.asynccontextmanager
async def stub_model(
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> AsyncIterator[None]:
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    use_client(
        AsyncAnthropic(api_key="test", base_url="http://fake", http_client=http, max_retries=0)
    )
    try:
        yield
    finally:
        use_client(None)
        await http.aclose()


class TestParseTurn:
    async def test_returns_a_validated_instance(self, fake_model: RecordingFake) -> None:
        result = await extract("I use uv. [[fact:The person uses uv.]]")

        assert result == Facts(facts=["The person uses uv."])

    async def test_sends_the_side_call_request(self, fake_model: RecordingFake) -> None:
        await extract("I use uv. [[fact:The person uses uv.]]")

        (request,) = side_requests(fake_model)
        assert request["model"] == "claude-haiku-5-5"
        assert request["system"] == "Extract."
        assert request["max_tokens"] == 16000
        assert request["messages"] == [
            {"role": "user", "content": "I use uv. [[fact:The person uses uv.]]"}
        ]
        output = request["output_config"]
        assert isinstance(output, dict)
        assert output["effort"] == "low"
        assert output["format"]["type"] == "json_schema"
        assert output["format"]["schema"]["properties"].keys() == {"facts"}
        for absent in ("thinking", "fallbacks", "cache_control", "stream", "temperature", "tools"):
            assert absent not in request
        assert not any("fallback" in flag for flag in fake_model.betas[0])

    async def test_retries_one_invalid_answer_once(self, fake_model: RecordingFake) -> None:
        result = await extract("[[extract_invalid_once]] [[fact:The person uses uv.]]")

        assert result.facts == ["The person uses uv."]
        assert len(side_requests(fake_model)) == 2

    async def test_a_second_invalid_answer_is_a_typed_error_without_the_text(
        self, fake_model: RecordingFake
    ) -> None:
        with pytest.raises(SideCallInvalid) as failure:
            await extract("[[extract_invalid]] my private note")

        assert len(side_requests(fake_model)) == 2
        assert failure.value.__cause__ is None
        assert failure.value.__suppress_context__ is True
        assert str(failure.value) == ""
        assert failure.value.__context__ is None or failure.value.__suppress_context__

    async def test_a_refusal_is_a_typed_error_and_is_not_retried(
        self, fake_model: RecordingFake
    ) -> None:
        with pytest.raises(SideCallRefused):
            await extract("[[extract_refused]]")

        assert len(side_requests(fake_model)) == 1

    async def test_a_cut_off_answer_is_a_typed_error_and_is_not_retried(
        self, fake_model: RecordingFake
    ) -> None:
        with pytest.raises(SideCallCutOff):
            await extract("[[extract_cut]]")

        assert len(side_requests(fake_model)) == 1

    async def test_text_before_a_fallback_block_is_ignored(self) -> None:
        def handler(_request: httpx2.Request) -> httpx2.Response:
            return message_json(
                [
                    {"type": "text", "text": "{broken"},
                    {"type": "fallback", "from": {"model": "a"}, "to": {"model": "b"}},
                    {"type": "text", "text": '{"facts": ["ok"]}'},
                ]
            )

        async with stub_model(handler):
            assert (await extract("x")).facts == ["ok"]

    async def test_the_stop_reason_is_read_before_any_text(self) -> None:
        def handler(_request: httpx2.Request) -> httpx2.Response:
            return message_json([{"type": "text", "text": '{"facts": ["x"]}'}], "refusal")

        async with stub_model(handler):
            with pytest.raises(SideCallRefused):
                await extract("x")

    async def test_logs_usage_with_both_cache_fields_and_no_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services import anthropic as module
        from tests.support import recording_logger

        logger, sink = recording_logger()
        monkeypatch.setattr(module, "log", logger)

        def handler(_request: httpx2.Request) -> httpx2.Response:
            return message_json([{"type": "text", "text": '{"facts": ["secret fact"]}'}])

        async with stub_model(handler):
            await extract("a private message")

        (line,) = sink.lines
        assert "usage_in=11" in line
        assert "usage_out=7" in line
        assert "cache_write=2" in line
        assert "cache_read=3" in line
        assert "private" not in line
        assert "secret" not in line

    @pytest.mark.parametrize(
        "error", [httpx2.ReadTimeout("timed out"), httpx2.ConnectError("refused")]
    )
    async def test_a_transport_failure_is_model_unavailable(self, error: Exception) -> None:
        def handler(_request: httpx2.Request) -> httpx2.Response:
            raise error

        async with stub_model(handler):
            with pytest.raises(ModelUnavailable):
                await extract("x")

    async def test_a_rate_limit_is_model_unavailable(self) -> None:
        def handler(_request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                429, json={"type": "error", "error": {"type": "rate_limit_error", "message": "x"}}
            )

        async with stub_model(handler):
            with pytest.raises(ModelUnavailable):
                await extract("x")
