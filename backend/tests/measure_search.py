"""FREE, and run by a person once: `uv run python -m tests.measure_search`. Not collected by pytest
and in no gate. It EMPTIES the test database (`app_test`) and refuses any other: it runs beside
neither `testDb` nor a `verify`.

It measures what the search design promises at the ceiling of `INDEX_CAPS`: 100,000 `ready` chunks
averaging about 670 characters with dense random vectors, in one source. An exact identifier, a
common word and a sentence are timed through the rule `search_knowledge_base` (twice each, the
second warm), then the same source is set `indexing` beside a small `ready` source, once with its
8 chunks far from the query and once nearest to it. It prints the inserts a second, each index's
size and every timing, and exits 1 when a search takes over a second or a result with fewer chunks
than the small source holds is not reported `incomplete`. The ready cases include an identifier
joined from the corpus's common words and a short word; the in-flight section ends with a one-word
search, which must end inside the statement limit (answered, or a 503 that is printed and allowed)
and fails only past 3.5 s.

After the bulk load it calls `service.refresh_statistics()`, the same function `_index` calls when a
source ends `ready`, so it measures what an index really leaves behind: without statistics the
planner reads every chunk through the document index (9 s for an identifier).

The vectors and words are generated inside Postgres (`setseed`, so a run repeats): nothing is
embedded and nothing leaves the machine.
"""

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from typing import Final

from tests.db.plugin import DEFAULT_TEST_URL, TEST_SUFFIX, database_name

CHUNKS: Final = 100_000
DOCUMENTS: Final = 5_000
BATCH: Final = 10_000
WORDS_PER_CHUNK: Final = 126
BUDGET_SECONDS: Final = 1.0
SMALL: Final = 8
IDENTIFIER: Final = "rare_identifier_zq"
COMMON_WORD: Final = "return"
# Joined from the corpus's most common words, so its trigrams are common too.
COMMON_IDENTIFIER: Final = "w1_w2_w3"
SHORT_WORD: Final = "re"
# The shortest word that runs a trigram search, taken from the corpus (`w12`).
THREE_LETTER_WORD: Final = "w12"
# The statement limit is 3 s; a search it cancels is answered within a little more.
STATEMENT_BUDGET_SECONDS: Final = 3.5
SENTENCE: Final = "w1 w2 w3 w4 w5 w6"

_INSERT_CHUNKS: Final = (
    "insert into chunk (id, document_id, symbol, start_line, end_line, content, embedding, "
    "created_at) select 'm' || g, 'doc' || (g %% %s::bigint), null, 1, 20, "
    "'return ' || (select string_agg('w' || (floor(random() * random() * 3000))::int, ' ') "
    "from generate_series(1::bigint, %s::bigint + (g * 0))) "
    "|| case when g %% 1000 = 0 then ' rare_identifier_zq' else '' end, "
    "(select array_agg((random() - 0.5)::real) from generate_series(1::bigint, 1024 + (g * 0)))"
    "::real[]::halfvec(1024), now() from generate_series(%s::bigint, %s::bigint) g"
)


@dataclass(frozen=True)
class _Size:
    name: str
    bytes: int


@dataclass(frozen=True)
class _Average:
    average: float


async def load() -> float:
    """Loads the big source; returns the inserts a second."""
    from app.api.source import service
    from app.models.source.enums import SourceStatus
    from app.models.source.interface import DocumentRecord, SourceRecord
    from app.services.db import execute
    from app.services.utils import clock

    now = clock.now()
    await service.insert_source(
        SourceRecord(
            id="big",
            url="https://github.com/octocat/big",
            ref="main",
            status=SourceStatus.ready,
            error_code=None,
            indexed_commit="0" * 40,
            document_count=DOCUMENTS,
            chunk_count=CHUNKS,
            created_at=now,
            updated_at=now,
        )
    )
    await service.insert_documents(
        [
            DocumentRecord(
                id=f"doc{n}", source_id="big", path=f"f{n}.py", language=None, created_at=now
            )
            for n in range(DOCUMENTS)
        ]
    )
    started = time.perf_counter()
    for batch, first in enumerate(range(1, CHUNKS + 1, BATCH)):

        async def work(db: service.Tx, batch: int = batch, first: int = first) -> None:
            await execute("select setseed(%s)", (0.01 * (batch + 1),), db=db)
            await execute(
                _INSERT_CHUNKS, (DOCUMENTS, WORDS_PER_CHUNK, first, first + BATCH - 1), db=db
            )

        await service.with_transaction(work)
        print(f"  inserted {first + BATCH - 1} chunks", flush=True)
    return CHUNKS / (time.perf_counter() - started)


async def report_sizes() -> None:
    from app.services.db import fetch_all, fetch_one

    average = await fetch_one(
        _Average,
        "select avg(length(content))::float8 as average from chunk where starts_with(id, 'm')",
    )
    print(f"average content length: {0 if average is None else average.average:.0f} characters")
    sizes = await fetch_all(
        _Size,
        "select relname as name, pg_relation_size(oid) as bytes from pg_class "
        "where relname in ('chunk', 'chunk_keyword_idx', 'chunk_content_trgm_idx', "
        "'chunk_embedding_idx') order by relname",
    )
    for size in sizes:
        print(f"  {size.name}: {size.bytes / 1024 / 1024:.0f} MiB")


@dataclass
class Verdict:
    failures: list[str]

    def check(
        self,
        label: str,
        seconds: float,
        hits: int,
        incomplete: bool,
        budget: float = BUDGET_SECONDS,
    ) -> None:
        print(f"  {label}: {seconds * 1000:.0f} ms, {hits} hits, incomplete={incomplete}")
        if seconds > budget:
            self.failures.append(f"{label} took {seconds:.2f} s")


async def timed(
    label: str,
    text: str,
    verdict: Verdict,
    expect: int | None = None,
    *,
    bounded_by_statement: bool = False,
) -> int:
    """Times the rule twice. A search `bounded_by_statement` may be answered with a 503 (the
    statement limit cancelled it): that is printed and allowed, and it fails only past
    `STATEMENT_BUDGET_SECONDS`. Every other search has the 1 s budget and no 503."""
    from psycopg.errors import QueryCanceled

    from app.api.search.controller import search_knowledge_base
    from app.services.utils.error import AppError

    hits = 0
    for run in ("cold", "warm"):
        started = time.perf_counter()
        try:
            outcome = await search_knowledge_base(text=text, limit=10)
        except (AppError, QueryCanceled) as error:
            # The rule raises the driver's error; the route's error handler makes it a 503.
            code = error.code if isinstance(error, AppError) else "statement timeout (503)"
            seconds = time.perf_counter() - started
            print(f"  {label} ({run}): {seconds * 1000:.0f} ms, answered 503 ({code})")
            if not bounded_by_statement:
                verdict.failures.append(f"{label} ({run}) was answered {code}")
            elif seconds > STATEMENT_BUDGET_SECONDS:
                verdict.failures.append(f"{label} ({run}) took {seconds:.2f} s to answer 503")
            continue
        seconds = time.perf_counter() - started
        hits = len(outcome.hits)
        verdict.check(
            f"{label} ({run})",
            seconds,
            hits,
            outcome.incomplete,
            budget=STATEMENT_BUDGET_SECONDS if bounded_by_statement else BUDGET_SECONDS,
        )
        if expect is not None and hits < expect and not outcome.incomplete:
            verdict.failures.append(f"{label} ({run}) returned {hits} of {expect}, not incomplete")
    return hits


async def main() -> int:
    import httpx2

    from app.api.source import service
    from app.infra.postgres import postgres
    from app.infra.scripts.migrate import migrate
    from app.models.source.enums import SourceStatus
    from app.services import voyage
    from app.services.db import execute
    from tests import fake_voyage
    from tests.store import reset_store

    fake = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=fake_voyage.app), base_url="http://fake-voyage"
    )
    voyage.use_client(fake)
    verdict = Verdict(failures=[])
    try:
        await migrate()
        await reset_store()
        print(f"loading {CHUNKS} chunks in {CHUNKS // BATCH} batches")
        rate = await load()
        print(f"inserts: {rate:.0f} chunks a second, indexes in place")
        # What an index leaves behind when it ends `ready` (`_index` calls the same function).
        started = time.perf_counter()
        await service.refresh_statistics()
        print(f"refresh_statistics: {(time.perf_counter() - started) * 1000:.0f} ms")
        await report_sizes()

        print("one ready source")
        await timed("identifier", IDENTIFIER, verdict)
        # A natural snake_case name is built from common trigrams, unlike the rare identifier.
        await timed("identifier of common words", COMMON_IDENTIFIER, verdict)
        await timed("common word", COMMON_WORD, verdict)
        await timed("short word", SHORT_WORD, verdict)
        await timed("three-letter word", THREE_LETTER_WORD, verdict)
        await timed("sentence", SENTENCE, verdict)

        print("the big source indexing, a small ready source beside it")
        await execute("update source set status = %s where id = 'big'", (SourceStatus.indexing,))
        far = "far from everything"
        await add_small_source("far", [fake_voyage.vector_of(f"small-{n}") for n in range(SMALL)])
        await timed("small source far from the query", far, verdict, SMALL)
        await execute("delete from source where id <> 'big'")
        near = "nearest the query"
        await add_small_source("near", [fake_voyage.vector_of(near)] * SMALL)
        await timed("small source nearest the query", near, verdict, SMALL)
        # One word, so a trigram search runs and tests every in-flight chunk before the filter to
        # `ready` sources: the statement limit must end it, answered or as a 503.
        await timed(
            "one common word, the big source indexing",
            COMMON_WORD,
            verdict,
            bounded_by_statement=True,
        )
    finally:
        voyage.use_client(None)
        await fake.aclose()
        await postgres.close()
    if verdict.failures:
        print("FAILED:")
        for failure in verdict.failures:
            print(f"  {failure}")
        return 1
    print("within budget")
    return 0


async def add_small_source(name: str, embeddings: list[list[float]]) -> None:
    """A `ready` source with one chunk per embedding."""
    from app.models.source.enums import SourceStatus
    from tests.test_search import Seed, add_source

    await add_source(
        SourceStatus.ready,
        name,
        [Seed(f"small {name} {n}", embedding) for n, embedding in enumerate(embeddings)],
    )


if __name__ == "__main__":
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_URL)
    if not database_name(url).endswith(TEST_SUFFIX):
        print(f"refusing {database_name(url)!r}: this script empties a database ending in _test")
        sys.exit(2)
    # Before the first import of the app: `config/env.py` reads the environment once.
    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = url
    from app.infra.loop import selector_loop_factory

    sys.exit(asyncio.run(main(), loop_factory=selector_loop_factory))
