"""The parse worker, with real children: no mock stands in for the process, because the deadline,
the crash handling and the isolation are the properties this file proves (V05, V06)."""

import asyncio
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.config.constants import SYMBOL_NAME_MAX, ParseLimits
from app.models.source.type import Symbol
from app.services import parse
from app.services.parse import ParseSession, ParseSessionClosed
from tests.fixture_repository import (
    JAVASCRIPT_SOURCE,
    PYTHON_SOURCE,
    TSX_SOURCE,
    TYPESCRIPT_SOURCE,
)

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"

# The probe's crafted inputs: parse time grows about with the square of their size.
CRAFTED_TYPESCRIPT = "\"'" * 40_000
CRAFTED_PYTHON = "def (:\n" * 12_000
SECRET_NAMES = (
    "JWT_ACCESS_SECRET",
    "JWT_REFRESH_SECRET",
    "OTP_SECRET",
    "ENCRYPTION_KEY",
    "DATABASE_URL",
    "ANTHROPIC_API_KEY",
    "VOYAGE_API_KEY",
)


def limits(file_seconds: float = 0.6, index_seconds: float = 30.0) -> ParseLimits:
    return ParseLimits(file_seconds=file_seconds, index_seconds=index_seconds)


@pytest.fixture
def session() -> Iterator[ParseSession]:
    with ParseSession(limits()) as opened:
        yield opened


class TestSymbols:
    def test_finds_the_python_definitions(self, session: ParseSession) -> None:
        symbols = session.symbols("python", PYTHON_SOURCE)

        assert symbols is not None
        assert [(s.name, s.start_line, s.end_line) for s in symbols] == [
            ("Greeter", 6, 11),
            ("shout", 14, 15),
            ("decorator", 18, 19),
            ("main", 22, 24),
        ]

    def test_finds_the_javascript_definitions(self, session: ParseSession) -> None:
        symbols = session.symbols("javascript", JAVASCRIPT_SOURCE)

        assert symbols is not None
        assert [(s.name, s.start_line, s.end_line) for s in symbols] == [
            ("add", 3, 5),
            ("double", 7, 7),
            ("Counter", 9, 16),
        ]

    def test_finds_the_typescript_definitions(self, session: ParseSession) -> None:
        symbols = session.symbols("typescript", TYPESCRIPT_SOURCE)

        assert symbols is not None
        assert [s.name for s in symbols] == ["Point", "Id", "norm", "Box", "Color"]
        assert symbols[0] == Symbol(name="Point", start_line=1, end_line=4)

    def test_finds_the_tsx_definitions(self, session: ParseSession) -> None:
        symbols = session.symbols("tsx", TSX_SOURCE)

        assert symbols is not None
        assert [(s.name, s.start_line, s.end_line) for s in symbols] == [
            ("Hello", 3, 5),
            ("Bye", 7, 7),
        ]

    def test_counts_lines_on_newlines_only(self, session: ParseSession) -> None:
        """A form feed is not a line break: the numbers are GitHub's."""
        source = "x = 1\n\x0c\ndef f():\n    return 1\n"

        symbols = session.symbols("python", source)

        assert symbols == [Symbol(name="f", start_line=3, end_line=4)]

    def test_gives_no_symbols_for_a_file_that_fails_to_parse(self, session: ParseSession) -> None:
        assert session.symbols("python", "def (:\n") is None

    def test_gives_no_symbols_for_an_unknown_language_and_starts_no_child(self) -> None:
        with ParseSession(limits()) as opened:
            assert opened.symbols("cobol", "IDENTIFICATION DIVISION.") is None
            assert opened.started == 0

    def test_keeps_one_child_across_files(self, session: ParseSession) -> None:
        session.symbols("python", PYTHON_SOURCE)
        session.symbols("javascript", JAVASCRIPT_SOURCE)

        assert session.started == 1


class TestTheChildIsolation:
    def test_environment_holds_no_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in SECRET_NAMES:
            monkeypatch.setenv(name, f"secret-value-of-{name}")

        environment = parse.child_environment()

        assert not any(name in environment for name in SECRET_NAMES)
        assert not any("secret-value" in value for value in environment.values())
        assert set(environment) <= {"SYSTEMROOT"}

    def test_the_running_child_holds_no_secret_and_imports_nothing_of_the_app_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in SECRET_NAMES:
            monkeypatch.setenv(name, f"secret-value-of-{name}")
        with ParseSession(limits()) as opened:
            report = opened.inspect()

        assert report is not None
        assert not any(name in report.environment for name in SECRET_NAMES)
        assert not any("secret-value" in value for value in report.environment.values())
        assert not any(module.startswith("app.config") for module in report.modules)
        assert not any(module.startswith("app.api") for module in report.modules)
        assert "app.services.parse_worker" in report.modules

    def test_the_child_is_a_separate_process(self) -> None:
        with ParseSession(limits()) as opened:
            opened.symbols("python", "x = 1\n")
            assert opened.child_pid is not None
            assert opened.child_pid != os.getpid()


class TestTheDeadline:
    def test_kills_a_crafted_typescript_file_at_its_deadline(self) -> None:
        with ParseSession(limits(file_seconds=0.6)) as opened:
            began = time.monotonic()
            symbols = opened.symbols("typescript", CRAFTED_TYPESCRIPT)
            elapsed = time.monotonic() - began

        assert symbols is None
        assert elapsed < 3, elapsed
        assert opened.overruns == 1

    def test_kills_a_crafted_python_file_at_its_deadline(self) -> None:
        with ParseSession(limits(file_seconds=0.6)) as opened:
            began = time.monotonic()
            symbols = opened.symbols("python", CRAFTED_PYTHON)
            elapsed = time.monotonic() - began

        assert symbols is None
        assert elapsed < 3, elapsed

    def test_restarts_the_child_and_parses_the_next_file(self) -> None:
        with ParseSession(limits(file_seconds=0.6)) as opened:
            assert opened.symbols("typescript", CRAFTED_TYPESCRIPT) is None
            first = opened.child_pid

            symbols = opened.symbols("python", PYTHON_SOURCE)

            assert symbols is not None
            assert opened.started == 2
            assert opened.child_pid != first

    def test_the_killed_child_is_gone(self) -> None:
        with ParseSession(limits(file_seconds=0.6)) as opened:
            opened.symbols("typescript", CRAFTED_TYPESCRIPT)

            assert opened.overruns == 1
            assert opened.child_pid is None
            assert opened.child_alive is False

    def test_a_spent_index_budget_sends_the_remaining_files_to_line_windows(self) -> None:
        with ParseSession(limits(file_seconds=0.5, index_seconds=0.7)) as opened:
            assert opened.symbols("typescript", CRAFTED_TYPESCRIPT) is None
            assert opened.symbols("typescript", CRAFTED_TYPESCRIPT) is None
            started = opened.started

            # The budget is spent: an ordinary file gets no parse and no child is started.
            assert opened.symbols("python", PYTHON_SOURCE) is None
            assert opened.started == started
            assert opened.budget_spent is True

    def test_counts_only_parse_time_against_the_budget(self) -> None:
        with ParseSession(limits(file_seconds=2, index_seconds=30)) as opened:
            opened.symbols("python", PYTHON_SOURCE)

            assert opened.spent_seconds < 5
            assert opened.budget_spent is False


class TestACrash:
    def test_a_child_that_dies_sends_that_file_to_line_windows_and_is_restarted(self) -> None:
        with ParseSession(limits()) as opened:
            assert opened.symbols("python", PYTHON_SOURCE) is not None
            assert opened.child_pid is not None
            os.kill(opened.child_pid, signal.SIGTERM)

            assert opened.symbols("python", PYTHON_SOURCE) is None
            assert opened.symbols("python", PYTHON_SOURCE) is not None
            assert opened.started == 2
            assert opened.crashes == 1


class TestTheEnd:
    def test_close_ends_the_child(self) -> None:
        opened = ParseSession(limits())
        opened.symbols("python", "x = 1\n")
        pid_alive = opened.child_alive

        opened.close()

        assert pid_alive is True
        assert opened.child_alive is False
        assert opened.child_pid is None

    def test_close_leaves_no_process_holding_the_pipe(self) -> None:
        """The reader sees the end of the pipe only once every process that held it is gone, the
        interpreter behind a Windows launcher included."""
        opened = ParseSession(limits())
        opened.symbols("python", "x = 1\n")
        child = opened._child  # the process under test
        assert child is not None

        opened.close()

        assert child.process.poll() is not None
        assert not child._reader.is_alive()

    def test_leaving_the_block_with_an_exception_ends_the_child(self) -> None:
        opened = ParseSession(limits())

        def use_then_fail() -> None:
            with opened:
                opened.symbols("python", "x = 1\n")
                assert opened.child_alive is True
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            use_then_fail()

        assert opened.child_alive is False

    def test_close_without_a_child_and_twice_is_harmless(self) -> None:
        opened = ParseSession(limits())
        opened.close()
        opened.close()

    def test_a_closed_session_refuses_to_parse(self) -> None:
        opened = ParseSession(limits())
        opened.close()

        with pytest.raises(ParseSessionClosed):
            opened.symbols("python", "x = 1\n")

    async def test_closing_from_another_thread_frees_a_parse_in_progress(self) -> None:
        """A cancelled index closes the session from the event loop while a thread is parsing."""
        opened = ParseSession(limits(file_seconds=20))
        began = time.monotonic()

        async def close_soon() -> None:
            await asyncio.sleep(0.8)
            opened.close()

        closer = asyncio.create_task(close_soon())
        with pytest.raises(ParseSessionClosed):
            await asyncio.to_thread(opened.symbols, "typescript", CRAFTED_TYPESCRIPT)
        await closer

        assert time.monotonic() - began < 5
        assert opened.child_alive is False


PARENT_SCRIPT = """
import sys
from app.config.constants import ParseLimits
from app.services.parse import ParseSession
session = ParseSession(ParseLimits(file_seconds=120, index_seconds=120))
session.symbols("python", "x = 1\\n")
print(session.child_pid, flush=True)
print("parsing", flush=True)
session.symbols("typescript", '"\\'' * 35000)
"""


def process_exists(pid: int) -> bool:
    if os.name == "nt":
        listing = subprocess.run(  # noqa: S603  # fixed arguments, an integer pid
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return f'"{pid}"' in listing
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class TestAParentKilledOutright:
    def test_the_worker_ends_when_its_parent_is_killed_mid_parse(self) -> None:
        """What a SIGKILL of the API leaves behind: the worker finishes the parse it is in, finds
        its stdin closed and exits. It must not survive past that parse."""
        environment = {**os.environ, "PYTHONPATH": str(SOURCE_ROOT)}
        parent = subprocess.Popen(  # noqa: S603  # our own interpreter, a fixed script
            [sys.executable, "-c", PARENT_SCRIPT],
            stdout=subprocess.PIPE,
            text=True,
            env=environment,
            cwd=SOURCE_ROOT.parent,
        )
        assert parent.stdout is not None
        worker_pid = int(parent.stdout.readline())
        assert parent.stdout.readline().strip() == "parsing"
        assert process_exists(worker_pid)
        time.sleep(0.5)  # inside the crafted parse

        parent.kill()
        parent.wait(timeout=10)
        parent.stdout.close()
        began = time.monotonic()
        try:
            while process_exists(worker_pid) and time.monotonic() - began < 90:
                time.sleep(0.5)
            survived = process_exists(worker_pid)
        finally:
            if process_exists(worker_pid):
                subprocess.run(  # noqa: S603  # cleanup of a leaked test process
                    ["taskkill", "/F", "/PID", str(worker_pid)]
                    if os.name == "nt"
                    else ["kill", "-9", str(worker_pid)],
                    check=False,
                    capture_output=True,
                )

        assert survived is False, "the worker outlived its killed parent"


class TestManyCraftedFiles:
    def test_a_hundred_crafted_files_cost_the_budget_and_no_more(self) -> None:
        """The budget is spent after a few overruns; the other files are not parsed, no child is
        started for them and none is left running."""
        began = time.monotonic()
        with ParseSession(limits(file_seconds=0.3, index_seconds=1.0)) as opened:
            results = [opened.symbols("typescript", CRAFTED_TYPESCRIPT) for _ in range(100)]
            started = opened.started

        assert results == [None] * 100
        assert opened.budget_spent is True
        # Each child that is started and overruns is charged at least `file_seconds` (0.3), so a
        # 1.0 s budget allows at most 1.0 / 0.3 rounded up, plus one: 5 whatever the start costs.
        assert started <= 6, started
        # The child ends with the index: after the session, none is left running.
        assert opened.child_alive is False
        assert time.monotonic() - began < 20

    def test_a_crash_on_every_file_never_loops_unbounded(self) -> None:
        """Each file kills its child at once. The restarts are the cost; a session must still
        return for every file."""
        with ParseSession(limits(file_seconds=2)) as opened:
            for _ in range(5):
                assert opened.symbols("python", "x = 1\n") is not None
                assert opened.child_pid is not None
                os.kill(opened.child_pid, signal.SIGTERM)
                assert opened.symbols("python", "x = 1\n") is None

            assert opened.crashes == 5


class TestHostileText:
    def test_a_one_mebibyte_non_ascii_file_round_trips_through_the_pipe(self) -> None:
        text = "# " + "é😀" * 200_000 + "\ndef target():\n    return 1\n"

        with ParseSession(limits(file_seconds=20)) as opened:
            symbols = opened.symbols("python", text)

        assert symbols == [Symbol("target", 2, 3)]

    @pytest.mark.parametrize("language", ["javascript", "typescript", "tsx", "python"])
    def test_deep_nesting_ends_within_the_deadline_with_no_child_left(self, language: str) -> None:
        text = "(" * 200_000 if language != "python" else "[" * 200_000

        began = time.monotonic()
        with ParseSession(limits(file_seconds=3)) as opened:
            symbols = opened.symbols(language, text)

        assert symbols is None
        assert time.monotonic() - began < 15
        assert opened.child_alive is False

    def test_a_file_of_only_a_byte_order_mark_character_or_a_lone_newline_is_harmless(
        self, session: ParseSession
    ) -> None:
        assert session.symbols("python", "﻿") in ([], None)
        assert session.symbols("python", "\n") == []
        assert session.symbols("python", "") == []


WIDE = "x" * 300


def python_module(count: int) -> tuple[str, list[Symbol]]:
    """`count` three-line definitions, then one on a line over 256 columns."""
    text, symbols = "", []
    for n in range(count):
        text += f"def f{n}():\n    return {n}\n\n"
        symbols.append(Symbol(f"f{n}", 3 * n + 1, 3 * n + 2))
    last = 3 * count + 1
    return text + f'def wide(): return "{WIDE}"\n', [*symbols, Symbol("wide", last, last)]


def script_module(count: int, tsx: bool) -> tuple[str, list[Symbol]]:
    text, symbols = "", []
    body = "<b>{n}</b>" if tsx else "n"
    for n in range(count):
        name = f"F{n}" if tsx else f"f{n}"
        text += f"export function {name}() {{\n  return {body.replace('n', str(n), 1)};\n}}\n\n"
        symbols.append(Symbol(name, 4 * n + 1, 4 * n + 3))
    last = 4 * count + 1
    wide = f'export function wide() {{ return "{WIDE}"; }}\n'
    return text + wide, [*symbols, Symbol("wide", last, last)]


class TestLinesPastTheSmallIntegerCache:
    """The review's P0: `Point.row` and `Point.column` of tree-sitter 0.26.0 corrupt memory from
    257 upward. The fixture files were under 30 lines, so only a long module shows it: a real
    child must answer the exact numbers, and never crash."""

    @pytest.mark.parametrize(
        ("language", "module"),
        [
            ("python", python_module(200)),
            ("javascript", script_module(150, tsx=False)),
            ("typescript", script_module(150, tsx=False)),
            ("tsx", script_module(150, tsx=True)),
        ],
    )
    def test_gives_the_exact_lines_of_a_600_line_module(
        self, language: str, module: tuple[str, list[Symbol]]
    ) -> None:
        text, expected = module
        assert text.count("\n") >= 600

        with ParseSession(limits(file_seconds=10)) as opened:
            symbols = opened.symbols(language, text)

            assert symbols == expected
            assert opened.crashes == 0
            assert opened.overruns == 0

    def test_a_definition_on_a_line_over_256_columns_has_exact_lines(self) -> None:
        with ParseSession(limits(file_seconds=10)) as opened:
            symbols = opened.symbols("python", f'def wide(): return "{WIDE}"\n')

            assert symbols == [Symbol("wide", 1, 1)]
            assert opened.crashes == 0

    def test_a_definition_ending_on_line_258_is_exact(self) -> None:
        text = "x = 1\n" * 256 + "def late():\n    return 1\n"

        with ParseSession(limits(file_seconds=10)) as opened:
            assert opened.symbols("python", text) == [Symbol("late", 257, 258)]
            assert opened.crashes == 0


class TestARealShapedLargeFile:
    """Past 256 rows and columns, with decorators, nesting, multi-byte text and very wide lines,
    on a file of thousands of lines: exact ranges, no crash, no overrun."""

    @pytest.mark.parametrize("language", ["python", "javascript", "typescript", "tsx"])
    def test_five_thousand_lines_keep_exact_symbol_ranges(self, language: str) -> None:
        wide = "é" * 300
        lines: list[str] = []
        expected: list[Symbol] = []
        for n in range(1000):
            if language == "python":
                lines += [
                    f"# {wide}",
                    "@decorate",
                    f"class C{n}:",
                    f"    def m(self): return '{wide}'",
                    "",
                ]
                expected.append(Symbol(f"C{n}", len(lines) - 3, len(lines) - 1))
            else:
                jsx = "<b>1</b>" if language == "tsx" else "1"
                lines += [
                    f"// {wide}",
                    f"export class C{n} {{",
                    f"  m() {{ return {jsx}; }}",
                    "}",
                    "",
                ]
                expected.append(Symbol(f"C{n}", len(lines) - 3, len(lines) - 1))
        text = "\n".join(lines) + "\n"
        assert len(lines) >= 5000

        with ParseSession(limits(file_seconds=15)) as opened:
            symbols = opened.symbols(language, text)

            assert symbols == expected
            assert (opened.crashes, opened.overruns) == (0, 0)
            assert opened.summary().fallbacks == 0


class TestARepliesShapeIsChecked:
    """A reply is data from a process that may have gone wrong: one that is not exactly what was
    asked for is a crash for that file, never trusted."""

    @pytest.mark.parametrize(
        "reply",
        [
            {"symbols": "none"},
            {"symbols": [["a", 1]]},
            {"symbols": [["a", 3, 2]]},
            {"symbols": [["a", 0, 1]]},
            {"symbols": [["a", -1, 1]]},
            {"symbols": [["a", 1, 99]]},
            {"symbols": [["a", 1.0, 1]]},
            {"symbols": [["a", True, 1]]},
            {"symbols": [["a", "1", 2]]},
            {"symbols": [[5, 1, 1]]},
            {"symbols": [["a", 1, 1], ["b", 1, 5]]},
            {"symbols": [["a\x00b", 1, 1]]},
            {"symbols": [["\ud800", 1, 1]]},
            {"error": "internal"},
            {"error": "language"},
            {"error": []},
            {"error": {"a": 1}},
            {"error": 5},
            {"error": "something else"},
            {},
        ],
    )
    def test_a_reply_of_the_wrong_shape_is_a_crash_for_that_file(
        self, monkeypatch: pytest.MonkeyPatch, reply: dict[str, object]
    ) -> None:
        with ParseSession(limits()) as opened:
            assert opened.symbols("python", "x = 1\n") is not None  # the child is up

            def answer(self: object, message: object, seconds: float) -> dict[str, object]:
                return reply

            monkeypatch.setattr("app.services.parse._Child.request", answer)

            assert opened.symbols("python", "a = 1\nb = 2\n") is None
            assert opened.crashes == 1
            assert opened.summary().fallbacks == 1

    def test_a_syntax_error_is_counted_apart_and_is_not_a_fault(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with ParseSession(limits()) as opened:
            assert opened.symbols("python", "def (:\n") is None

            summary = opened.summary()

        assert (summary.syntax_errors, summary.crashes, summary.fallbacks) == (1, 0, 0)

    def test_a_name_over_the_limit_is_kept_without_its_name_and_not_as_a_fault(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An honest worker can send a very long identifier; the symbol keeps its lines."""
        with ParseSession(limits()) as opened:
            opened.symbols("python", "x = 1\n")
            monkeypatch.setattr(
                "app.services.parse._Child.request",
                lambda self, message, seconds: {
                    "symbols": [["n" * SYMBOL_NAME_MAX, 1, 1], ["n" * (SYMBOL_NAME_MAX + 1), 2, 2]]
                },
            )

            assert opened.symbols("python", "a = 1\nb = 2\n") == [
                Symbol("n" * SYMBOL_NAME_MAX, 1, 1),
                Symbol(None, 2, 2),
            ]
            assert opened.crashes == 0

    def test_a_one_mebibyte_identifier_through_a_real_child_loses_only_its_name(self) -> None:
        text = f"def {'n' * (1024 * 1024 - 20)}(): pass\n"

        with ParseSession(limits(file_seconds=20)) as opened:
            assert opened.symbols("python", text) == [Symbol(None, 1, 1)]
            assert opened.crashes == 0

    def test_an_answer_within_the_document_is_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with ParseSession(limits()) as opened:
            opened.symbols("python", "x = 1\n")
            monkeypatch.setattr(
                "app.services.parse._Child.request",
                lambda self, message, seconds: {"symbols": [["a", 1, 2]]},
            )

            assert opened.symbols("python", "a = 1\nb = 2\n") == [Symbol("a", 1, 2)]
            assert opened.crashes == 0


READY = 'w.write(b\'{"ready": true, "pid": %d}\\n\' % os.getpid()); w.flush();'


def stand_in(monkeypatch: pytest.MonkeyPatch, body: str, *, ready: str = READY) -> None:
    """Replaces the worker with a child that misbehaves in the way `body` says, after it has read
    one request. It speaks through real pipes, so the reader thread and the JSON parse are run."""
    code = f"import os, sys; w = sys.stdout.buffer; {ready} sys.stdin.buffer.readline(); {body}"
    monkeypatch.setattr("app.services.parse._command", lambda: [sys.executable, "-I", "-c", code])


class TestAHostileChildThroughRealPipes:
    """The reply is untrusted data end to end: whatever a child writes ends as a fallback for
    that file, never as an exception out of `symbols()`."""

    def test_a_reply_nested_deeper_than_json_can_read_is_a_crash_for_that_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stand_in(
            monkeypatch, "w.write(b'[' * 200000 + b'\\n'); w.flush(); import time; time.sleep(5)"
        )

        with ParseSession(limits(file_seconds=5)) as opened:
            assert opened.symbols("python", "x = 1\n") is None

            assert opened.crashes == 1

    def test_a_reply_with_no_end_of_line_is_cut_off_at_the_bound_and_is_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stand_in(
            monkeypatch,
            f"w.write(b'x' * {parse.MAX_REPLY_BYTES * 4}); w.flush(); import time; time.sleep(5)",
        )

        began = time.monotonic()
        with ParseSession(limits(file_seconds=5)) as opened:
            assert opened.symbols("python", "x = 1\n") is None

            assert opened.crashes == 1
        assert time.monotonic() - began < 4

    def test_a_child_that_dies_in_the_middle_of_a_line_is_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stand_in(monkeypatch, "w.write(b'{\"symbols\": ['); w.flush()")

        with ParseSession(limits(file_seconds=5)) as opened:
            assert opened.symbols("python", "x = 1\n") is None

            assert opened.crashes == 1

    @pytest.mark.parametrize(
        "pid",
        ["b'0'", "b'-1'", "b'1'", "b'true'", "b'null'", "b'\"7\"'", "str(os.getppid()).encode()"],
    )
    def test_a_pid_that_is_not_a_process_to_end_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch, pid: str
    ) -> None:
        """`os.kill` with 0 or -1 signals a group, and the parent's own pid would end the API.
        `pid` is a Python expression for the JSON text the child reports."""
        ready = f"w.write(b'{{\"ready\": true, \"pid\": ' + {pid} + b'}}\\n'); w.flush();"
        stand_in(monkeypatch, "w.write(b'{\"symbols\": []}\\n'); w.flush()", ready=ready)

        with ParseSession(limits(file_seconds=5)) as opened:
            assert opened.symbols("python", "x = 1\n") == []
            child = opened._child
            assert child is not None
            assert child.worker_pid == child.process.pid
            assert opened.child_pid not in (0, -1, 1, os.getpid(), os.getppid())


class TestFallbacksAreCounted:
    def test_counts_overruns_crashes_and_files_the_budget_skipped(self) -> None:
        with ParseSession(limits(file_seconds=0.4, index_seconds=30.0)) as opened:
            opened.symbols("python", "x = 1\n")
            assert opened.child_pid is not None
            os.kill(opened.child_pid, signal.SIGTERM)
            opened.symbols("python", "x = 1\n")  # the crash
            opened.symbols("typescript", CRAFTED_TYPESCRIPT)  # the overrun
            opened.symbols("cobol", "x")  # no grammar: not a fallback

            summary = opened.summary()

        assert (summary.crashes, summary.overruns) == (1, 1)
        assert summary.budget_skipped == 0

    def test_counts_the_files_a_spent_budget_skipped(self) -> None:
        with ParseSession(limits(file_seconds=0.3, index_seconds=0.5)) as opened:
            for _ in range(4):
                opened.symbols("typescript", CRAFTED_TYPESCRIPT)
            opened.symbols("python", "x = 1\n")
            opened.symbols("cobol", "x")

            summary = opened.summary()

        assert summary.budget_skipped >= 3
        assert summary.fallbacks == summary.overruns + summary.crashes + summary.budget_skipped


class TestAWorkerThatNeverStarts:
    """A production image with a broken grammar wheel: the child exits before it is ready."""

    def test_stops_trying_after_three_starts_in_a_row_and_parses_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.parse.WORKER_MODULE", "app.services.no_such_worker")
        with ParseSession(limits()) as opened:
            results = [opened.symbols("python", "x = 1\n") for _ in range(3)]
            assert results == [None, None, None]
            assert opened.start_failures == 3
            assert opened.budget_spent is True

            # The worker is repaired, but this index has given up on it.
            monkeypatch.undo()
            assert opened.symbols("python", "x = 1\n") is None
            assert opened.started == 0
            assert opened.child_alive is False

    def test_a_start_that_works_resets_the_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with monkeypatch.context() as broken:
            broken.setattr("app.services.parse.WORKER_MODULE", "app.services.no_such_worker")
            opened = ParseSession(limits())
            assert opened.symbols("python", "x = 1\n") is None
            assert opened.start_failures == 1

        assert opened.symbols("python", "x = 1\n") is not None
        assert opened.start_failures == 0
        opened.close()


class TestTheBudgetIsWallTime:
    def test_a_start_is_charged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Deterministic on any machine: the clock is a fake that the start advances by a known
        amount, so the budget must have been charged exactly that, however fast a start is."""
        now = [100.0]
        start_cost = 7.0
        real_start = parse._start_child

        def slow_start() -> object:
            child = real_start()
            now[0] += start_cost
            return child

        monkeypatch.setattr("app.services.parse._start_child", slow_start)
        monkeypatch.setattr("app.services.parse.time", SimpleNamespace(monotonic=lambda: now[0]))

        with ParseSession(limits(file_seconds=0.6, index_seconds=60.0)) as opened:
            assert opened.symbols("python", "x = 1\n") is not None

            assert opened.spent_seconds == start_cost

    def test_a_crash_is_charged_its_wall_time_not_nothing(self) -> None:
        with ParseSession(limits(file_seconds=5)) as opened:
            opened.symbols("python", "x = 1\n")
            before = opened.spent_seconds
            assert opened.child_pid is not None
            os.kill(opened.child_pid, signal.SIGTERM)
            opened.symbols("python", "x = 1\n")  # the crash, then nothing

            began = time.monotonic()
            assert opened.symbols("python", "x = 1\n") is not None  # a restart
            restart = time.monotonic() - began

            assert opened.spent_seconds >= before + restart * 0.9


class TestTheServerKeepsAnswering:
    async def test_health_answers_while_a_crafted_file_is_being_killed(
        self, client: httpx.AsyncClient
    ) -> None:
        """V05: a crafted file is parsed in the child, so the API process stays responsive."""
        with ParseSession(limits(file_seconds=1.5)) as opened:
            opened.symbols("python", "x = 1\n")  # the child is up before the clock starts
            work = asyncio.create_task(
                asyncio.to_thread(opened.symbols, "typescript", CRAFTED_TYPESCRIPT)
            )
            latencies: list[float] = []
            statuses: list[int] = []
            while not work.done():
                began = time.monotonic()
                res = await client.get("/api/health")
                latencies.append(time.monotonic() - began)
                statuses.append(res.status_code)
                await asyncio.sleep(0.02)

            assert await work is None
            assert opened.overruns == 1

        assert len(statuses) >= 10, statuses
        assert set(statuses) == {200}
        assert max(latencies) < 0.5, max(latencies)
