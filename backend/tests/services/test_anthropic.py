from collections.abc import AsyncIterator

import httpx2
import pytest
from anthropic import AsyncAnthropic

from app.models.conversation.type import HistoryTurn
from app.services.anthropic import (
    Block,
    ModelUnavailable,
    TurnResult,
    echo_blocks,
    served_blocks,
    stream_turn,
    use_client,
)
from tests import fake_anthropic
from tests.agent_support import RecordingFake


async def collect(history: list[HistoryTurn]) -> tuple[list[str], TurnResult]:
    seen: list[str] = []

    async def on_text(text: str) -> None:
        seen.append(text)

    result = await stream_turn(history, [], on_text)
    return seen, result


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
        for forbidden in ("thinking", "temperature", "top_p", "top_k", "tool_choice", "tools"):
            assert forbidden not in request

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

    def test_served_blocks_are_those_after_the_last_fallback(self) -> None:
        blocks: list[Block] = [
            {"type": "tool_use", "id": "t"},
            {"type": "fallback"},
            {"type": "text"},
        ]

        assert served_blocks(blocks) == [{"type": "text"}]
        assert served_blocks([{"type": "text"}]) == [{"type": "text"}]
