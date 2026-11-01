"""A scripted fake of Anthropic's `POST /v1/messages`, on the SSE wire format.

The SDK's own stream handling runs against it, so nothing test-only ships in the app: the backend
tests point an `AsyncAnthropic` at this ASGI app, and the e2e suite starts it on port 8101
(`python -m tests.fake_anthropic`) and sets `ANTHROPIC_BASE_URL` for the API. No network and no key.

The script is chosen by markers in the user's last message, so journeys running in parallel stay
apart. A marker is `[[name]]` or `[[name:key]]`:

- none: a Markdown answer, a few chunks, then `end_turn`.
- `[[hold:KEY]]`: the first part of the answer, then the fake waits until `POST /release/KEY`
  (or 30 s) before it sends the rest.
- `[[tool:NAME]]`: the first call asks for tool NAME with a valid input `{"text": "hi"}`; after the
  tool result the answer is "Tool done.".
- `[[badtool:NAME]]`: as `tool`, with an input that fails any schema: `{"nope": 1}`.
- `[[stringinput:NAME]]`: as `tool`, with an input that is a JSON string, not an object.
- `[[nulinput:NAME]]`: as `tool`, with a NUL in the input, which a JSONB column cannot store.
- `[[many:NAME]]`: one turn asks for NAME 14 times (more than a run's budget), each with a valid
  input (a query for `knowledge__search`, a text otherwise).
- `[[pause]]`: some text, then `stop_reason: pause_turn`; the request that continues it (it ends in
  the stored assistant turn) is answered normally.
- `[[stop_sequence]]`, `[[context_limit]]`, `[[unknown_stop]]`: those stop reasons
  (`stop_sequence`, `model_context_window_exceeded`, and one the API does not define).
- `[[empty]]`: `end_turn` with no content at all.
- `[[parallel]]`: the first call asks for two tools (`lab__first` and `lab__second`) in one turn.
- `[[loop]]`: every call asks for a tool, so the run reaches its turn limit.
- `[[refuse]]`: `stop_reason: refusal`, no content.
- `[[truncate]]`: some text, then `stop_reason: max_tokens`.
- `[[stream_error]]`: some text, then an `overloaded_error` event in the middle of the stream.
- `[[fallback]]`: a `fallback` block, then the answer from the serving model.
- `[[research]]`: asks for `knowledge__search` with a semantic query, then with a keyword one, then
  cites `path:start-end` of the first hit in the last tool result, or says the knowledge base holds
  no answer (no hits, or an error result). When the request does not offer the tool, it says it
  cannot search and calls nothing.

A request is also checked for what the real API refuses: an empty turn, a `tool_use` input that is
not an object, and a `strict` tool whose schema holds a keyword `strict` does not support or an
object that is not closed. Each is a 400.
"""

import asyncio
import json
import os
import re
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Final

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from tests.fixture_repository import KEYWORD_QUERY, SEMANTIC_QUERY

MARKER: Final = re.compile(r"\[\[([a-z_]+)(?::([A-Za-z0-9_-]+))?\]\]")
ANSWER_CHUNKS: Final = ("Hello! ", "This is the **scripted** answer.\n\n", "- one\n", "- two\n")
HOLD_CHUNKS: Final = ("The first part. ", "The rest, **done**.")
TOOL_DONE: Final = "Tool done."
# `[[research]]` searches the fixture repository twice (the second query is a keyword the first
# answer does not hold), then cites the last result.
SEARCH_TOOL: Final = "knowledge__search"
RESEARCH_QUERIES: Final = (SEMANTIC_QUERY, KEYWORD_QUERY)
MANY_CALLS: Final = 14
NO_ANSWER: Final = "The knowledge base holds no answer to that."
NOT_OFFERED: Final = "I cannot search the knowledge base right now."
HOLD_TIMEOUT_SECONDS: Final = 30.0
# Between chunks, so a reader sees an answer arrive in pieces. A test sets it to 0.
timings: dict[str, float] = {"chunk_delay": 0.01}

_released: dict[str, asyncio.Event] = {}

type Json = dict[str, object]


def _event(name: str, data: Json) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()


def _blocks(content: object) -> list[Json]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def script_text(messages: object) -> tuple[str, bool]:
    """The text of the user's last message that has text, and whether the request continues after a
    tool result (the last message is a user turn made of `tool_result` blocks)."""
    if not isinstance(messages, list) or not messages:
        return "", False
    last = messages[-1]
    # After tool results, or after a stored `pause_turn` (the request ends in an assistant turn).
    continuation = isinstance(last, dict) and (
        last.get("role") == "assistant"
        or any(block.get("type") == "tool_result" for block in _blocks(last.get("content")))
    )
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        for block in _blocks(message.get("content")):
            text = block.get("text")
            if block.get("type") == "text" and isinstance(text, str):
                return text, continuation
    return "", continuation


STRICT_UNSUPPORTED: Final = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "maxItems",
        "uniqueItems",
    }
)


def _schema_problem(schema: object, where: str) -> str | None:
    """What `strict` tool use refuses in an input schema: a keyword it does not support, and an
    object that does not close itself with `additionalProperties: false`."""
    if not isinstance(schema, dict):
        return None
    for keyword in STRICT_UNSUPPORTED & schema.keys():
        return f"{where}: strict tool use does not support '{keyword}'"
    if schema.get("type") == "object" and schema.get("additionalProperties") is not False:
        return f"{where}: additionalProperties must be false for strict tool use"
    for key, value in schema.items():
        children = value.values() if key == "properties" and isinstance(value, dict) else [value]
        for child in children:
            for item in child if isinstance(child, list) else [child]:
                problem = _schema_problem(item, f"{where}.{key}")
                if problem is not None:
                    return problem
    return None


def tool_problem(tools: object) -> str | None:
    """A `strict` tool definition the API would refuse. The fake answers it with a 400, because
    the paid smoke is the only other place the real API's limits would show."""
    if not isinstance(tools, list):
        return None
    for index, definition in enumerate(tools):
        if isinstance(definition, dict) and definition.get("strict") is True:
            problem = _schema_problem(definition.get("input_schema"), f"tools.{index}.input_schema")
            if problem is not None:
                return problem
    return None


def request_problem(messages: object) -> str | None:
    """What the real API refuses and a stored history must never hold: a turn with no content, or a
    `tool_use` whose input is not an object. The fake answers it with a 400, so drift of this class
    fails a test instead of passing because the fake was lenient."""
    if not isinstance(messages, list):
        return None
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if content == []:
            return f"messages.{index}: content must not be empty"
        for block in _blocks(content):
            if block.get("type") == "tool_use" and not isinstance(block.get("input"), dict):
                return f"messages.{index}.content: tool_use input must be an object"
        if message.get("role") == "assistant":
            problem = _fallback_problem(messages, index)
            if problem is not None:
                return problem
    return None


def _fallback_problem(messages: list[object], index: int) -> str | None:
    """The wire rule for an assistant turn that holds a `fallback` block (the API's "Continuing the
    conversation"): `thinking`, `redacted_thinking` and `tool_use` before the final `fallback` are
    dropped by the client, and the `fallback` block stays where it appeared. A turn answering a
    `[[fallback]]` message is one this fake served with the block first, so one that lacks it, or
    holds it elsewhere, was omitted or moved."""
    message = messages[index]
    assert isinstance(message, dict)
    blocks = _blocks(message.get("content"))
    kinds = [block.get("type") for block in blocks]
    final = max((i for i, kind in enumerate(kinds) if kind == "fallback"), default=-1)
    if any(
        kind in {"thinking", "redacted_thinking", "tool_use"} for kind in kinds[: max(final, 0)]
    ):
        return f"messages.{index}.content: thinking and tool_use must not precede a fallback block"
    previous = messages[index - 1] if index > 0 else None
    if isinstance(previous, dict) and previous.get("role") == "user":
        marked = any(
            "[[fallback]]" in str(block.get("text", ""))
            for block in _blocks(previous.get("content"))
        )
        if marked and kinds[:1] != ["fallback"]:
            return f"messages.{index}.content: the fallback block was omitted or moved"
    return None


def tool_results_of(messages: object) -> list[str]:
    """The text of each `tool_result` after the last user message that holds text: what this run's
    tools have returned so far, oldest first."""
    if not isinstance(messages, list):
        return []
    results: list[str] = []
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        blocks = _blocks(message.get("content"))
        found = [block for block in blocks if block.get("type") == "tool_result"]
        if not found:
            break
        results[:0] = [str(block.get("content", "")) for block in found]
    return results


def tool_names_of(tools: object) -> set[str]:
    if not isinstance(tools, list):
        return set()
    return {str(tool["name"]) for tool in tools if isinstance(tool, dict) and "name" in tool}


def markers_of(text: str) -> dict[str, str]:
    return {match.group(1): match.group(2) or "" for match in MARKER.finditer(text)}


def _message_start(model: str) -> bytes:
    return _event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": f"msg_{uuid.uuid4().hex[:12]}",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 1},
            },
        },
    )


message_start_event = _message_start


def _message_end(stop_reason: str) -> list[bytes]:
    return [
        _event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 5},
            },
        ),
        _event("message_stop", {"type": "message_stop"}),
    ]


def _text_start(index: int) -> bytes:
    return _event(
        "content_block_start",
        {
            "type": "content_block_start",
            "index": index,
            "content_block": {"type": "text", "text": ""},
        },
    )


def _text_delta(index: int, text: str) -> bytes:
    return _event(
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": index,
            "delta": {"type": "text_delta", "text": text},
        },
    )


def _stop(index: int) -> bytes:
    return _event("content_block_stop", {"type": "content_block_stop", "index": index})


def _tool_use(index: int, name: str, arguments: object) -> list[bytes]:
    return [
        _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {
                    "type": "tool_use",
                    "id": f"toolu_{uuid.uuid4().hex[:12]}",
                    "name": name,
                    "input": {},
                },
            },
        ),
        _event(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "input_json_delta", "partial_json": json.dumps(arguments)},
            },
        ),
        _stop(index),
    ]


async def _chunks(index: int, chunks: tuple[str, ...]) -> AsyncIterator[bytes]:
    yield _text_start(index)
    for chunk in chunks:
        yield _text_delta(index, chunk)
        await asyncio.sleep(timings["chunk_delay"])
    yield _stop(index)


async def _hold(key: str) -> None:
    event = _released.setdefault(key, asyncio.Event())
    try:
        await asyncio.wait_for(event.wait(), HOLD_TIMEOUT_SECONDS)
    except TimeoutError:
        return
    finally:
        _released.pop(key, None)


def _arguments_for(name: str) -> Json:
    """A valid input for the tool: `knowledge__search` takes a query, the scripted tools a text."""
    return {"query": SEMANTIC_QUERY} if name == SEARCH_TOOL else {"text": "hi"}


def _cited(result: str) -> str:
    """The answer a research run gives from its last search: the file and lines of the best hit,
    or that nothing was found (an error result and an empty `hits` are the same to a reader)."""
    try:
        parsed = json.loads(result)
    except ValueError:
        return NO_ANSWER
    hits = parsed.get("hits") if isinstance(parsed, dict) else None
    if not isinstance(hits, list) or not hits or not isinstance(hits[0], dict):
        return NO_ANSWER
    best = hits[0]
    return f"It is in `{best['path']}:{best['startLine']}-{best['endLine']}`."


async def _research(results: list[str], offered: set[str]) -> AsyncIterator[bytes]:
    """`[[research]]`: search, search again, then cite what the last result holds. Without the
    search tool (a server that was down) it says so and calls nothing."""
    if SEARCH_TOOL not in offered:
        text = NOT_OFFERED
    elif len(results) < len(RESEARCH_QUERIES):
        for part in _tool_use(0, SEARCH_TOOL, {"query": RESEARCH_QUERIES[len(results)]}):
            yield part
        for part in _message_end("tool_use"):
            yield part
        return
    else:
        text = _cited(results[-1])
    async for part in _chunks(0, (text,)):
        yield part
    for part in _message_end("end_turn"):
        yield part


async def script(
    model: str,
    text: str,
    continuation: bool,
    results: list[str] | None = None,
    offered: set[str] | None = None,
) -> AsyncIterator[bytes]:
    marks = markers_of(text)
    yield _message_start(model)

    if "research" in marks:
        async for part in _research(results or [], offered or set()):
            yield part
        return

    if "stream_error" in marks:
        async for part in _chunks(0, ANSWER_CHUNKS[:1]):
            yield part
        yield _event(
            "error",
            {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
        )
        return
    if "refuse" in marks:
        for part in _message_end("refusal"):
            yield part
        return
    if "truncate" in marks:
        async for part in _chunks(0, ANSWER_CHUNKS[:2]):
            yield part
        for part in _message_end("max_tokens"):
            yield part
        return

    if "empty" in marks and not continuation:
        for part in _message_end("end_turn"):
            yield part
        return
    if "context_limit" in marks:
        for part in _message_end("model_context_window_exceeded"):
            yield part
        return
    if "unknown_stop" in marks:
        for part in _message_end("a_stop_reason_nobody_knows"):
            yield part
        return
    if "pause" in marks and not continuation:
        async for part in _chunks(0, ANSWER_CHUNKS[:1]):
            yield part
        for part in _message_end("pause_turn"):
            yield part
        return
    if "stop_sequence" in marks:
        async for part in _chunks(0, ANSWER_CHUNKS[:1]):
            yield part
        for part in _message_end("stop_sequence"):
            yield part
        return

    wants_tool = ("loop" in marks) or (
        not continuation
        and bool({"tool", "badtool", "stringinput", "nulinput", "many", "parallel"} & marks.keys())
    )
    if wants_tool:
        calls: list[tuple[str, object]]
        if "parallel" in marks:
            calls = [("lab__first", {"text": "a"}), ("lab__second", {"text": "b"})]
        elif "stringinput" in marks:
            calls = [(marks["stringinput"], "this is not an object")]
        elif "nulinput" in marks:
            calls = [(marks["nulinput"], {"text": "a\x00b"})]
        elif "badtool" in marks:
            calls = [(marks["badtool"], {"nope": 1})]
        elif "many" in marks:
            calls = [(marks["many"], _arguments_for(marks["many"])) for _ in range(MANY_CALLS)]
        else:
            name = marks.get("tool") or "lookup"
            calls = [(name, _arguments_for(name))]
        for index, (name, arguments) in enumerate(calls):
            for part in _tool_use(index, name, arguments):
                yield part
        for part in _message_end("tool_use"):
            yield part
        return

    index = 0
    if "fallback" in marks:
        yield _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "fallback",
                    "from": {"model": model},
                    "to": {"model": "claude-opus-4-8"},
                    "trigger": {"type": "refusal"},
                },
            },
        )
        yield _stop(0)
        index = 1
    if continuation:
        chunks: tuple[str, ...] = (TOOL_DONE,)
    elif "hold" in marks:
        async for part in _chunks(index, HOLD_CHUNKS[:1]):
            if part.startswith(b"event: content_block_stop"):
                await _hold(marks["hold"])
                yield _text_delta(index, HOLD_CHUNKS[1])
            yield part
        for part in _message_end("end_turn"):
            yield part
        return
    else:
        chunks = ANSWER_CHUNKS
    async for part in _chunks(index, chunks):
        yield part
    for part in _message_end("end_turn"):
        yield part


async def messages(request: Request) -> Response:
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"type": "error", "error": {"type": "invalid_request_error"}}, 400)
    problem = request_problem(body.get("messages")) or tool_problem(body.get("tools"))
    if problem is not None:
        return JSONResponse(
            {"type": "error", "error": {"type": "invalid_request_error", "message": problem}}, 400
        )
    text, continuation = script_text(body.get("messages"))
    model = body.get("model")
    return StreamingResponse(
        script(
            model if isinstance(model, str) else "fake",
            text,
            continuation,
            tool_results_of(body.get("messages")),
            tool_names_of(body.get("tools")),
        ),
        media_type="text/event-stream",
    )


async def release(request: Request) -> Response:
    key = request.path_params["key"]
    _released.setdefault(key, asyncio.Event()).set()
    return JSONResponse({"released": key})


async def health(_request: Request) -> Response:
    return JSONResponse({"status": "ok"})


app: Final = Starlette(
    routes=[
        Route("/v1/messages", messages, methods=["POST"]),
        Route("/release/{key}", release, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ]
)


def main(environ: Mapping[str, str] = os.environ) -> None:
    import uvicorn  # only the e2e entry starts a server

    uvicorn.run(app, host="127.0.0.1", port=int(environ.get("FAKE_ANTHROPIC_PORT", "8101")))


if __name__ == "__main__":
    main()
