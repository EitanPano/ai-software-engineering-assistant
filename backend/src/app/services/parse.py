"""parse.py belongs: the parent side of the parse worker (`services/parse_worker.py`). A
`ParseSession` is one index's parser: a long-lived child process started on the first file it
parses, one JSON line per file over its pipes, and ended with the index.

The guarantees, each tested with a real child (`tests/services/test_parse.py`):

- Each file has `file_seconds` to answer and the whole index `index_seconds`, counted as the wall
  time of every exchange with the child, a start or a restart included. An overrun kills the child
  and the next file starts a new one; the overrun file has no symbols, so the caller falls back to
  line windows. A child that crashes, or answers something other than what was asked (a line
  outside the document, a float), is the same. A spent index budget gives every remaining file no
  symbols and starts no child. Overruns, crashes and budget-skipped files are counted
  (`summary()`), and the controller logs the counts when the index ends: a fallback is never silent.
- The child's environment holds only what the interpreter needs: no secret, however the API
  process was started. It is started with `subprocess`, not `multiprocessing`: a spawned
  `multiprocessing` child re-imports the entry module (`app.main`, and with it the secrets), and a
  forked one inherits them.
- The pipes are read by a thread, because a pipe cannot be waited on with a timeout on Windows,
  and not with asyncio's subprocess support, because the server's loop is a selector loop and
  that cannot run subprocesses there. A session is used from one worker thread; `close()` may
  come from another, and frees a parse in progress.
- The child ends on every exit path: `close()` kills it, the context manager and the controller's
  `finally` call it, and a child whose parent is gone ends at the end of its stdin.

It is isolation, not a sandbox: the child runs as the same user.
It does not belong: chunking (`services/chunk.py`) or the tree-sitter import (`parse_worker.py`).
"""

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Final, Literal, Self

from app.config.constants import PARSE_LIMITS, SYMBOL_NAME_MAX, ParseLimits
from app.models.source.type import Symbol
from app.services.logger import log

LANGUAGES: Final = frozenset({"python", "javascript", "typescript", "tsx"})
WORKER_MODULE: Final = "app.services.parse_worker"
# The child imports its grammars before it answers: that is not the file's time.
STARTUP_SECONDS: Final = 15.0
# After this many starts in a row that never became ready, the session stops trying.
MAX_START_FAILURES: Final = 3
_REAP_SECONDS: Final = 5.0
# The longest reply line read: the symbols of a 1 MiB file of `def a():0` lines are about 2 MiB.
# A child that writes more without a newline is cut off and its file is a crash.
MAX_REPLY_BYTES: Final = 8 * 1024 * 1024

type Json = dict[str, object]
type Failure = Literal["timeout", "crash"]


class ParseSessionClosed(Exception):  # noqa: N818  # named for what it says
    """The session was closed (a cancelled index) while, or before, a file was parsed."""


class _NotReady(Exception):  # noqa: N818
    """The child did not report ready."""


@dataclass(frozen=True)
class InspectReport:
    """What the child reports of itself: the `app` modules it loaded and its environment."""

    modules: list[str]
    environment: dict[str, str]


@dataclass(frozen=True)
class ParseSummary:
    """How many files of one index fell back to line windows, and why. Counts only: a path or a
    content never goes in the log."""

    overruns: int
    crashes: int
    budget_skipped: int
    # Files the grammar could not parse. Not a fault, so not in `fallbacks`, but counted and logged.
    syntax_errors: int = 0

    @property
    def fallbacks(self) -> int:
        """Files that fell back to line windows because the parse failed, not because the file
        has no syntax tree."""
        return self.overruns + self.crashes + self.budget_skipped


def child_environment() -> dict[str, str]:
    """The only variables the child gets. `SYSTEMROOT` is what a Windows interpreter needs to start;
    nothing else of the parent's environment crosses. (The child runs with `-I` and `-X utf8`, so no
    `PYTHON*` variable would be read anyway.)"""
    environment: dict[str, str] = {}
    root = os.environ.get("SYSTEMROOT")
    if root:
        environment["SYSTEMROOT"] = root
    return environment


def _command() -> list[str]:
    """The worker's command line; a test replaces it with a child that misbehaves."""
    return [sys.executable, "-I", "-X", "utf8", "-m", WORKER_MODULE]


class _Child:
    """One worker process and the thread that reads its stdout."""

    def __init__(self) -> None:
        self.process = subprocess.Popen(  # noqa: S603  # our own module, fixed arguments
            _command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=child_environment(),
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # The interpreter running the worker. It is `process.pid` unless a launcher (a Windows
        # virtual environment's `python.exe`) started it, then it is the launcher's child.
        self.worker_pid = self.process.pid
        self._lines: queue.Queue[bytes | None] = queue.Queue()
        self._reader = threading.Thread(target=self._read, name="parse-reader", daemon=True)
        self._reader.start()

    def _read(self) -> None:
        stdout = self.process.stdout
        try:
            if stdout is not None:
                while line := stdout.readline(MAX_REPLY_BYTES):
                    if not line.endswith(b"\n"):
                        break  # no end of line within the bound, or the child died mid-line
                    self._lines.put(line)
        except OSError, ValueError:
            pass
        finally:
            self._lines.put(None)  # the end of the stream: the child is gone

    def wait_ready(self, seconds: float) -> None:
        reply = self.receive(seconds)
        if not isinstance(reply, dict) or reply.get("ready") is not True:
            raise _NotReady
        pid = reply.get("pid")
        # `os.kill` with 0 or -1 signals a group, 1 is init, and this process's own pid would end
        # the API: only a plain other process id is taken.
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 1 and pid != os.getpid():
            self.worker_pid = pid

    def receive(self, seconds: float) -> Json | Failure:
        try:
            line = self._lines.get(timeout=seconds)
        except queue.Empty:
            return "timeout"
        if line is None:
            return "crash"
        try:
            reply = json.loads(line)
        except ValueError, RecursionError:  # a reply nested deeper than the parser can read
            return "crash"
        return reply if isinstance(reply, dict) else "crash"

    def request(self, message: Json, seconds: float) -> Json | Failure:
        payload = json.dumps(message).encode("ascii") + b"\n"
        try:
            stdin = self.process.stdin
            if stdin is None:
                return "crash"
            stdin.write(payload)
            stdin.flush()
        except OSError, ValueError:
            return "crash"
        return self.receive(seconds)

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def kill(self) -> None:
        """Ends the process and releases its pipes and reader. Safe to call twice."""
        with suppress(OSError):
            self.process.kill()
        # A launcher that is killed leaves its child to the operating system; end the child
        # here. Only while the child still holds the pipe open, so a recycled pid is never hit.
        if self.worker_pid != self.process.pid and self._reader.is_alive():
            with suppress(OSError):
                os.kill(self.worker_pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        with suppress(subprocess.TimeoutExpired, OSError):
            self.process.wait(timeout=_REAP_SECONDS)
        self._reader.join(timeout=_REAP_SECONDS)
        for pipe in (self.process.stdin, self.process.stdout):
            if pipe is not None:
                with suppress(OSError, ValueError):
                    pipe.close()


class ParseSession:
    """The symbols of an index's files, found in a child process under a deadline."""

    def __init__(self, limits: ParseLimits = PARSE_LIMITS) -> None:
        self._limits = limits
        self._lock = threading.Lock()
        self._child: _Child | None = None
        self._closed = False
        self._spent = 0.0
        self._start_failures = 0
        self.started = 0
        self.overruns = 0
        self.crashes = 0
        self.budget_skipped = 0
        self.syntax_errors = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def spent_seconds(self) -> float:
        return self._spent

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def start_failures(self) -> int:
        return self._start_failures

    def summary(self) -> ParseSummary:
        return ParseSummary(
            overruns=self.overruns,
            crashes=self.crashes,
            budget_skipped=self.budget_skipped,
            syntax_errors=self.syntax_errors,
        )

    @property
    def budget_spent(self) -> bool:
        return (
            self._spent >= self._limits.index_seconds - 1e-9
            or self._start_failures >= MAX_START_FAILURES
        )

    @property
    def child_pid(self) -> int | None:
        child = self._child
        return None if child is None else child.worker_pid

    @property
    def child_alive(self) -> bool:
        child = self._child
        return child is not None and child.alive

    def symbols(self, language: str, text: str) -> list[Symbol] | None:
        """The top-level definitions of `text`, or `None` when the file gets none: an unknown
        language, a syntax error, a deadline, a crash or a spent budget."""
        self._check_open()
        if language not in LANGUAGES:
            return None
        if self.budget_spent:
            self.budget_skipped += 1
            return None
        reply = self._exchange({"op": "parse", "language": language, "source": text})
        if reply is None:
            return None
        if "symbols" not in reply and reply.get("error") == "syntax":
            # The worker parsed it and the grammar found an error node: not a fault, but counted,
            # because a grammar that lags a language would send a whole repository here.
            self.syntax_errors += 1
            return None
        if reply.get("error") == "internal":
            # The worker raised on this file and its stderr is not read: this is the only trace.
            kind = reply.get("type")
            named = isinstance(kind, str) and len(kind) <= 64 and kind.isidentifier()
            log.warning(
                "parse worker raised",
                {"error": kind if isinstance(kind, str) and named else "unknown"},
            )
        symbols = _symbols_of(reply, text.count("\n") + 1)
        if symbols is None:
            # Not what was asked for (an error other than `syntax` included): whatever produced it
            # is not trusted again, so this is a crash for the file, and the child is replaced.
            self._fault("crash", "parse worker answered something unexpected")
        return symbols

    def inspect(self) -> InspectReport | None:
        """What the child reports of itself (`parse_worker._inspect`), for the isolation tests."""
        self._check_open()
        reply = self._exchange({"op": "inspect"}, counted=False)
        if reply is None:
            return None
        modules, environment = reply.get("modules"), reply.get("environment")
        if not isinstance(modules, list) or not isinstance(environment, dict):
            return None
        return InspectReport(
            modules=[m for m in modules if isinstance(m, str)],
            environment={k: v for k, v in environment.items() if isinstance(v, str)},
        )

    def close(self) -> None:
        """Ends the child. Callable twice, and from a thread other than the parsing one: a parse
        in progress then raises `ParseSessionClosed`."""
        with self._lock:
            self._closed = True
            child, self._child = self._child, None
        if child is not None:
            child.kill()

    def _check_open(self) -> None:
        if self._closed:
            raise ParseSessionClosed

    def _exchange(self, message: Json, *, counted: bool = True) -> Json | None:
        """One request. The index budget is charged the wall time of the whole exchange, a start
        or a restart included, so a worker that dies on every file cannot cost more than it."""
        began = time.monotonic()  # a real duration of a child process, not an expiry
        try:
            child = self._ensure_child()
        except _NotReady:
            self._start_failures += 1
            if counted:
                self._spent += time.monotonic() - began
            log.warning("parse worker did not start", {"failures": self._start_failures})
            return None
        startup = time.monotonic() - began
        allowed = self._limits.file_seconds
        if counted:
            allowed = min(allowed, self._limits.index_seconds - self._spent - startup)
            if allowed <= 0:  # the start used what was left
                self._spent += startup
                self.budget_skipped += 1
                return None
        reply = child.request(message, allowed)
        if counted:
            elapsed = time.monotonic() - began
            self._spent += max(elapsed, startup + allowed) if reply == "timeout" else elapsed
        self._check_open()
        if isinstance(reply, str):
            self._fault(
                reply,
                "parse worker overran its deadline"
                if reply == "timeout"
                else "parse worker crashed",
                child,
            )
            return None
        return reply

    def _fault(self, kind: Failure, message: str, child: _Child | None = None) -> None:
        """Counts an overrun or a crash, logs it (no path, no content) and ends the child."""
        if kind == "timeout":
            self.overruns += 1
        else:
            self.crashes += 1
        log.warning(message, {"overruns": self.overruns, "crashes": self.crashes})
        with self._lock:
            target = child or self._child
        if target is not None:
            self._discard(target)

    def _ensure_child(self) -> _Child:
        with self._lock:
            if self._closed:
                raise ParseSessionClosed
            if self._child is not None:
                return self._child
        child = _start_child()
        with self._lock:
            lost = self._closed
            if not lost:
                self._child = child
                self.started += 1
                self._start_failures = 0
        if lost:
            child.kill()
            raise ParseSessionClosed
        return child

    def _discard(self, child: _Child) -> None:
        with self._lock:
            if self._child is child:
                self._child = None
        child.kill()


def _start_child() -> _Child:
    try:
        child = _Child()
    except OSError:
        raise _NotReady from None
    try:
        child.wait_ready(STARTUP_SECONDS)
    except _NotReady:
        child.kill()
        raise
    return child


def _is_line(value: object, line_count: int) -> bool:
    """An integer (not a bool, not a float) within the document."""
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= line_count


def _symbols_of(reply: Json, line_count: int) -> list[Symbol] | None:
    """The symbols of a reply, or `None` unless every one is exactly `[name | null, start, end]`
    with integer lines, `start <= end`, inside the document's `line_count` lines, and a name that
    can be stored (no NUL, no lone surrogate). A name longer than `SYMBOL_NAME_MAX` is not a bad
    reply, since an honest worker can send one: the symbol keeps its lines and loses its name."""
    found = reply.get("symbols")
    if not isinstance(found, list):
        return None
    symbols: list[Symbol] = []
    for item in found:
        if not (isinstance(item, list) and len(item) == 3):
            return None
        name, start, end = item
        if not (
            (name is None or isinstance(name, str))
            and _is_line(start, line_count)
            and _is_line(end, line_count)
            and start <= end
        ):
            return None
        if name is not None:
            if not _is_storable(name):
                return None
            if len(name) > SYMBOL_NAME_MAX:
                name = None
        symbols.append(Symbol(name=name, start_line=start, end_line=end))
    return symbols


def _is_storable(name: str) -> bool:
    """Postgres text holds no NUL, and a lone surrogate cannot be encoded as UTF-8."""
    if "\x00" in name:
        return False
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True
