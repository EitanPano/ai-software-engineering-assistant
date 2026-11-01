import json
import traceback
from collections.abc import AsyncIterator

import httpx2
import pytest
from anthropic import AsyncAnthropic, BadRequestError

from app.models.conversation.type import HistoryTurn
from app.services.anthropic import (
    Block,
    InvalidModelOutput,
    ModelUnavailable,
    TurnResult,
    echo_blocks,
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
