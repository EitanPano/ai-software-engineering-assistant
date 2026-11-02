import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from psycopg import errors, sql

from app.api.conversation.service import (
    find_owned_conversation,
    insert_conversation,
    with_transaction,
)
from app.infra import postgres as postgres_module
from app.infra.postgres import postgres
from app.infra.scripts import migrate as migrate_script
from app.infra.scripts.migrate import migrate
from app.models.conversation.interface import ConversationRecord
from app.services.db import Executor, fetch_all, fetch_one, get_db
from tests.store import reset_store, store_backed

pytestmark = store_backed


FAILING_STATEMENT = "select * from table_that_does_not_exist;"


@dataclass(frozen=True)
class Name:
    name: str


@dataclass(frozen=True)
class Found:
    found: str | None


@dataclass
class Probes:
    """What a test creates outside the truncated tables: they are removed after it, because a
    record in `schema_migration` survives `reset_store` and would make the next run skip its
    file."""

    tables: list[str]
    files: list[str]

    def table(self) -> str:
        name = f"probe_{uuid.uuid4().hex}"
        self.tables.append(name)
        return name

    def migration(self) -> str:
        name = f"9000-{uuid.uuid4()}.sql"
        self.files.append(name)
        return name


@pytest.fixture(autouse=True)
async def probes() -> AsyncIterator[Probes]:
    await reset_store()
    found = Probes(tables=[], files=[])
    yield found
    async with get_db() as connection:
        for table in found.tables:
            await connection.execute(
                sql.SQL("drop table if exists {} cascade").format(sql.Identifier(table))
            )
        if found.files:
            await connection.execute(
                "delete from schema_migration where name = any(%s)", (found.files,)
            )


def migration_directory(root: Path, files: dict[str, str]) -> Path:
    directory = root / f"migrations-{uuid.uuid4().hex}"
    directory.mkdir()
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    return directory


async def table_exists(name: str) -> bool:
    row = await fetch_one(Found, "select to_regclass(%s) as found", (name,))
    return row is not None and row.found is not None


async def recorded_migrations(names: list[str]) -> list[str]:
    rows = await fetch_all(Name, "select name from schema_migration where name = any(%s)", (names,))
    return sorted(row.name for row in rows)


def conversation_record(conversation_id: str, created_at: datetime) -> ConversationRecord:
    return ConversationRecord(
        id=conversation_id,
        user_id="owner",
        title=None,
        created_at=created_at,
        updated_at=created_at,
    )


async def index_names_starting_with(prefix: str) -> list[str]:
    rows = await fetch_all(
        Name,
        "select indexname as name from pg_indexes where schemaname = 'public' "
        "and indexname like %s",
        (f"{prefix}%",),
    )
    return sorted(row.name for row in rows)


class TestThePostgresResource:
    async def test_runs_against_the_test_database(self) -> None:
        row = await fetch_one(Name, "select current_database() as name")

        assert row is not None
        assert row.name.endswith("_test")

    async def test_connects_pings_closes_and_connects_again_with_a_new_pool(self) -> None:
        await postgres.connect()
        await postgres.ping()
        first = await postgres.get_pool()

        await postgres.close()
        await postgres.connect()
        await postgres.ping()

        assert await postgres.get_pool() is not first
        assert first.closed

    async def test_closes_twice_without_error_and_pings_on_a_pool_built_on_demand(self) -> None:
        await postgres.close()
        await postgres.close()

        await postgres.ping()

        assert await table_exists("session") is True

    async def test_a_failed_connect_closes_the_pool_it_built_and_the_next_use_builds_another(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await postgres.close()
        monkeypatch.setattr(postgres, "_url", "postgres://app:app@127.0.0.1:1/app")
        monkeypatch.setattr(postgres_module, "OPEN_TIMEOUT_SECONDS", 1.0)

        with pytest.raises(psycopg.OperationalError):
            await postgres.connect()

        monkeypatch.undo()
        await postgres.ping()

    async def test_refuses_a_pool_that_belongs_to_another_event_loop(self) -> None:
        pool = await postgres.get_pool()
        other_loop_result: list[BaseException] = []

        async def from_another_loop() -> None:
            try:
                await postgres.get_pool()
            except RuntimeError as error:
                other_loop_result.append(error)

        await asyncio.to_thread(asyncio.run, from_another_loop())

        assert len(other_loop_result) == 1
        assert "another event loop" in str(other_loop_result[0])
        assert await postgres.get_pool() is pool


class TestMigrate:
    async def test_applies_a_file_once_and_nothing_the_second_time(
        self, probes: Probes, tmp_path: Path
    ) -> None:
        table = probes.table()
        name = probes.migration()
        directory = migration_directory(tmp_path, {name: f"create table {table} (id text);"})

        first = await migrate(directory)
        second = await migrate(directory)

        assert first == [name]
        assert second == []
        assert await table_exists(table) is True
        assert await recorded_migrations([name]) == [name]

    async def test_rolls_a_broken_file_back_whole_and_records_nothing_for_it(
        self, probes: Probes, tmp_path: Path
    ) -> None:
        good, bad = probes.table(), probes.table()
        good_name, bad_name = probes.migration(), probes.migration().replace("9000", "9001")
        probes.files.append(bad_name)
        directory = migration_directory(
            tmp_path,
            {
                good_name: f"create table {good} (id text);",
                bad_name: f"create table {bad} (id text); " + FAILING_STATEMENT,
            },
        )

        with pytest.raises(errors.UndefinedTable, match="table_that_does_not_exist"):
            await migrate(directory)

        assert await table_exists(bad) is False
        assert await table_exists(good) is True
        assert await recorded_migrations([good_name, bad_name]) == [good_name]

    async def test_applies_a_file_once_when_two_runs_start_together(
        self, probes: Probes, tmp_path: Path
    ) -> None:
        table = probes.table()
        name = probes.migration()
        directory = migration_directory(tmp_path, {name: f"create table {table} (id text);"})

        runs = await asyncio.gather(migrate(directory), migrate(directory))

        assert [applied for run in runs for applied in run] == [name]

    async def test_applies_the_files_in_name_order_and_ignores_what_is_not_sql(
        self, probes: Probes, tmp_path: Path
    ) -> None:
        first, second = probes.table(), probes.table()
        late = probes.migration().replace("9000", "9002")
        early = probes.migration().replace("9000", "9001")
        directory = migration_directory(
            tmp_path,
            {
                late: f"create table {second} (id text references {first} (id));",
                early: f"create table {first} (id text primary key);",
                "9003-notes.txt": "not a migration",
            },
        )

        applied = await migrate(directory)

        assert applied == [early, late]

    async def test_has_dropped_the_module_table_from_the_shipped_migrations(self) -> None:
        assert await table_exists("module") is False
        assert await index_names_starting_with("module") == []
        assert await recorded_migrations(["0003-drop-module.sql"]) == ["0003-drop-module.sql"]
        assert await table_exists("schema_migration") is True

    async def test_reads_the_shipped_migrations_from_the_package(self) -> None:
        """The `.sql` files ship inside the `app` package, so the image needs no source tree."""
        assert await migrate() == []

    async def test_releases_the_lock_and_leaves_the_connection_as_the_pool_expects(
        self, probes: Probes, tmp_path: Path
    ) -> None:
        name = probes.migration()
        directory = migration_directory(
            tmp_path, {name: f"create table {probes.table()} (id text);"}
        )
        await migrate(directory)

        pool = await postgres.get_pool()
        async with pool.connection() as connection:
            assert connection.autocommit is False
            cursor = await connection.execute(
                "select count(*) from pg_locks where locktype = 'advisory' "
                "and objid = %s and granted",
                (migrate_script.LOCK_KEY,),
            )
            row = await cursor.fetchone()
        assert row == (0,)


@dataclass(frozen=True)
class Version:
    version: int


class TestTheEngine:
    """The `database` service is Postgres 18 with pgvector: the retrieval tasks build on both."""

    async def test_is_postgres_18_or_later(self) -> None:
        row = await fetch_one(
            Version, "select current_setting('server_version_num')::int as version"
        )

        assert row is not None
        assert row.version >= 180000

    async def test_has_the_vector_extension_enabled_by_a_shipped_migration(self) -> None:
        row = await fetch_one(
            Name, "select extname as name from pg_extension where extname = 'vector'"
        )

        assert row is not None
        assert row.name == "vector"
        assert await recorded_migrations(["0004-vector-extension.sql"]) == [
            "0004-vector-extension.sql"
        ]

    async def test_round_trips_a_halfvec_and_takes_an_hnsw_index(self) -> None:
        literal = "[" + ",".join("0.5" if i == 0 else "0" for i in range(1024)) + "]"
        async with get_db() as connection, connection.transaction():
            await connection.execute(
                "create temporary table probe_vector (id int primary key, embedding halfvec(1024)) "
                "on commit drop"
            )
            await connection.execute(
                "create index on probe_vector using hnsw (embedding halfvec_cosine_ops)"
            )
            await connection.execute(
                "insert into probe_vector values (1, %s::halfvec(1024))", (literal,)
            )
            cursor = await connection.execute(
                "select embedding::text as text from probe_vector where id = 1"
            )
            row = await cursor.fetchone()

        assert row is not None
        assert row[0].startswith("[0.5,0,")
        assert row[0].count(",") == 1023


class TestTheMigrateCommand:
    async def test_exits_zero_when_the_migrations_apply(self) -> None:
        assert await migrate_script.main() == 0

    async def test_exits_one_and_names_no_secret_when_a_migration_fails(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def failing(*_args: object, **_kwargs: object) -> list[str]:
            raise errors.UndefinedTable("relation does not exist")

        monkeypatch.setattr(migrate_script, "migrate", failing)

        assert await migrate_script.main() == 1
        assert "app:app@" not in caplog.text


class TestWithTransaction:
    async def test_rolls_back_every_write_when_the_work_throws(self) -> None:
        now = datetime.now(UTC)

        async def work(tx: Executor) -> None:
            await insert_conversation(conversation_record("rolled-back", now), db=tx)
            raise RuntimeError("stop")

        with pytest.raises(RuntimeError, match="stop"):
            await with_transaction(work)

        assert await find_owned_conversation("rolled-back", "owner") is None

    async def test_commits_the_writes_of_work_that_returns_and_returns_its_value(self) -> None:
        now = datetime.now(UTC)

        async def work(tx: Executor) -> ConversationRecord:
            await insert_conversation(conversation_record("one", now), db=tx)
            return await insert_conversation(conversation_record("two", now), db=tx)

        created = await with_transaction(work)

        assert created.id == "two"
        assert await find_owned_conversation("one", "owner") is not None

    async def test_a_query_inside_the_transaction_sees_its_own_uncommitted_write(self) -> None:
        now = datetime.now(UTC)

        async def work(tx: Executor) -> tuple[bool, bool]:
            await insert_conversation(conversation_record("inside", now), db=tx)
            return (
                await find_owned_conversation("inside", "owner", db=tx) is not None,
                await find_owned_conversation("inside", "owner") is not None,
            )

        assert await with_transaction(work) == (True, False)
