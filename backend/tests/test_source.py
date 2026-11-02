import asyncio
import threading
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta

import httpx
import pytest
from pydantic import ValidationError

from app.api.source import service
from app.api.source.controller import fail_lost_sources, index_source
from app.api.source.schema import ConnectSourceBody
from app.config.constants import CHUNK_BOUNDS, EMBEDDING, INDEX_CAPS, ParseLimits
from app.infra.pubsub import pubsub
from app.models.source.enums import SourceErrorCode, SourceStatus
from app.models.source.interface import DocumentRecord, SourceRecord
from app.services.db import fetch_all
from app.services.event import SOURCE_QUEUED, SourceQueued, drain, subscribe
from app.services.parse import ParseSession
from app.services.utils import clock
from tests import fake_github, fake_voyage
from tests.fixture_repository import (
    FIXTURE_COMMIT,
    FIXTURE_FILES,
    INDEXED_PATHS,
    build_tarball,
)
from tests.source_support import (
    HELLO_WORLD,
    admin_bearer,
    connect,
    member_bearer,
    repository_url,
    stored_chunks,
    stored_documents,
)
from tests.store import reset_store, store_backed
from tests.support import error_of, recording_logger

REPOSITORY = "https://github.com/octocat/Hello-World"


def rejected(body: Mapping[str, object], path: str) -> None:
    with pytest.raises(ValidationError) as failure:
        ConnectSourceBody.model_validate(body)

    assert failure.value.errors()[0]["loc"] == (path,)


class TestUrlShape:
    """The request rules of `POST /api/source`: the exact form of `body.url` (V02)."""

    def test_accepts_the_exact_form(self) -> None:
        assert ConnectSourceBody.model_validate({"url": REPOSITORY}).url == REPOSITORY

    def test_accepts_the_owner_and_repository_limits(self) -> None:
        owner = "a" * 39
        repo = "r" * 100
        assert ConnectSourceBody.model_validate({"url": f"https://github.com/{owner}/{repo}"})
        assert ConnectSourceBody.model_validate({"url": "https://github.com/a/a.b_c-d"})
        assert ConnectSourceBody.model_validate({"url": "https://github.com/a/...x"})

    @pytest.mark.parametrize(
        "url",
        [
            "http://github.com/octocat/Hello-World",
            "https://gitlab.com/octocat/Hello-World",
            "https://www.github.com/octocat/Hello-World",
            "https://github.com.evil.test/octocat/Hello-World",
            "https://user@github.com/octocat/Hello-World",
            "https://user:pw@github.com/octocat/Hello-World",
            "https://github.com:443/octocat/Hello-World",
            "https://github.com/octocat/Hello-World?x=1",
            "https://github.com/octocat/Hello-World#readme",
            "https://github.com/octocat/Hello-World/",
            "https://github.com/octocat/Hello-World\n",
            "https://github.com/octocat/Hello-World ",
            " https://github.com/octocat/Hello-World",
            "https://github.com/octocat/Hello-World.git",
            "https://github.com/octocat/..",
            "https://github.com/octocat/.",
            "https://github.com/../Hello-World",
            "https://github.com/octocat/Hello-World/tree/main",
            "https://github.com/octocat",
            "https://github.com//Hello-World",
            "https://github.com/octocat/",
            "https://github.com/oc_tocat/Hello-World",
            "https://github.com/octocat/Hello World",
            "https://github.com/octocat/Hello%2DWorld",
            f"https://github.com/{'a' * 40}/Hello-World",
            f"https://github.com/octocat/{'r' * 101}",
            "https://github.com/octocat/Hello-Worlд",
            "git@github.com:octocat/Hello-World",
            "github.com/octocat/Hello-World",
            "",
        ],
    )
    def test_rejects_every_url_outside_the_exact_form(self, url: str) -> None:
        rejected({"url": url}, "url")

    def test_rejects_a_missing_or_non_string_url(self) -> None:
        for body in ({}, {"url": 5}, {"url": None}):
            rejected(body, "url")


class TestRefShape:
    """The request rules of `body.ref` (V02)."""

    def test_is_optional(self) -> None:
        assert ConnectSourceBody.model_validate({"url": REPOSITORY}).model_fields_set == {"url"}

    @pytest.mark.parametrize(
        "ref",
        [
            "main",
            "v1.2.3",
            "feature/a-b_c",
            "release/2026.10",
            "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d",
            "." + "a",
            "a" * 255,
        ],
    )
    def test_accepts_a_branch_tag_or_commit(self, ref: str) -> None:
        body = ConnectSourceBody.model_validate({"url": REPOSITORY, "ref": ref})

        assert body.ref == ref

    @pytest.mark.parametrize(
        "ref",
        [
            "",
            "a" * 256,
            "/main",
            "-main",
            "a..b",
            "..",
            ".",
            "./a",
            "a/./b",
            "a/.",
            "a/../b",
            "a b",
            "a\n",
            "a?b",
            "a#b",
            "a%2Fb",
            "a\\b",
            "a:b",
            "a~1",
            "a^",
            "a*",
            "١٢",
        ],
    )
    def test_rejects_a_malformed_ref(self, ref: str) -> None:
        rejected({"url": REPOSITORY, "ref": ref}, "ref")

    def test_rejects_a_null_or_non_string_ref(self) -> None:
        for ref in (None, 5):
            rejected({"url": REPOSITORY, "ref": ref}, "ref")


BAD_URLS = [
    "http://github.com/octocat/Hello-World",
    "https://gitlab.com/octocat/Hello-World",
    "https://user:pw@github.com/octocat/Hello-World",
    "https://github.com:443/octocat/Hello-World",
    "https://github.com/octocat/Hello-World?x=1",
    "https://github.com/octocat/Hello-World#readme",
    "https://github.com/octocat/Hello-World/",
    "https://github.com/octocat/Hello-World\n",
    "https://github.com/octocat/Hello-World.git",
    "https://github.com/octocat/..",
    "https://github.com/octocat/Hello-World/tree/main",
]


def error_code(response: httpx.Response) -> str:
    assert response.json()["requestId"]
    return error_of(response).code


@pytest.mark.usefixtures("fakes")
class TestUrlShapeOverHttp:
    """V02: a URL outside the exact form, or a malformed ref, is a 400 and GitHub is not called."""

    @pytest.mark.parametrize("url", BAD_URLS)
    async def test_rejects_a_url_outside_the_form_without_calling_github(
        self, client: httpx.AsyncClient, url: str
    ) -> None:
        res = await connect(client, admin_bearer(), url)

        assert res.status_code == 400
        assert error_code(res) == "validation_failed"
        assert [detail.path for detail in error_of(res).details] == ["url"]
        assert fake_github.state.calls == []

    @pytest.mark.parametrize("ref", ["a..b", ".", "a/./b", "/x", "-x", "a b", "a\n", ""])
    async def test_rejects_a_malformed_ref_without_calling_github(
        self, client: httpx.AsyncClient, ref: str
    ) -> None:
        res = await connect(client, admin_bearer(), HELLO_WORLD, ref)

        assert res.status_code == 400
        assert [detail.path for detail in error_of(res).details] == ["ref"]
        assert fake_github.state.calls == []


@pytest.mark.usefixtures("fakes")
class TestAccess:
    """V03: every endpoint is admin-only."""

    CALLS = (
        ("POST", "/api/source", {"url": HELLO_WORLD}),
        ("GET", "/api/source", None),
        ("POST", "/api/source/some-id/indexing", None),
    )

    @pytest.mark.parametrize(("method", "path", "body"), CALLS)
    async def test_no_token_is_a_401(
        self, client: httpx.AsyncClient, method: str, path: str, body: dict[str, str] | None
    ) -> None:
        res = await client.request(method, path, json=body)

        assert res.status_code == 401
        assert error_code(res) == "unauthenticated"

    @pytest.mark.parametrize(("method", "path", "body"), CALLS)
    async def test_a_user_is_a_403(
        self, client: httpx.AsyncClient, method: str, path: str, body: dict[str, str] | None
    ) -> None:
        res = await client.request(method, path, json=body, headers=member_bearer())

        assert res.status_code == 403
        assert error_code(res) == "forbidden"
        assert fake_github.state.calls == []

    async def test_a_user_with_a_malformed_body_is_still_a_403(
        self, client: httpx.AsyncClient
    ) -> None:
        res = await connect(client, member_bearer(), "nonsense")

        assert res.status_code == 403


@pytest.fixture
async def empty_store() -> AsyncIterator[None]:
    await reset_store()
    yield
    await reset_store()


async def wire_of(client: httpx.AsyncClient, source_id: str) -> dict[str, object]:
    res = await client.get("/api/source?limit=100", headers=admin_bearer())
    assert res.status_code == 200, res.text
    found = [item for item in res.json()["items"] if item["id"] == source_id]
    assert len(found) == 1
    assert isinstance(found[0], dict)
    return found[0]


async def connected(client: httpx.AsyncClient, url: str = HELLO_WORLD) -> str:
    res = await connect(client, admin_bearer(), url)
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestConnect:
    async def test_connects_at_the_default_branch_in_githubs_spelling(
        self, client: httpx.AsyncClient
    ) -> None:
        res = await connect(client, admin_bearer(), "https://github.com/octocat/hello-world")

        assert res.status_code == 201
        body = res.json()
        assert body["url"] == HELLO_WORLD
        assert body["ref"] == "main"
        assert body["status"] == "queued"
        assert body["errorCode"] is None
        assert body["indexedCommit"] is None
        assert (body["documentCount"], body["chunkCount"]) == (0, 0)
        assert body["id"]
        assert body["createdAt"].endswith("Z") or "+00:00" in body["createdAt"]

    async def test_connects_at_a_given_ref(self, client: httpx.AsyncClient) -> None:
        res = await connect(client, admin_bearer(), HELLO_WORLD, "release/1.0")

        assert res.status_code == 201
        assert res.json()["ref"] == "release/1.0"

    async def test_asks_github_twice_and_sends_no_credentials(
        self, client: httpx.AsyncClient
    ) -> None:
        await connect(client, admin_bearer())

        assert len(fake_github.state.calls) == 2
        assert all("authorization" not in call.headers for call in fake_github.state.calls)

    async def test_an_unknown_repository_ref_or_an_empty_repository_is_a_404(
        self, client: httpx.AsyncClient
    ) -> None:
        for url, ref in (
            (repository_url("missing"), None),
            (HELLO_WORLD, "nope"),
            (repository_url("emptyrepo"), None),
        ):
            res = await connect(client, admin_bearer(), url, ref)

            assert res.status_code == 404, (url, ref)
            assert error_code(res) == "not_found"
        listing = await client.get("/api/source", headers=admin_bearer())
        assert listing.json()["items"] == []

    async def test_a_second_connect_of_the_same_url_and_ref_is_a_409(
        self, client: httpx.AsyncClient
    ) -> None:
        await connected(client)

        for url, ref in (
            (HELLO_WORLD, None),
            ("https://github.com/octocat/hello-world", None),
            (HELLO_WORLD, "main"),
        ):
            res = await connect(client, admin_bearer(), url, ref)

            assert res.status_code == 409, (url, ref)
            assert error_code(res) == "conflict"
        assert (await connect(client, admin_bearer(), HELLO_WORLD, "v2")).status_code == 201

    async def test_github_down_or_limiting_is_a_503(self, client: httpx.AsyncClient) -> None:
        for name in ("down", "limited"):
            res = await connect(client, admin_bearer(), repository_url(name))

            assert res.status_code == 503, name
            assert error_code(res) == "upstream_unavailable"

    async def test_logs_the_status_githubs_answer_carried(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.source.controller.log", logger)

        await connect(client, admin_bearer(), repository_url("limited"))

        line = next(line for line in sink.lines if "github unavailable" in line)
        assert "status=403" in line
        assert "error=GithubUnavailable" in line

    async def test_publishes_source_queued_for_the_new_source(
        self, client: httpx.AsyncClient
    ) -> None:
        seen: list[SourceQueued] = []
        unsubscribe = subscribe(SOURCE_QUEUED, seen.append)
        try:
            source_id = await connected(client)
            await drain()
        finally:
            unsubscribe()

        assert seen == [{"source_id": source_id}]


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestList:
    async def test_lists_newest_first_in_pages(self, client: httpx.AsyncClient) -> None:
        first = await connected(client, repository_url("one"))
        second = await connected(client, repository_url("two"))
        third = await connected(client, repository_url("three"))

        page = await client.get("/api/source?limit=2", headers=admin_bearer())
        rest = await client.get(
            f"/api/source?limit=2&cursor={page.json()['nextCursor']}", headers=admin_bearer()
        )

        assert [item["id"] for item in page.json()["items"]] == [third, second]
        assert page.json()["nextCursor"]
        assert [item["id"] for item in rest.json()["items"]] == [first]
        assert rest.json()["nextCursor"] is None

    async def test_an_empty_list_is_an_empty_page(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/source", headers=admin_bearer())

        assert res.json() == {"items": [], "nextCursor": None}

    async def test_a_bad_cursor_or_limit_is_a_400(self, client: httpx.AsyncClient) -> None:
        for query in ("cursor=not-a-cursor", "limit=0", "limit=101"):
            res = await client.get(f"/api/source?{query}", headers=admin_bearer())

            assert res.status_code == 400, query
            assert error_code(res) == "validation_failed"


@dataclass(frozen=True)
class _Tuples:
    relname: str
    tuples: float


def lines_of(path: str) -> list[str]:
    return FIXTURE_FILES[path].decode().split("\n")


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestIndex:
    async def test_the_fixture_repository_ends_ready_with_its_commit_and_counts(
        self, client: httpx.AsyncClient
    ) -> None:
        source_id = await connected(client)

        await index_source(source_id)

        wire = await wire_of(client, source_id)
        chunks = await stored_chunks(source_id)
        documents = await stored_documents(source_id)
        assert wire["status"] == "ready"
        assert wire["errorCode"] is None
        assert wire["indexedCommit"] == FIXTURE_COMMIT
        assert wire["documentCount"] == len(documents) == len(INDEXED_PATHS)
        assert wire["chunkCount"] == len(chunks) > 0
        assert {document.path for document in documents} == INDEXED_PATHS

    async def test_each_chunk_is_exactly_its_lines_and_every_non_blank_line_is_in_one(
        self, client: httpx.AsyncClient
    ) -> None:
        source_id = await connected(client)
        await index_source(source_id)

        chunks = await stored_chunks(source_id)

        for path in INDEXED_PATHS:
            lines = lines_of(path)
            mine = [chunk for chunk in chunks if chunk.path == path]
            covered: set[int] = set()
            pieces: dict[int, list[str]] = {}
            for chunk in mine:
                if chunk.start_line == chunk.end_line and (
                    len(lines[chunk.start_line - 1]) > CHUNK_BOUNDS.max_chars
                ):
                    # The documented exception: a line over the bound is cut into pieces that
                    # share its number, and together they are the line.
                    assert len(chunk.content) <= CHUNK_BOUNDS.max_chars
                    pieces.setdefault(chunk.start_line, []).append(chunk.content)
                else:
                    assert chunk.content == "\n".join(lines[chunk.start_line - 1 : chunk.end_line])
                covered.update(range(chunk.start_line, chunk.end_line + 1))
            assert pieces or path != "src/limiter.py"
            for number, found in pieces.items():
                # The rows come back in no order within a line number.
                line = lines[number - 1]
                cut = [
                    line[offset : offset + CHUNK_BOUNDS.max_chars]
                    for offset in range(0, len(line), CHUNK_BOUNDS.max_chars)
                ]
                assert sorted(found) == sorted(cut)
            assert [
                n for n, line in enumerate(lines, 1) if line.strip() and n not in covered
            ] == [], path

    async def test_every_embedding_has_1024_dimensions(self, client: httpx.AsyncClient) -> None:
        source_id = await connected(client)
        await index_source(source_id)

        assert {chunk.dimensions for chunk in await stored_chunks(source_id)} == {1024}

    async def test_splits_the_fixture_by_symbol(self, client: httpx.AsyncClient) -> None:
        source_id = await connected(client)
        await index_source(source_id)

        symbols = {
            (chunk.path, chunk.symbol)
            for chunk in await stored_chunks(source_id)
            if chunk.symbol is not None
        }
        assert {
            ("src/app.py", "Greeter"),
            ("src/app.py", "main"),
            ("src/util.js", "add"),
            ("src/types.ts", "norm"),
            ("src/widget.tsx", "Hello"),
        } <= symbols

    async def test_a_definition_past_line_256_is_split_by_symbol_and_no_file_fell_back(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The review's P0: the child died on any definition ending past line 256, every file
        quietly fell back to line windows, and the source still ended `ready`."""
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.source.controller.log", logger)
        source_id = await connected(client)

        await index_source(source_id)

        late = [chunk for chunk in await stored_chunks(source_id) if chunk.path == "src/late.py"]
        assert [(c.symbol, c.start_line, c.end_line) for c in late if c.symbol] == [
            ("last_one", 299, 300)
        ]
        assert not [line for line in sink.lines if "parse fell back" in line], sink.lines

    async def test_a_fault_in_the_worker_is_counted_and_logged_not_silent(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A worker that raised on a file answers `internal`; stderr is not read, so this is the
        only trace of it."""
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.source.controller.log", logger)
        monkeypatch.setattr("app.services.parse.log", logger)
        monkeypatch.setattr(
            "app.services.parse._Child.request",
            lambda self, message, seconds: {"error": "internal", "type": "ValueError"},
        )
        source_id = await connected(client)

        await index_source(source_id)

        assert (await wire_of(client, source_id))["status"] == "ready"
        lines = [line for line in sink.lines if "parse fell back" in line]
        assert len(lines) == 1, sink.lines
        assert "crashes=0" not in lines[0]
        assert any("parse worker raised" in e and "error=ValueError" in e for e in sink.lines)

    async def test_files_that_do_not_parse_are_counted_apart_from_faults(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.source.controller.log", logger)
        monkeypatch.setattr("app.services.parse.log", logger)
        monkeypatch.setattr(
            "app.services.parse._Child.request",
            lambda self, message, seconds: {"error": "syntax"},
        )
        source_id = await connected(client)

        await index_source(source_id)

        lines = [line for line in sink.lines if "parse fell back" in line]
        assert len(lines) == 1, sink.lines
        assert "syntaxErrors=" in lines[0]
        assert "crashes=0" in lines[0]

    async def test_logs_how_many_files_fell_back_and_nothing_that_names_one(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.source.controller.log", logger)
        monkeypatch.setattr(
            "app.api.source.controller.ParseSession",
            lambda: ParseSession(ParseLimits(file_seconds=0.6, index_seconds=30)),
        )
        source_id = await connected(client, repository_url("crafted"))

        await index_source(source_id)

        lines = [line for line in sink.lines if "parse fell back" in line]
        assert len(lines) == 1, sink.lines
        assert "overruns=1" in lines[0]
        assert "crashes" not in lines[0] or "crashes=0" in lines[0]
        assert "bad.ts" not in lines[0]
        assert source_id in lines[0]

    async def test_sends_voyage_only_what_it_stores(self, client: httpx.AsyncClient) -> None:
        source_id = await connected(client)
        await index_source(source_id)

        sent = [
            text
            for body in fake_voyage.state.requests
            for text in body["input"]  # type: ignore[attr-defined]
        ]
        stored = [chunk.content for chunk in await stored_chunks(source_id)]
        assert sorted(sent) == sorted(stored)
        assert not any("node_modules" in text or "caf" in text for text in sent)

    async def test_embeds_and_commits_in_batches(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.api.source.controller.EMBEDDING", replace(EMBEDDING, commit_chunks=3)
        )
        source_id = await connected(client)

        await index_source(source_id)

        chunks = await stored_chunks(source_id)
        assert len(fake_voyage.state.requests) >= len(chunks) // 3
        assert (await wire_of(client, source_id))["chunkCount"] == len(chunks)

    async def test_a_crafted_file_falls_back_to_line_windows_and_the_index_still_ends_ready(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """V05: the parse worker's deadline fires, and the server keeps answering meanwhile."""
        monkeypatch.setattr(
            "app.api.source.controller.ParseSession",
            lambda: ParseSession(ParseLimits(file_seconds=0.6, index_seconds=30)),
        )
        source_id = await connected(client, repository_url("crafted"))

        task = asyncio.create_task(index_source(source_id))
        statuses: list[int] = []
        while not task.done():
            statuses.append((await client.get("/api/health")).status_code)
            await asyncio.sleep(0.02)
        await task

        assert (await wire_of(client, source_id))["status"] == "ready"
        chunks = await stored_chunks(source_id)
        crafted = [chunk for chunk in chunks if chunk.path == "bad.ts"]
        assert crafted
        assert {chunk.symbol for chunk in crafted} == {None}
        assert {chunk.symbol for chunk in chunks if chunk.path == "ok.py"} >= {"Greeter", "main"}
        assert set(statuses) == {200}
        assert len(statuses) >= 5

    async def test_ending_a_source_that_is_already_finished_keeps_its_documents(
        self, client: httpx.AsyncClient
    ) -> None:
        """The review's P1: the delete ran before the guarded update and committed alone, so a
        `ready` source (the connection dropped after `finish_ready`, a cancel in that await)
        lost its documents and could not be retried."""
        source_id = await connected(client)
        await index_source(source_id)
        before = await stored_chunks(source_id)

        async def work(db: service.Tx) -> bool:
            return await service.finish_failed(
                source_id, SourceErrorCode.interrupted, clock.now(), db=db
            )

        ended = await service.with_transaction(work)

        assert ended is False
        assert await stored_chunks(source_id) == before
        assert len(await stored_documents(source_id)) == len(INDEXED_PATHS)
        wire = await wire_of(client, source_id)
        assert (wire["status"], wire["errorCode"]) == ("ready", None)
        assert wire["chunkCount"] == len(before)

    async def test_ending_an_active_source_removes_its_documents_with_the_update(
        self, client: httpx.AsyncClient
    ) -> None:
        source_id = await connected(client)
        assert await service.claim_source(source_id, clock.now()) is not None
        await service.insert_documents(
            [
                DocumentRecord(
                    id="d1",
                    source_id=source_id,
                    path="a.py",
                    language="python",
                    created_at=clock.now(),
                )
            ]
        )
        assert len(await stored_documents(source_id)) == 1

        async def work(db: service.Tx) -> bool:
            return await service.finish_failed(
                source_id, SourceErrorCode.internal, clock.now(), db=db
            )

        assert await service.with_transaction(work) is True
        assert await stored_documents(source_id) == []

    async def test_a_source_that_is_not_queued_is_left_alone(
        self, client: httpx.AsyncClient
    ) -> None:
        source_id = await connected(client)
        await index_source(source_id)
        before = len(fake_voyage.state.requests)

        await index_source(source_id)
        await index_source("no-such-source")

        assert len(fake_voyage.state.requests) == before
        assert (await wire_of(client, source_id))["status"] == "ready"

    async def test_an_archive_that_is_not_a_tarball_ends_failed_as_unavailable(
        self, client: httpx.AsyncClient
    ) -> None:
        source_id = await connected(client, repository_url("notar"))

        await index_source(source_id)

        wire = await wire_of(client, source_id)
        assert (wire["status"], wire["errorCode"]) == ("failed", "repository_unavailable")
        assert await stored_documents(source_id) == []

    async def test_the_failure_log_names_the_error_type_and_githubs_status(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.source.controller.log", logger)
        now = clock.now()
        await service.insert_source(
            SourceRecord(
                id="down-source",
                url=repository_url("down"),
                ref="main",
                status=SourceStatus.queued,
                error_code=None,
                indexed_commit=None,
                document_count=0,
                chunk_count=0,
                created_at=now,
                updated_at=now,
            )
        )

        await index_source("down-source")

        line = next(line for line in sink.lines if "index failed" in line)
        assert "error=GithubUnavailable" in line
        assert "status=502" in line
        assert "reason=repository_unavailable" in line

    async def test_a_ready_source_leaves_the_planner_statistics_of_its_tables(
        self, client: httpx.AsyncClient
    ) -> None:
        """A small table never reaches autovacuum's threshold, and the planner then reads every
        chunk through the document index (V06)."""
        source_id = await connected(client)
        await index_source(source_id)

        tuples = await fetch_all(
            _Tuples,
            "select relname, reltuples::float8 as tuples from pg_class "
            "where relname in ('source', 'document', 'chunk')",
        )
        assert {row.relname for row in tuples} == {"source", "document", "chunk"}
        assert all(row.tuples >= 0 for row in tuples), tuples

    async def test_a_failing_refresh_leaves_the_source_ready_and_logs_a_warning(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.source.controller.log", logger)

        async def refuse() -> None:
            raise RuntimeError("secret internal detail")

        monkeypatch.setattr("app.api.source.service.refresh_statistics", refuse)
        source_id = await connected(client)

        await index_source(source_id)

        assert (await wire_of(client, source_id))["status"] == "ready"
        (line,) = [line for line in sink.lines if "could not refresh statistics" in line]
        assert line.startswith("warning ")
        assert f"sourceId={source_id}" in line
        assert "secret internal detail" not in line
        assert not any("index failed" in line for line in sink.lines)

    async def test_no_refresh_runs_when_the_source_left_indexing_first(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int] = []

        async def spy() -> None:
            calls.append(1)

        async def not_indexing(*args: object) -> bool:
            return False

        monkeypatch.setattr("app.api.source.service.refresh_statistics", spy)
        monkeypatch.setattr("app.api.source.service.finish_ready", not_indexing)
        source_id = await connected(client)

        await index_source(source_id)

        assert calls == []

    async def test_an_unexpected_error_ends_failed_as_internal_and_hides_it(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def explode(texts: list[str]) -> list[list[float]]:
            raise RuntimeError("secret internal detail")

        monkeypatch.setattr("app.api.source.controller.embed_documents", explode)
        source_id = await connected(client)

        await index_source(source_id)

        wire = await wire_of(client, source_id)
        assert (wire["status"], wire["errorCode"]) == ("failed", "internal")
        assert "secret" not in str(wire)
        assert await stored_documents(source_id) == []

    async def test_a_cancel_while_the_archive_is_being_read_ends_the_source_and_the_child(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reading, release = threading.Event(), threading.Event()
        sessions: list[ParseSession] = []

        def hang(archive: object, caps: object) -> list[object]:
            reading.set()
            release.wait(30)
            return []

        def open_session() -> ParseSession:
            sessions.append(ParseSession())
            return sessions[-1]

        monkeypatch.setattr("app.api.source.controller.read_archive", hang)
        monkeypatch.setattr("app.api.source.controller.ParseSession", open_session)
        source_id = await connected(client)
        task = asyncio.create_task(index_source(source_id))
        await asyncio.wait_for(asyncio.to_thread(reading.wait, 30), 30)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()

        wire = await wire_of(client, source_id)
        assert (wire["status"], wire["errorCode"]) == ("failed", "interrupted")
        assert sessions[0].closed is True
        assert sessions[0].child_alive is False

    async def test_a_source_that_left_indexing_before_it_finished_is_logged_not_raised(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def refused(*args: object, **kwargs: object) -> bool:
            return False

        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.source.controller.log", logger)
        monkeypatch.setattr("app.api.source.service.finish_ready", refused)
        source_id = await connected(client)

        await index_source(source_id)

        assert any("source left indexing" in line for line in sink.lines), sink.lines

    async def test_a_write_that_cannot_end_a_source_is_logged_and_never_raised(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def broken(*args: object, **kwargs: object) -> bool:
            raise RuntimeError("the database went away")

        logger, sink = recording_logger()
        monkeypatch.setattr("app.api.source.controller.log", logger)
        monkeypatch.setattr("app.api.source.service.finish_failed", broken)
        source_id = await connected(client, repository_url("notar"))

        await index_source(source_id)  # fails to index, and fails to record it

        assert any("could not end a source" in line for line in sink.lines), sink.lines

    async def test_a_cancelled_index_ends_failed_as_interrupted(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        started = asyncio.Event()

        async def hang(texts: list[str]) -> list[list[float]]:
            started.set()
            await asyncio.Event().wait()
            return []

        monkeypatch.setattr("app.api.source.controller.embed_documents", hang)
        source_id = await connected(client)
        task = asyncio.create_task(index_source(source_id))
        await asyncio.wait_for(started.wait(), 30)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        wire = await wire_of(client, source_id)
        assert (wire["status"], wire["errorCode"]) == ("failed", "interrupted")
        assert await stored_documents(source_id) == []


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestHostileRepository:
    """V06: the archive is attacker-controlled."""

    async def test_links_devices_and_fifos_store_nothing(self, client: httpx.AsyncClient) -> None:
        source_id = await connected(client, repository_url("hostile-links"))

        await index_source(source_id)

        assert (await wire_of(client, source_id))["status"] == "ready"
        assert [d.path for d in await stored_documents(source_id)] == ["ok.txt"]

    async def test_traversal_members_store_nothing(self, client: httpx.AsyncClient) -> None:
        source_id = await connected(client, repository_url("hostile-traversal"))

        await index_source(source_id)

        assert (await wire_of(client, source_id))["status"] == "ready"
        assert [d.path for d in await stored_documents(source_id)] == ["ok.txt"]

    @pytest.mark.parametrize(
        ("name", "caps"),
        [
            ("bomb", replace(INDEX_CAPS, unpacked_bytes=1024 * 1024)),
            ("Hello-World", replace(INDEX_CAPS, documents=2)),
            ("Hello-World", replace(INDEX_CAPS, text_bytes=100)),
            ("Hello-World", replace(INDEX_CAPS, archive_bytes=500)),
            ("Hello-World", replace(INDEX_CAPS, members=3)),
            ("Hello-World", replace(INDEX_CAPS, chunks=3)),
            ("Hello-World", replace(INDEX_CAPS, embedded_chars=200)),
        ],
    )
    async def test_a_repository_over_a_cap_fails_whole_with_no_chunk_left(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, name: str, caps: object
    ) -> None:
        monkeypatch.setattr("app.api.source.controller.INDEX_CAPS", caps)
        source_id = await connected(client, repository_url(name))

        await index_source(source_id)

        wire = await wire_of(client, source_id)
        assert (wire["status"], wire["errorCode"]) == ("failed", "repository_too_large")
        assert await stored_documents(source_id) == []
        assert await stored_chunks(source_id) == []
        assert fake_voyage.state.requests == []

    async def test_a_redirect_to_another_host_fails_as_unavailable(
        self, client: httpx.AsyncClient
    ) -> None:
        source_id = await connected(client, repository_url("evil-redirect"))

        await index_source(source_id)

        wire = await wire_of(client, source_id)
        assert (wire["status"], wire["errorCode"]) == ("failed", "repository_unavailable")


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestRetry:
    async def test_a_voyage_failure_leaves_no_row_and_a_retry_ends_ready_without_duplicates(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Small commits: the earlier batches are stored before the failing one.
        monkeypatch.setattr(
            "app.api.source.controller.EMBEDDING", replace(EMBEDDING, commit_chunks=2)
        )
        source_id = await connected(client, repository_url("embedfail-down"))

        await index_source(source_id)

        wire = await wire_of(client, source_id)
        assert (wire["status"], wire["errorCode"]) == ("failed", "embedding_unavailable")
        assert (wire["documentCount"], wire["chunkCount"]) == (0, 0)
        assert await stored_documents(source_id) == []
        assert await stored_chunks(source_id) == []

        fake_voyage.state.released.add("down")
        retry = await client.post(f"/api/source/{source_id}/indexing", headers=admin_bearer())
        assert retry.status_code == 202
        assert retry.json()["status"] == "queued"
        assert retry.json()["errorCode"] is None
        await index_source(source_id)

        wire = await wire_of(client, source_id)
        documents = await stored_documents(source_id)
        assert wire["status"] == "ready"
        assert wire["documentCount"] == len(documents) == len(INDEXED_PATHS) + 1
        assert len({document.path for document in documents}) == len(documents)
        assert wire["chunkCount"] == len(await stored_chunks(source_id))

    async def test_a_retry_that_fails_again_stays_failed_with_no_rows(
        self, client: httpx.AsyncClient
    ) -> None:
        source_id = await connected(client, repository_url("embedfail-again"))
        await index_source(source_id)

        retry = await client.post(f"/api/source/{source_id}/indexing", headers=admin_bearer())
        await index_source(source_id)

        assert retry.status_code == 202
        wire = await wire_of(client, source_id)
        assert (wire["status"], wire["errorCode"]) == ("failed", "embedding_unavailable")
        assert await stored_chunks(source_id) == []

    async def test_a_source_that_is_not_failed_is_a_409(self, client: httpx.AsyncClient) -> None:
        queued = await connected(client, repository_url("one"))
        ready = await connected(client, repository_url("two"))
        await index_source(ready)

        for source_id in (queued, ready):
            res = await client.post(f"/api/source/{source_id}/indexing", headers=admin_bearer())

            assert res.status_code == 409, source_id
            assert error_code(res) == "conflict"

    async def test_an_unknown_source_is_a_404(self, client: httpx.AsyncClient) -> None:
        res = await client.post("/api/source/missing-id/indexing", headers=admin_bearer())

        assert res.status_code == 404
        assert error_code(res) == "not_found"

    async def test_a_retry_publishes_source_queued(self, client: httpx.AsyncClient) -> None:
        source_id = await connected(client, repository_url("embedfail-event"))
        await index_source(source_id)
        seen: list[SourceQueued] = []
        unsubscribe = subscribe(SOURCE_QUEUED, seen.append)
        try:
            await client.post(f"/api/source/{source_id}/indexing", headers=admin_bearer())
            await drain()
        finally:
            unsubscribe()

        assert seen == [{"source_id": source_id}]


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes")
class TestRacesAndEmptyRepositories:
    async def test_two_connects_at_once_make_one_source_and_one_409(
        self, client: httpx.AsyncClient
    ) -> None:
        results = await asyncio.gather(
            connect(client, admin_bearer()), connect(client, admin_bearer())
        )

        assert sorted(res.status_code for res in results) == [201, 409]
        listing = await client.get("/api/source", headers=admin_bearer())
        assert len(listing.json()["items"]) == 1

    async def test_two_indexers_for_one_queued_source_embed_it_once(
        self, client: httpx.AsyncClient
    ) -> None:
        source_id = await connected(client)

        await asyncio.gather(index_source(source_id), index_source(source_id))

        wire = await wire_of(client, source_id)
        documents = await stored_documents(source_id)
        assert wire["status"] == "ready"
        assert {document.path for document in documents} == INDEXED_PATHS
        assert len(documents) == len(INDEXED_PATHS)
        assert wire["chunkCount"] == len(await stored_chunks(source_id))
        sent = [text for body in fake_voyage.state.requests for text in body["input"]]  # type: ignore[attr-defined]
        assert len(sent) == wire["chunkCount"]

    async def test_two_retries_at_once_requeue_once(self, client: httpx.AsyncClient) -> None:
        source_id = await connected(client, repository_url("embedfail-race"))
        await index_source(source_id)
        seen: list[SourceQueued] = []
        unsubscribe = subscribe(SOURCE_QUEUED, seen.append)
        try:
            results = await asyncio.gather(
                *(
                    client.post(f"/api/source/{source_id}/indexing", headers=admin_bearer())
                    for _ in range(2)
                )
            )
            await drain()
        finally:
            unsubscribe()

        assert sorted(res.status_code for res in results) == [202, 409]
        assert seen == [{"source_id": source_id}]

    async def test_a_retry_while_the_index_is_running_is_a_409_and_changes_nothing(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        started, release = asyncio.Event(), asyncio.Event()

        async def hold(texts: list[str]) -> list[list[float]]:
            started.set()
            await release.wait()
            return [[1.0] + [0.0] * 1023 for _ in texts]

        monkeypatch.setattr("app.api.source.controller.embed_documents", hold)
        source_id = await connected(client)
        task = asyncio.create_task(index_source(source_id))
        await asyncio.wait_for(started.wait(), 30)

        retry = await client.post(f"/api/source/{source_id}/indexing", headers=admin_bearer())
        during = await wire_of(client, source_id)
        release.set()
        await task

        assert retry.status_code == 409
        assert during["status"] == "indexing"
        assert (await wire_of(client, source_id))["status"] == "ready"

    async def test_a_repository_with_nothing_to_index_ends_ready_with_zero_counts_and_no_embedding(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            fake_github,
            "fixture_tarball",
            lambda: build_tarball({"logo.png": b"\x89PNG\0", "blank.txt": b" \n", "a.dat": b"\0"}),
        )
        source_id = await connected(client)

        await index_source(source_id)

        wire = await wire_of(client, source_id)
        assert (wire["status"], wire["documentCount"], wire["chunkCount"]) == ("ready", 0, 0)
        assert wire["indexedCommit"] == FIXTURE_COMMIT
        assert fake_voyage.state.requests == []

    async def test_a_retry_clears_what_a_late_writer_stored_under_a_failed_source(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A sweep never runs beside a live indexer in one process, but if a source is failed under
        a running index, the rows it stores afterwards stay until a retry clears them."""
        started, release = asyncio.Event(), asyncio.Event()

        async def hold(texts: list[str]) -> list[list[float]]:
            started.set()
            await release.wait()
            return [[1.0] + [0.0] * 1023 for _ in texts]

        monkeypatch.setattr("app.api.source.controller.embed_documents", hold)
        source_id = await connected(client)
        task = asyncio.create_task(index_source(source_id))
        await asyncio.wait_for(started.wait(), 30)

        await fail_lost_sources(clock.now() + timedelta(seconds=5))
        release.set()
        await task

        wire = await wire_of(client, source_id)
        assert (wire["status"], wire["errorCode"]) == ("failed", "interrupted")
        assert (wire["documentCount"], wire["chunkCount"]) == (0, 0)
        # The rows the late writer stored stay under the failed source (a finding in qa.md); the
        # guarantee that holds is that the retry clears them and leaves no duplicate.
        fake_voyage.reset()
        retry = await client.post(f"/api/source/{source_id}/indexing", headers=admin_bearer())
        assert retry.status_code == 202
        monkeypatch.undo()
        await index_source(source_id)
        documents = await stored_documents(source_id)
        assert (await wire_of(client, source_id))["status"] == "ready"
        assert sorted(document.path for document in documents) == sorted(INDEXED_PATHS)


@pytest.fixture
async def bus() -> AsyncIterator[None]:
    await pubsub.connect()
    yield
    await pubsub.close()


@store_backed
@pytest.mark.usefixtures("empty_store", "fakes", "bus")
class TestTheBusIndexesAConnectedSource:
    async def test_connecting_a_source_indexes_it_beside_the_request(
        self, client: httpx.AsyncClient
    ) -> None:
        source_id = await connected(client)

        await drain()

        assert (await wire_of(client, source_id))["status"] == "ready"


@store_backed
@pytest.mark.usefixtures("empty_store")
class TestLostSources:
    async def test_ends_the_active_sources_a_lost_process_left_as_interrupted(self) -> None:
        old = clock.now() - timedelta(hours=1)
        for name, status in (
            ("a", SourceStatus.queued),
            ("b", SourceStatus.indexing),
            ("c", SourceStatus.ready),
            ("d", SourceStatus.failed),
        ):
            await service.insert_source(
                SourceRecord(
                    id=name,
                    url=repository_url(name),
                    ref="main",
                    status=status,
                    error_code=SourceErrorCode.internal if status is SourceStatus.failed else None,
                    indexed_commit=None,
                    document_count=0,
                    chunk_count=0,
                    created_at=old,
                    updated_at=old,
                )
            )

        failed = await fail_lost_sources(clock.now())

        assert failed == 2
        found = {
            record.id: record
            for record in (await service.list_sources(cursor=None, limit=10)).items
        }
        assert (found["a"].status, found["a"].error_code) == (
            SourceStatus.failed,
            SourceErrorCode.interrupted,
        )
        assert (found["b"].status, found["b"].error_code) == (
            SourceStatus.failed,
            SourceErrorCode.interrupted,
        )
        assert found["c"].status is SourceStatus.ready
        assert found["d"].error_code is SourceErrorCode.internal

    async def test_leaves_a_source_queued_after_the_boot_alone(self) -> None:
        now = clock.now()
        await service.insert_source(
            SourceRecord(
                id="fresh",
                url=repository_url("fresh"),
                ref="main",
                status=SourceStatus.queued,
                error_code=None,
                indexed_commit=None,
                document_count=0,
                chunk_count=0,
                created_at=now,
                updated_at=now,
            )
        )

        assert await fail_lost_sources(now - timedelta(seconds=5)) == 0
