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
- `[[links]]`: an answer whose links try to hide where they go (`LINK_CHUNKS`).
- `[[parallel]]`: the first call asks for two tools (`lab__first` and `lab__second`) in one turn.
- `[[trio]]`: the first call asks for `lab__echo`, `lab__lookup` and `lab__loose`, in that order.
- `[[github_comment]]`: asks for `github__add_issue_comment` with a valid input whose `body` is 60
  lines (`GITHUB_COMMENT_BODY`), long enough to run past a screen; after the result the answer is
  "Tool done.". `[[tool:github__issue_read]]` and `[[tool:github__get_file_contents]]` ask for those
  with valid inputs (`GITHUB_ARGUMENTS`).
- `[[github_minimum]]`: asks for `github__add_issue_comment` with a `comment_id` of 0, which the
  recorded schema's `minimum: 1` refuses.
- `[[pair]]`: one turn asks for `knowledge__search` and `github__issue_read` together.
- `[[twice:NAME]]`: asks for NAME with `{"text": "hi"}`, then, after its result, again with
  `{"text": "hi2"}`, then answers.
- `[[think]]`: a `thinking` block opens a tool call or an answer. Its signature is a SHA-256 over
  the request's `system`, its tools sorted by name and the messages before it, and the fake refuses
  (400) a replayed block whose prefix changed, as the real API does under
  `prefix_mismatch_behavior: "error"`.
- `[[fallback_tool:NAME]]`: a `tool_use` of NAME, a `fallback` block, then a `tool_use` of NAME:
  only the last is served, the first is stored and never run.
- `[[loop]]`: every call asks for a tool, so the run reaches its turn limit.
- `[[refuse]]`: `stop_reason: refusal`, no content.
- `[[truncate]]`: some text, then `stop_reason: max_tokens`.
- `[[stream_error]]`: some text, then an `overloaded_error` event in the middle of the stream.
  Beside a first-turn tool marker (`tool`, `trio`...), the tool turn comes first and the turn
  after its result fails.
- `[[fallback]]`: a `fallback` block, then the answer from the serving model.
- `[[research]]`: asks for `knowledge__search` with a semantic query, then with a keyword one, then
  cites `path:start-end` of the first hit in the last tool result, or says the knowledge base holds
  no answer (no hits, or an error result). When the request does not offer the tool, it says it
  cannot search and calls nothing.

- `[[recall]]`: asks for `knowledge__recall` with `{"query": RECALL_QUERY}`, then answers from the
  last tool result: `From memory: <content>; <content>` (each memory, best first), or `Nothing is
  remembered.` for an empty list or an error result. When the request does not offer the tool, it
  says it cannot recall and calls nothing.

A request without `stream` is a side call (memory extraction, `parse_turn` in
`services/anthropic.py`), answered as one JSON message, not a script above:

- `[[fact:TEXT]]` (TEXT is anything up to `]]`, spaces included; repeatable): the answer is
  `{"facts": [TEXT, ...]}`, in order. A message with no `fact` marker has no facts.
- `[[extract_refused]]`: `stop_reason: refusal`, no content. `[[extract_cut]]`: `max_tokens` with
  half a JSON text. `[[extract_invalid]]`: text that is not JSON, every time.
  `[[extract_invalid_once]]`: that text the first time the message is seen, valid afterwards.
- It is refused (400) when it sends `fallbacks`, `tools`, `temperature`, `top_p`, `top_k`, a
  `thinking` that is not adaptive, no `output_config.effort`, or a format schema `strict` refuses.

A request is also checked for what the real API refuses: an empty turn, a `tool_use` input that is
not an object, a `tool_use` whose next user turn lacks its `tool_result`, a replayed `thinking`
block whose prefix changed, and a `strict` tool whose schema holds a keyword `strict` does not
support or an object that is not closed. Each is a 400.
"""

import asyncio
import hashlib
import json
import os
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from typing import Final

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from tests.fixture_repository import KEYWORD_QUERY, SEMANTIC_QUERY

MARKER: Final = re.compile(r"\[\[([a-z_]+)(?::([A-Za-z0-9_-]+))?\]\]")
# `[[fact:TEXT]]`: TEXT is anything up to `]]`, spaces included, unlike the other markers.
FACT_MARKER: Final = re.compile(r"\[\[fact:(.+?)\]\]", re.DOTALL)
ANSWER_CHUNKS: Final = ("Hello! ", "This is the **scripted** answer.\n\n", "- one\n", "- two\n")
HOLD_CHUNKS: Final = ("The first part. ", "The rest, **done**.")
# A steered answer. Each link hides where it goes in a way only a browser's layout can show: a
# direction override in its words, or before a bare URL that then reads as GitHub's, a label long
# enough to push what follows off the screen, a first column that cuts a table at its edge. Built
# from a code point, so no invisible character lives in this file.
_OVERRIDE: Final = chr(0x202E)
LINK_CHUNKS: Final = (
    f"See [the docs{_OVERRIDE}](https://moc.buhtig.se/?d=secret) next.\n\n",
    f"{_OVERRIDE}https://evil.example/moc.buhtig//:sptth\n\n",
    "[a long label" + " word" * 600 + "](https://far.example/)\n\n",
    "| A | B |\n| --- | --- |\n",
    f"| {'x' * 92} | [in a table](https://github.com.evil.example/?d=x) |\n",
)
TOOL_DONE: Final = "Tool done."
# `[[research]]` searches the fixture repository twice (the second query is a keyword the first
# answer does not hold), then cites the last result.
SEARCH_TOOL: Final = "knowledge__search"
RESEARCH_QUERIES: Final = (SEMANTIC_QUERY, KEYWORD_QUERY)
MANY_CALLS: Final = 14
TWICE_TEXTS: Final = ("hi", "hi2")
# `[[github_comment]]` asks to comment on an issue. The body runs past a screen on a phone, so the
# e2e journey proves the whole of it sits above the decision buttons, with no inner scroll.
GITHUB_COMMENT_LINES: Final = 60
GITHUB_COMMENT_BODY: Final = "\n".join(
    f"Scripted comment, line {number} of {GITHUB_COMMENT_LINES}."
    for number in range(1, GITHUB_COMMENT_LINES + 1)
)
GITHUB_COMMENT_TOOL: Final = "github__add_issue_comment"
GITHUB_ARGUMENTS: Final[dict[str, dict[str, object]]] = {
    GITHUB_COMMENT_TOOL: {
        "owner": "octo-org",
        "repo": "hello-world",
        "issue_number": 7,
        "body": GITHUB_COMMENT_BODY,
    },
    "github__issue_read": {
        "method": "get",
        "owner": "octo-org",
        "repo": "hello-world",
        "issue_number": 7,
    },
    "github__get_file_contents": {"owner": "octo-org", "repo": "hello-world", "path": "README.md"},
}
# `[[recall]]` asks for what the person told the assistant, then answers from the result.
RECALL_TOOL: Final = "knowledge__recall"
RECALL_QUERY: Final = "what the person told the assistant before"
NOTHING_REMEMBERED: Final = "Nothing is remembered."
NOT_RECALLABLE: Final = "I cannot recall anything right now."
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
            problem = _fallback_problem(messages, index) or _unanswered_problem(messages, index)
            if problem is not None:
                return problem
    return None


def _unanswered_problem(messages: list[object], index: int) -> str | None:
    """A `tool_use` must be answered by a `tool_result` in the next user turn, which holds one for
    each of them. The last message may be an assistant turn (a continued `pause_turn`)."""
    message = messages[index]
    assert isinstance(message, dict)
    asked = [
        str(block.get("id"))
        for block in _blocks(message.get("content"))
        if block.get("type") == "tool_use"
    ]
    if not asked or index + 1 >= len(messages):
        return None
    following = messages[index + 1]
    answered = (
        {
            str(block.get("tool_use_id"))
            for block in _blocks(following.get("content"))
            if block.get("type") == "tool_result"
        }
        if isinstance(following, dict) and following.get("role") == "user"
        else set()
    )
    missing = [identifier for identifier in asked if identifier not in answered]
    if missing:
        return f"messages.{index}: tool_use ids were found without tool_result blocks after them"
    return None


def prefix_signature(system: object, tools: object, preceding: list[object]) -> str:
    """What a `thinking` block's signature stands for: the system prompt, the tool set (by name)
    and every message before the turn that holds the block."""
    ordered = (
        sorted((t for t in tools if isinstance(t, dict)), key=lambda t: str(t.get("name")))
        if isinstance(tools, list)
        else []
    )
    encoded = json.dumps([system, ordered, preceding], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def binding_problem(body: Json) -> str | None:
    """The real API's refusal of a replayed `thinking` block whose prefix is not the one it was
    signed over (`prefix_mismatch_behavior: "error"`)."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return None
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for block in _blocks(message.get("content")):
            signature = block.get("signature")
            if block.get("type") == "thinking" and isinstance(signature, str) and signature:
                expected = prefix_signature(body.get("system"), body.get("tools"), messages[:index])
                if signature != expected:
                    return (
                        f"messages.{index}.content: thinking block signature does not match the "
                        "system, tools and messages before it"
                    )
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


_FIRST_TURN_TOOLS = frozenset(
    {
        "tool",
        "badtool",
        "stringinput",
        "nulinput",
        "many",
        "parallel",
        "trio",
        "fallback_tool",
        "github_comment",
        "github_minimum",
        "pair",
    }
)


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
    """A valid input for the tool: `knowledge__search` takes a query, a GitHub tool what its
    recorded schema requires, the scripted tools a text."""
    if name == SEARCH_TOOL:
        return {"query": SEMANTIC_QUERY}
    if name == RECALL_TOOL:
        return {"query": RECALL_QUERY}
    if name in GITHUB_ARGUMENTS:
        return dict(GITHUB_ARGUMENTS[name])
    return {"text": "hi"}


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


def _remembered(result: str) -> str:
    """The answer a recall run gives from its tool result: each memory's content, best first, or
    that nothing is remembered (an empty list and an error result are the same to a reader)."""
    try:
        parsed = json.loads(result)
    except ValueError:
        return NOTHING_REMEMBERED
    memories = parsed.get("memories") if isinstance(parsed, dict) else None
    contents = [
        str(memory["content"])
        for memory in memories or []
        if isinstance(memory, dict) and "content" in memory
    ]
    return f"From memory: {'; '.join(contents)}" if contents else NOTHING_REMEMBERED


async def _recall(results: list[str], offered: set[str]) -> AsyncIterator[bytes]:
    """`[[recall]]`: asks `knowledge__recall`, then answers from its result. Without the tool (a
    conversation started before it existed, or a server that was down) it says so and calls
    nothing."""
    if RECALL_TOOL not in offered:
        text = NOT_RECALLABLE
    elif not results:
        for part in _tool_use(0, RECALL_TOOL, {"query": RECALL_QUERY}):
            yield part
        for part in _message_end("tool_use"):
            yield part
        return
    else:
        text = _remembered(results[-1])
    async for part in _chunks(0, (text,)):
        yield part
    for part in _message_end("end_turn"):
        yield part


def _fallback_block(index: int, model: str) -> list[bytes]:
    return [
        _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {
                    "type": "fallback",
                    "from": {"model": model},
                    "to": {"model": "claude-opus-4-8"},
                    "trigger": {"type": "refusal"},
                },
            },
        ),
        _stop(index),
    ]


def _thinking(index: int, signature: str) -> list[bytes]:
    return [
        _event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "thinking", "thinking": "", "signature": ""},
            },
        ),
        _event(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "thinking_delta", "thinking": "Considering the request."},
            },
        ),
        _event(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "signature_delta", "signature": signature},
            },
        ),
        _stop(index),
    ]


async def script(
    model: str,
    text: str,
    continuation: bool,
    results: list[str] | None = None,
    offered: set[str] | None = None,
    signature: str = "",
) -> AsyncIterator[bytes]:
    marks = markers_of(text)
    yield _message_start(model)

    if "research" in marks:
        async for part in _research(results or [], offered or set()):
            yield part
        return
    if "recall" in marks:
        async for part in _recall(results or [], offered or set()):
            yield part
        return

    # With a tool marker beside it, the first turn asks for the tool and the turn after its result
    # is the one that fails: a model failure on the turn after a resume.
    if "stream_error" in marks and (continuation or not marks.keys() & _FIRST_TURN_TOOLS):
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

    done = len(results or [])
    twice = "twice" in marks and done < len(TWICE_TEXTS)
    wants_tool = (
        ("loop" in marks) or twice or (not continuation and bool(_FIRST_TURN_TOOLS & marks.keys()))
    )
    if wants_tool:
        calls: list[tuple[str, object]]
        base = 0
        if "think" in marks:
            for part in _thinking(0, signature):
                yield part
            base = 1
        if twice:
            calls = [(marks["twice"], {"text": TWICE_TEXTS[done]})]
        elif "trio" in marks:
            calls = [(f"lab__{name}", {"text": "a"}) for name in ("echo", "lookup", "loose")]
        elif "fallback_tool" in marks:
            name = marks["fallback_tool"]
            for part in _tool_use(base, name, _arguments_for(name)):
                yield part
            for part in _fallback_block(base + 1, model):
                yield part
            base += 2
            calls = [(name, _arguments_for(name))]
        elif "github_comment" in marks:
            calls = [(GITHUB_COMMENT_TOOL, _arguments_for(GITHUB_COMMENT_TOOL))]
        elif "github_minimum" in marks:
            # `comment_id` has `minimum: 1`, a keyword the API no longer checks without `strict`.
            calls = [
                (
                    GITHUB_COMMENT_TOOL,
                    {**_arguments_for("github__issue_read"), "comment_id": 0, "reaction": "eyes"},
                )
            ]
        elif "pair" in marks:
            calls = [
                (SEARCH_TOOL, _arguments_for(SEARCH_TOOL)),
                ("github__issue_read", _arguments_for("github__issue_read")),
            ]
        elif "parallel" in marks:
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
            for part in _tool_use(base + index, name, arguments):
                yield part
        for part in _message_end("tool_use"):
            yield part
        return

    index = 0
    if "fallback" in marks:
        for part in _fallback_block(0, model):
            yield part
        index = 1
    if "think" in marks:
        for part in _thinking(index, signature):
            yield part
        index += 1
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
    elif "links" in marks:
        chunks = LINK_CHUNKS
    else:
        chunks = ANSWER_CHUNKS
    async for part in _chunks(index, chunks):
        yield part
    for part in _message_end("end_turn"):
        yield part


# `[[extract_invalid_once]]` answers invalid text the first time a message is seen, then valid.
_invalid_once_seen: set[str] = set()


def side_call_problem(body: Json) -> str | None:
    """What the real API refuses in a side call (a non-streamed request with a structured output):
    the parameters that return 400 on the current models, and a format schema `strict` would not
    accept. A side call never sends `fallbacks`, so one that does is refused here."""
    for name in ("temperature", "top_p", "top_k", "fallbacks", "tools", "tool_choice"):
        if name in body:
            return f"{name}: not part of a side call"
    thinking = body.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") != "adaptive":
        return "thinking: only adaptive is accepted"
    output = body.get("output_config")
    if not isinstance(output, dict) or output.get("effort") not in {"low", "medium", "high"}:
        return "output_config.effort must be set explicitly"
    format_ = output.get("format")
    if not isinstance(format_, dict) or format_.get("type") != "json_schema":
        return "output_config.format must be a json_schema"
    return _schema_problem(format_.get("schema"), "output_config.format.schema")


def side_facts(text: str) -> list[str]:
    """The facts an extraction side call should return: each `[[fact:TEXT]]` marker of the message
    (TEXT is anything but `]]`), in order."""
    return [match.group(1).strip() for match in FACT_MARKER.finditer(text)]


def _side_message(model: str, text: str | None, stop_reason: str = "end_turn") -> JSONResponse:
    content: list[Json] = [] if text is None else [{"type": "text", "text": text}]
    return JSONResponse(
        {
            "id": f"msg_{uuid.uuid4().hex[:12]}",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        }
    )


def side_call(body: Json, text: str) -> JSONResponse:
    """The answer to a non-streamed request: memory extraction. `[[fact:TEXT]]` markers become the
    `facts`; `[[extract_refused]]`, `[[extract_cut]]`, `[[extract_invalid]]` and
    `[[extract_invalid_once]]` script the failures; a message with no marker has no facts."""
    model = body.get("model")
    name = model if isinstance(model, str) else "fake"
    marks = markers_of(text)
    if "extract_refused" in marks:
        return _side_message(name, None, "refusal")
    if "extract_cut" in marks:
        return _side_message(name, '{"facts": ["', "max_tokens")
    if "extract_invalid" in marks:
        return _side_message(name, "these are not facts")
    if "extract_invalid_once" in marks and text not in _invalid_once_seen:
        _invalid_once_seen.add(text)
        return _side_message(name, "these are not facts")
    return _side_message(name, json.dumps({"facts": side_facts(text)}))


async def messages(request: Request) -> Response:
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"type": "error", "error": {"type": "invalid_request_error"}}, 400)
    problem = (
        request_problem(body.get("messages"))
        or tool_problem(body.get("tools"))
        or binding_problem(body)
        or (None if body.get("stream") else side_call_problem(body))
    )
    if problem is not None:
        return JSONResponse(
            {"type": "error", "error": {"type": "invalid_request_error", "message": problem}}, 400
        )
    text, continuation = script_text(body.get("messages"))
    if not body.get("stream"):
        return side_call(body, text)
    model = body.get("model")
    sent = body.get("messages")
    return StreamingResponse(
        script(
            model if isinstance(model, str) else "fake",
            text,
            continuation,
            tool_results_of(sent),
            tool_names_of(body.get("tools")),
            prefix_signature(
                body.get("system"), body.get("tools"), sent if isinstance(sent, list) else []
            ),
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


GITHUB_PATH: Final = "/github/mcp"


def with_note_server(
    note: Callable[[Scope, Receive, Send], Awaitable[None]],
    github: Callable[[Scope, Receive, Send], Awaitable[None]] | None = None,
) -> ASGIApp:
    """The fake plus the `fixture` MCP server at `/mcp` (`tests/fake_note.py`) and, when given, the
    scripted `github-mcp-server` at `/github/mcp` (`tests/fake_github_mcp.py`), in one process: the
    lifespan enters each server's, their paths go to them, the rest to the fake. `note` and `github`
    are `McpApp`s, whose own `lifespan()` the fake needs while it serves; the GitHub one serves
    `/mcp` itself, so its path is rewritten."""
    servers = [note] if github is None else [note, github]

    async def serve(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            async with AsyncExitStack() as stack:
                for server in servers:
                    await stack.enter_async_context(server.lifespan())  # type: ignore[attr-defined]
                while True:
                    message = await receive()
                    if message["type"] == "lifespan.startup":
                        await send({"type": "lifespan.startup.complete"})
                    elif message["type"] == "lifespan.shutdown":
                        await send({"type": "lifespan.shutdown.complete"})
                        return
        elif scope["type"] == "http" and scope["path"] == "/mcp":
            await note(scope, receive, send)
        elif github is not None and scope["type"] == "http" and scope["path"] == GITHUB_PATH:
            await github({**scope, "path": "/mcp"}, receive, send)
        else:
            await app(scope, receive, send)

    return serve


def main(environ: Mapping[str, str] = os.environ) -> None:
    import uvicorn  # only the e2e entry starts a server

    from tests.fake_github_mcp import E2E_TOKEN, Github, create_github_app
    from tests.fake_note import create_note_app  # loads the app's MCP seam, so not at import

    port = int(environ.get("FAKE_ANTHROPIC_PORT", "8101"))
    hosts = [f"127.0.0.1:{port}", f"localhost:{port}"]
    # The bearer the API sends is `GITHUB_MCP_TOKEN` of its web server; the placeholder is the
    # default of both sides, so a config that sets nothing still agrees.
    github = create_github_app(
        Github(), token=environ.get("GITHUB_MCP_TOKEN") or E2E_TOKEN, allowed_hosts=hosts
    )
    uvicorn.run(with_note_server(create_note_app(port), github), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
