"""The text of the fixture repository's `src/limiter.py`: 503 lines of real-sized Python the search
tests index, so the chunks are the size of a real repository's and not the 128 characters of
the small fixture files.

What each part is for (the tests find them by the names below, never by a line number written here):

- `class WindowCounter` is a symbol over 4,000 characters and under the 6,000-character bound. It
  is the chunk the paraphrase query expects, and it shares no word with that query.
- `def sliding_window_remaining` is the exact identifier: full-text and trigram search find it.
- `def build_default_policy_table` is a symbol over the bound, so it is cut into windows that keep
  its name.
- `QUOKKA_SNAPSHOT` is one line over the bound, cut into pieces that share its line number.
- `limiter.defer_penalty(key)` in `admit_batch` is a dotted call past line 300: Postgres reads
  `limiter.defer_penalty` and `penalty` apart from `defer_penalty`, so only trigram search finds
  the identifier. No other part of the file holds the words `defer` or `penalty`.
- The paraphrase (`SEMANTIC_QUERY`) shares no word with the file at all; a test asserts it. The
  file stays at 50 chunks or fewer, so every chunk is a candidate of the semantic search and the
  one scripted to be last has a rank.
"""

from typing import Final

_HEAD: Final = '''"""Rate limiting for the edge: windows and token buckets, keyed by caller.

A limiter answers one question, whether a key may do one more thing now, and says when to ask
again if not. Nothing here sleeps or reads the clock on its own: the caller passes the time in
milliseconds, so every rule can be tested with a number.
"""

from __future__ import annotations

import hashlib
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Final

MILLIS: Final = 1000
MINUTE_MS: Final = 60 * MILLIS
HOUR_MS: Final = 60 * MINUTE_MS
MAX_KEYS: Final = 100_000
KEY_BYTES: Final = 16
DEFAULT_LIMIT: Final = 60
DEFAULT_BURST: Final = 10


@dataclass(frozen=True)
class Policy:
    """How often a key may act: `limit` times in each `window_ms`, with a short `burst`."""

    limit: int
    window_ms: int
    burst: int = DEFAULT_BURST

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("a policy allows at least one action")
        if self.window_ms < 1:
            raise ValueError("a window lasts at least one millisecond")
        if self.burst < 0:
            raise ValueError("a burst cannot be negative")


class RateLimitExceeded(Exception):
    """Raised by `require`: the key must wait `retry_after_ms` before it acts again."""

    def __init__(self, key: str, retry_after_ms: int) -> None:
        super().__init__("rate limit exceeded")
        self.key = key
        self.retry_after_ms = retry_after_ms


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    remaining: int
    retry_after_ms: int


def hash_key(key: str) -> str:
    """A caller is stored by the hash of its key, never in clear."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[: KEY_BYTES * 2]


class WindowCounter:
    """Counts the actions of every key in a trailing window.

    Each key keeps the timestamps of its recent actions in a queue, oldest first. An action is
    allowed while fewer than `limit` timestamps lie inside the window that ends now. Timestamps
    older than the window are dropped from the front before every decision, so the queue never
    holds more than `limit` entries, and a key that stops acting costs memory only until its last
    timestamp ages out.

    The counter does not lock: it is meant to be owned by one task, or wrapped by a caller that
    serialises access. It also does not know the time. Every method takes `now_ms`, and a clock
    that moves backwards is treated as a clock that stood still.
    """

    def __init__(self, policy: Policy, max_keys: int = MAX_KEYS) -> None:
        self.policy = policy
        self.max_keys = max_keys
        self._seen: dict[str, deque[int]] = {}
        self._latest = 0

    def _now(self, now_ms: int) -> int:
        """The time to use: never earlier than the latest time any caller passed."""
        self._latest = max(self._latest, now_ms)
        return self._latest

    def _queue(self, key: str, now_ms: int) -> deque[int]:
        """The key's queue with everything older than the window dropped from the front."""
        queue = self._seen.get(key)
        if queue is None:
            self._make_room()
            queue = deque()
            self._seen[key] = queue
        edge = now_ms - self.policy.window_ms
        while queue and queue[0] <= edge:
            queue.popleft()
        return queue

    def _make_room(self) -> None:
        """Forgets the keys whose queues are empty, then the oldest key, when the table is full."""
        if len(self._seen) < self.max_keys:
            return
        for key in [k for k, queue in self._seen.items() if not queue]:
            del self._seen[key]
        if len(self._seen) >= self.max_keys:
            oldest = next(iter(self._seen))
            del self._seen[oldest]

    def count(self, key: str, now_ms: int) -> int:
        """How many actions the key made inside the window that ends now."""
        return len(self._queue(key, self._now(now_ms)))

    def remaining(self, key: str, now_ms: int) -> int:
        """How many more actions the key may make before it is refused."""
        return max(0, self.policy.limit - self.count(key, now_ms))

    def check(self, key: str, now_ms: int) -> Verdict:
        """Records an action when it is allowed, and says how long to wait when it is not."""
        now = self._now(now_ms)
        queue = self._queue(key, now)
        if len(queue) >= self.policy.limit:
            wait = queue[0] + self.policy.window_ms - now
            return Verdict(allowed=False, remaining=0, retry_after_ms=max(1, wait))
        queue.append(now)
        return Verdict(allowed=True, remaining=self.policy.limit - len(queue), retry_after_ms=0)

    def require(self, key: str, now_ms: int) -> Verdict:
        """As `check`, but a refusal is an exception, for a caller that prefers to unwind."""
        verdict = self.check(key, now_ms)
        if not verdict.allowed:
            raise RateLimitExceeded(key, verdict.retry_after_ms)
        return verdict

    def reset(self, key: str) -> bool:
        """Forgets a key at once, for an operator who lifted a block. True when it was known."""
        return self._seen.pop(key, None) is not None

    def oldest(self, key: str, now_ms: int) -> int | None:
        """The time of the oldest action still inside the window, or None when there is none."""
        queue = self._queue(key, self._now(now_ms))
        return queue[0] if queue else None

    def reset_in(self, key: str, now_ms: int) -> int:
        """Milliseconds until the key has its whole allowance back."""
        queue = self._queue(key, self._now(now_ms))
        if not queue:
            return 0
        return max(0, queue[-1] + self.policy.window_ms - self._now(now_ms))

    def keys(self) -> int:
        """How many keys the counter currently remembers."""
        return len(self._seen)

    def snapshot(self) -> dict[str, list[int]]:
        """The queues as plain lists, for a test or a debugging endpoint."""
        return {key: list(queue) for key, queue in self._seen.items()}

    def restore(self, snapshot: dict[str, list[int]]) -> None:
        """Replaces the table with a snapshot taken earlier, newest timestamps last."""
        self._seen = {key: deque(stamps) for key, stamps in snapshot.items()}
        self._latest = max((s[-1] for s in snapshot.values() if s), default=0)

    def __len__(self) -> int:
        return len(self._seen)


def sliding_window_remaining(stamps: list[int], limit: int, window_ms: int, now_ms: int) -> int:
    """How many actions are left in a trailing window, from the timestamps alone.

    This is the rule `WindowCounter` applies, written as a pure function: the stamps at or before
    the edge of the window no longer count, and the answer is never negative. It exists so a
    reader can check the rule without a queue in the way.
    """
    edge = now_ms - window_ms
    inside = sum(1 for stamp in stamps if stamp > edge)
    return max(0, limit - inside)


@dataclass
class TokenBucket:
    """A bucket that holds up to `capacity` tokens and gains `rate` tokens each second.

    An action takes one token. The bucket is topped up lazily, from the time of its last use, so
    an idle bucket costs nothing. A bucket starts full, which lets a quiet key act in a burst.
    """

    capacity: float
    rate: float
    tokens: float = field(default=-1.0)
    stamp_ms: int = 0

    def __post_init__(self) -> None:
        if self.capacity <= 0 or self.rate <= 0:
            raise ValueError("capacity and rate must be positive")
        if self.tokens < 0:
            self.tokens = self.capacity

    def top_up(self, now_ms: int) -> None:
        elapsed = max(0, now_ms - self.stamp_ms)
        self.tokens = min(self.capacity, self.tokens + elapsed / MILLIS * self.rate)
        self.stamp_ms = max(self.stamp_ms, now_ms)

    def take(self, now_ms: int, cost: float = 1.0) -> bool:
        """True when the bucket had `cost` tokens, which it then spends."""
        self.top_up(now_ms)
        if self.tokens < cost:
            return False
        self.tokens -= cost
        return True

    def wait_ms(self, now_ms: int, cost: float = 1.0) -> int:
        """Milliseconds until `cost` tokens are there; 0 when they already are."""
        self.top_up(now_ms)
        missing = cost - self.tokens
        if missing <= 0:
            return 0
        return math.ceil(missing / self.rate * MILLIS)

    def level(self, now_ms: int) -> float:
        """The tokens in the bucket now, between 0 and the capacity."""
        self.top_up(now_ms)
        return self.tokens


def build_default_policy_table() -> dict[str, Policy]:
    """The policies a deployment starts with, one per tier, before its settings are applied.

    The table is long on purpose: every tier is spelled out so that a reader can see the numbers
    and a diff shows exactly which tier changed.
    """
    return {
'''

_TAIL_ONE: Final = """    }


"""

_AFTER_TABLE: Final = '''def describe_policy(policy: Policy) -> str:
    """A policy as a sentence for a log line or an error message."""
    seconds = policy.window_ms / MILLIS
    return f"{policy.limit} per {seconds:g}s with a burst of {policy.burst}"


def merge_policies(base: dict[str, Policy], extra: dict[str, Policy]) -> dict[str, Policy]:
    """The tiers of `base`, with each tier of `extra` replacing the one of the same name."""
    merged = dict(base)
    merged.update(extra)
    return merged


def tighten(policy: Policy, factor: float) -> Policy:
    """A policy that allows `factor` times as many actions, rounded down but never below one."""
    if factor <= 0:
        raise ValueError("the factor must be positive")
    return Policy(max(1, int(policy.limit * factor)), policy.window_ms, policy.burst)


'''

_SNAPSHOT_NAME: Final = "QUOKKA_SNAPSHOT"

_BETWEEN: Final = '''

class KeyedLimiter:
    """One counter per tier, and the tier a key belongs to.

    A key is assigned to a tier the first time it is seen; `assign` moves it to another tier.
    Every decision goes to the counter of the key's tier, so a tier's allowance is not shared with
    any other.
    """

    def __init__(self, table: dict[str, Policy], fallback: str = "tier_000") -> None:
        if fallback not in table:
            raise KeyError("the fallback tier must be in the table")
        self.fallback = fallback
        self._counters = {name: WindowCounter(policy) for name, policy in table.items()}
        self._tier_of: dict[str, str] = {}

    def tier(self, key: str) -> str:
        return self._tier_of.get(key, self.fallback)

    def assign(self, key: str, tier: str) -> None:
        if tier not in self._counters:
            raise KeyError("no such tier")
        self._tier_of[key] = tier

    def check(self, key: str, now_ms: int) -> Verdict:
        return self._counters[self.tier(key)].check(key, now_ms)

    def remaining(self, key: str, now_ms: int) -> int:
        return self._counters[self.tier(key)].remaining(key, now_ms)

    def reset(self, key: str) -> bool:
        return self._counters[self.tier(key)].reset(key)

    def tiers(self) -> list[str]:
        return sorted(self._counters)

    def load(self) -> dict[str, int]:
        """How many keys each tier currently remembers."""
        return {name: counter.keys() for name, counter in self._counters.items()}


def merge_verdicts(verdicts: list[Verdict]) -> Verdict:
    """One verdict for a group of actions: allowed only if all are, waiting for the longest."""
    if not verdicts:
        return Verdict(allowed=True, remaining=0, retry_after_ms=0)
    return Verdict(
        allowed=all(v.allowed for v in verdicts),
        remaining=min(v.remaining for v in verdicts),
        retry_after_ms=max(v.retry_after_ms for v in verdicts),
    )


def admit_batch(limiter: KeyedLimiter, keys: list[str], now_ms: int) -> Verdict:
    """Asks for every key in a batch and answers for the batch as a whole.

    A key that is refused is pushed back before the next batch is judged, so one noisy key does
    not keep every later batch waiting.
    """
    verdicts: list[Verdict] = []
    for key in keys:
        verdict = limiter.check(key, now_ms)
        if not verdict.allowed:
            limiter.defer_penalty(key)
        verdicts.append(verdict)
    return merge_verdicts(verdicts)


def summarise(limiter: KeyedLimiter) -> str:
    """A line for a status page: the busiest tier and how many keys it holds."""
    load = limiter.load()
    if not load:
        return "no tiers"
    busiest = max(load, key=lambda name: (load[name], name))
    return f"{busiest} holds {load[busiest]} keys of {sum(load.values())}"


def retry_after_header(verdict: Verdict) -> str:
    """The value of a Retry-After header: whole seconds, rounded up, never zero."""
    return str(max(1, math.ceil(verdict.retry_after_ms / MILLIS)))


def window_edges(now_ms: int, window_ms: int, count: int) -> list[int]:
    """The start of each of the last `count` windows, newest first, for a chart."""
    current = now_ms - now_ms % window_ms
    return [current - n * window_ms for n in range(count)]


def parse_duration(text: str) -> int:
    """Milliseconds from a short duration such as 250ms, 30s, 15m or 2h."""
    units = {"ms": 1, "s": MILLIS, "m": MINUTE_MS, "h": HOUR_MS}
    for suffix in ("ms", "s", "m", "h"):
        if text.endswith(suffix) and text[: -len(suffix)].isdigit():
            return int(text[: -len(suffix)]) * units[suffix]
    raise ValueError("not a duration")
'''


def _table_rows() -> str:
    """A tier a row, 150 rows: one symbol far over the chunk bound."""
    rows: list[str] = []
    for n in range(150):
        limit = 20 + (n * 7) % 180
        window = (1, 5, 10, 30, 60)[n % 5] * MILLIS_PER_SECOND
        rows.append(
            f'        "tier_{n:03d}": Policy(limit={limit}, window_ms={window}, burst={n % 12}),\n'
        )
    return "".join(rows)


MILLIS_PER_SECOND: Final = 1000


def _quokka_line() -> str:
    """One line of 6,400 characters with no space in it, so the browser has nothing to wrap at."""
    return f'{_SNAPSHOT_NAME} = "' + ("0123456789abcdef" * 400) + '"\n'


def limiter_source() -> str:
    return _HEAD + _table_rows() + _TAIL_ONE + _AFTER_TABLE + "\n" + _quokka_line() + _BETWEEN


LIMITER_SOURCE: Final = limiter_source()
