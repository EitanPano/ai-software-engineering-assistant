"""The GitHub client and the archive reader, against the scripted fake (V06). The archive is
treated as hostile: a member that is not a plain file, or is named to escape, stores nothing."""

import gzip
import io
import tarfile
import tracemalloc
from collections.abc import AsyncIterator
from dataclasses import replace

import httpx2
import pytest

from app.config.constants import INDEX_CAPS, IndexCaps
from app.services import github
from app.services.github import (
    ArchiveInvalid,
    ArchiveRefused,
    ArchiveTooLarge,
    GithubUnavailable,
    RepositoryNotFound,
    download_archive,
    lookup_repository,
    read_archive,
    resolve_commit,
)
from tests import fake_github
from tests.fixture_repository import (
    FIXTURE_COMMIT,
    FIXTURE_FILES,
    FIXTURE_ROOT,
    INDEXED_PATHS,
    add_member,
    bomb_tarball,
    build_tarball,
    empty_members_tarball,
    fixture_tarball,
    links_tarball,
    many_tarball,
    traversal_tarball,
)

MIB = 1024 * 1024


@pytest.fixture
async def fake() -> AsyncIterator[None]:
    fake_github.reset()
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=fake_github.app), base_url="http://fake-github"
    )
    github.use_client(client)
    try:
        yield
    finally:
        github.use_client(None)
        await client.aclose()


def paths_of(data: bytes, caps: IndexCaps = INDEX_CAPS) -> set[str]:
    return {file.path for file in read_archive(io.BytesIO(data), caps)}


@pytest.mark.usefixtures("fake")
class TestLookups:
    async def test_names_the_repository_in_githubs_spelling(self) -> None:
        repository = await lookup_repository("octocat", "hello-world")

        assert repository.url == "https://github.com/octocat/Hello-World"
        assert repository.default_branch == "main"

    async def test_sends_no_credentials(self) -> None:
        await lookup_repository("octocat", "Hello-World")
        await resolve_commit("octocat", "Hello-World", "main")

        assert len(fake_github.state.calls) == 2
        for call in fake_github.state.calls:
            assert "authorization" not in call.headers
            assert "cookie" not in call.headers
            assert call.headers["user-agent"]
        assert fake_github.state.calls[0].headers["accept"] == "application/vnd.github+json"

    async def test_asks_for_the_sha_alone_not_the_commit_the_author_controls(self) -> None:
        """A full commit carries the diff, whose size the repository's author chooses."""
        await resolve_commit("octocat", "Hello-World", "main")

        assert fake_github.state.calls[-1].headers["accept"] == "application/vnd.github.sha"

    async def test_a_sha_answer_that_is_not_a_sha_is_unavailable(self) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, text="<html>not a sha</html>")

        client = httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler), base_url="http://fake-github"
        )
        github.use_client(client)

        with pytest.raises(GithubUnavailable):
            await resolve_commit("octocat", "Hello-World", "main")
        await client.aclose()

    async def test_the_error_names_the_status_githubs_answer_carried(self) -> None:
        with pytest.raises(GithubUnavailable) as raised:
            await lookup_repository("octocat", "down")

        assert raised.value.status == 502

    async def test_a_missing_repository_is_not_found(self) -> None:
        with pytest.raises(RepositoryNotFound):
            await lookup_repository("octocat", "missing")

    async def test_a_rate_limit_is_unavailable_not_missing(self) -> None:
        with pytest.raises(GithubUnavailable):
            await lookup_repository("octocat", "limited")

    async def test_a_server_error_is_unavailable(self) -> None:
        with pytest.raises(GithubUnavailable):
            await lookup_repository("octocat", "down")

    async def test_resolves_a_ref_to_its_commit(self) -> None:
        assert await resolve_commit("octocat", "Hello-World", "main") == FIXTURE_COMMIT

    async def test_sends_a_ref_with_a_slash_as_one_path_segment(self) -> None:
        await resolve_commit("octocat", "Hello-World", "feature/a-b")

        assert fake_github.state.calls[-1].raw_path.endswith("/commits/feature%2Fa-b")

    async def test_an_unknown_ref_and_an_empty_repository_are_not_found(self) -> None:
        with pytest.raises(RepositoryNotFound):
            await resolve_commit("octocat", "Hello-World", "nope")
        with pytest.raises(RepositoryNotFound):
            await resolve_commit("octocat", "emptyrepo", "main")

    async def test_a_transport_failure_is_unavailable(self) -> None:
        def refuse(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("no route", request=request)

        client = httpx2.AsyncClient(
            transport=httpx2.MockTransport(refuse), base_url="http://fake-github"
        )
        github.use_client(client)

        with pytest.raises(GithubUnavailable):
            await lookup_repository("octocat", "Hello-World")
        await client.aclose()

    async def test_a_redirect_on_a_lookup_is_not_followed(self) -> None:
        def moved(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(301, headers={"location": "http://fake-github/elsewhere"})

        client = httpx2.AsyncClient(
            transport=httpx2.MockTransport(moved), base_url="http://fake-github"
        )
        github.use_client(client)

        with pytest.raises(RepositoryNotFound):
            await lookup_repository("octocat", "Hello-World")
        await client.aclose()


@pytest.mark.usefixtures("fake")
class TestDownload:
    async def test_follows_the_one_redirect_and_returns_the_archive(self) -> None:
        archive = await download_archive("octocat", "Hello-World", FIXTURE_COMMIT)
        try:
            files = read_archive(archive)
        finally:
            archive.close()

        assert {file.path for file in files} == INDEXED_PATHS
        assert [call.raw_path.split("/")[1] for call in fake_github.state.calls] == [
            "repos",
            "codeload",
        ]
        assert all("authorization" not in call.headers for call in fake_github.state.calls)

    async def test_refuses_a_redirect_to_another_host(self) -> None:
        with pytest.raises(ArchiveRefused):
            await download_archive("octocat", "evil-redirect", FIXTURE_COMMIT)

        assert len(fake_github.state.calls) == 1

    async def test_refuses_a_second_redirect(self) -> None:
        with pytest.raises(ArchiveRefused):
            await download_archive("octocat", "double-redirect", FIXTURE_COMMIT)

        assert len(fake_github.state.calls) == 2

    async def test_refuses_an_archive_larger_than_its_cap_by_its_declared_size(self) -> None:
        with pytest.raises(ArchiveTooLarge):
            await download_archive("octocat", "Hello-World", FIXTURE_COMMIT, max_bytes=500)

    async def test_refuses_an_archive_larger_than_its_cap_by_the_bytes_it_sends(self) -> None:
        async def stream() -> AsyncIterator[bytes]:
            for _ in range(100):
                yield b"x" * 1000

        def handler(request: httpx2.Request) -> httpx2.Response:
            if "/tarball/" in request.url.path:
                return httpx2.Response(302, headers={"location": "http://fake-github/codeload/x"})
            return httpx2.Response(200, content=stream())

        client = httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler), base_url="http://fake-github"
        )
        github.use_client(client)

        with pytest.raises(ArchiveTooLarge):
            await download_archive("octocat", "Hello-World", FIXTURE_COMMIT, max_bytes=5000)
        await client.aclose()

    async def test_only_the_configured_base_and_codeload_may_serve_the_archive(self) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                302, headers={"location": "https://codeload.github.com/o/r/legacy.tar.gz/abc"}
            )

        client = httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler), base_url="http://fake-github"
        )
        github.use_client(client)

        # codeload is allowed, so the second request is made; it redirects again and is refused.
        with pytest.raises(ArchiveRefused):
            await download_archive("octocat", "Hello-World", FIXTURE_COMMIT)
        await client.aclose()

    async def test_a_missing_archive_is_not_found_and_an_error_is_unavailable(self) -> None:
        def gone(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(404)

        def broken(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(500)

        client = httpx2.AsyncClient(transport=httpx2.MockTransport(gone), base_url="http://fake")
        github.use_client(client)
        with pytest.raises(RepositoryNotFound):
            await download_archive("octocat", "Hello-World", FIXTURE_COMMIT)
        await client.aclose()

        client = httpx2.AsyncClient(transport=httpx2.MockTransport(broken), base_url="http://fake")
        github.use_client(client)
        with pytest.raises(GithubUnavailable):
            await download_archive("octocat", "Hello-World", FIXTURE_COMMIT)
        await client.aclose()


class TestReadArchive:
    def test_stores_the_text_files_with_the_root_directory_stripped(self) -> None:
        files = read_archive(io.BytesIO(fixture_tarball()))

        by_path = {file.path: file.text for file in files}
        assert set(by_path) == INDEXED_PATHS
        assert by_path["src/app.py"] == FIXTURE_FILES["src/app.py"].decode()

    def test_skips_directories_suffixes_binaries_bad_bytes_and_oversized_files(self) -> None:
        paths = paths_of(fixture_tarball())

        assert not paths & {
            "node_modules/dep/index.js",
            "assets/logo.png",
            "data/blob.dat",
            "data/latin1.txt",
            "data/big.txt",
        }

    def test_bytes_that_are_not_utf8_do_not_raise(self) -> None:
        data = build_tarball(
            {"ok.txt": b"fine\n", "bad.txt": b"\xff\xfe\xfa", "worse.txt": b"\xc3("}
        )

        assert paths_of(data) == {"ok.txt"}

    def test_skips_a_file_with_only_whitespace(self) -> None:
        assert paths_of(build_tarball({"ok.txt": b"x\n", "blank.txt": b" \n\t\n"})) == {"ok.txt"}

    def test_stores_nothing_for_links_devices_and_fifos(self) -> None:
        assert paths_of(links_tarball()) == {"ok.txt"}

    def test_stores_nothing_for_a_member_named_to_escape_the_root(self) -> None:
        assert paths_of(traversal_tarball()) == {"ok.txt"}

    def test_skips_a_path_that_cannot_be_stored(self) -> None:
        def extra(tar: tarfile.TarFile) -> None:
            add_member(tar, "root/bad\udcff.txt", data=b"x\n")

        assert paths_of(build_tarball({"ok.txt": b"x\n"}, extra=extra, root="root")) == {"ok.txt"}

    def test_the_first_of_two_members_with_one_path_wins(self) -> None:
        def extra(tar: tarfile.TarFile) -> None:
            add_member(tar, "octocat-Hello-World-7fd1a60/ok.txt", data=b"second\n")

        files = read_archive(io.BytesIO(build_tarball({"ok.txt": b"first\n"}, extra=extra)))

        assert [(f.path, f.text) for f in files] == [("ok.txt", "first\n")]

    def test_a_file_over_the_cap_is_skipped_not_fatal(self) -> None:
        caps = replace(INDEX_CAPS, file_bytes=10)

        assert paths_of(build_tarball({"small.txt": b"tiny\n", "large.txt": b"x" * 11}), caps) == {
            "small.txt"
        }

    def test_counts_the_bytes_of_a_skipped_member_against_the_unpacked_cap(self) -> None:
        caps = replace(INDEX_CAPS, unpacked_bytes=MIB)

        with pytest.raises(ArchiveTooLarge):
            read_archive(io.BytesIO(bomb_tarball(3 * MIB)), caps)

    def test_an_archive_within_the_unpacked_cap_is_read(self) -> None:
        caps = replace(INDEX_CAPS, unpacked_bytes=8 * MIB)

        assert paths_of(bomb_tarball(3 * MIB), caps) == {"ok.txt"}

    def test_too_many_documents_is_too_large(self) -> None:
        caps = replace(INDEX_CAPS, documents=5)

        with pytest.raises(ArchiveTooLarge):
            read_archive(io.BytesIO(many_tarball(6)), caps)
        assert len(read_archive(io.BytesIO(many_tarball(5)), caps)) == 5

    def test_skips_generated_lockfiles_by_name(self) -> None:
        data = build_tarball(
            {
                "package-lock.json": b"{}\n",
                "web/pnpm-lock.yaml": b"lockfileVersion: 9\n",
                "npm-shrinkwrap.json": b"{}\n",
                "package.json": b"{}\n",
            }
        )

        assert paths_of(data) == {"package.json"}

    def test_too_many_members_is_too_large_counted_across_every_member(self) -> None:
        caps = replace(INDEX_CAPS, members=1000)

        # The root directory is a member too: 999 files make 1000.
        assert read_archive(io.BytesIO(empty_members_tarball(999)), caps) == []
        with pytest.raises(ArchiveTooLarge):
            read_archive(io.BytesIO(empty_members_tarball(1000)), caps)

    def test_a_many_member_archive_does_not_accumulate_in_memory(self) -> None:
        """The review's P1: stream mode kept a `TarInfo` for every member (about 480 bytes each),
        so a few MiB of empty members held a GiB of heap in the process that serves chat."""
        data = empty_members_tarball(60_000)
        caps = replace(INDEX_CAPS, members=200_000)

        tracemalloc.start()
        try:
            assert read_archive(io.BytesIO(data), caps) == []
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert peak < 8 * MIB, peak

    def test_a_member_can_still_be_read_after_the_members_before_it_were_dropped(self) -> None:
        data = build_tarball({f"f{n}.txt": f"file {n}\n".encode() for n in range(500)})

        files = read_archive(io.BytesIO(data))

        assert [f.text for f in files][-1] == "file 499\n"
        assert len(files) == 500

    def test_too_much_text_is_too_large(self) -> None:
        caps = replace(INDEX_CAPS, text_bytes=250)

        with pytest.raises(ArchiveTooLarge):
            read_archive(io.BytesIO(many_tarball(3, 100)), caps)

    def test_something_that_is_not_a_tarball_is_invalid(self) -> None:
        with pytest.raises(ArchiveInvalid):
            read_archive(io.BytesIO(b"this is not a tarball"))

    def test_a_truncated_archive_is_invalid(self) -> None:
        data = fixture_tarball()

        with pytest.raises(ArchiveInvalid):
            read_archive(io.BytesIO(data[: len(data) // 2]))

    @pytest.mark.parametrize("declared", [10**6, 10**12])
    def test_a_member_whose_declared_size_lies_never_hangs_or_stores_it(
        self, declared: int
    ) -> None:
        """A header that claims more bytes than the stream holds: refused whole, either as too
        large (the claim is skipped through the counter) or invalid (the stream ends)."""
        info = tarfile.TarInfo(f"{FIXTURE_ROOT}/liar.txt")
        info.size = declared
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
            directory = tarfile.TarInfo(FIXTURE_ROOT)
            directory.type = tarfile.DIRTYPE
            tar.addfile(directory)
            tar.fileobj.write(info.tobuf(tarfile.PAX_FORMAT) + b"only ten b")

        with pytest.raises((ArchiveInvalid, ArchiveTooLarge)):
            read_archive(io.BytesIO(raw.getvalue()))

    def test_a_member_that_claims_less_than_it_holds_stores_what_it_claims(self) -> None:
        """The header size is the member's size; trailing bytes are not a second file."""
        data = build_tarball({"short.txt": b"0123456789\n"})

        files = read_archive(io.BytesIO(data), replace(INDEX_CAPS, file_bytes=5))

        assert files == []

    def test_an_empty_gzip_and_a_gzip_of_nothing_are_invalid_or_empty_never_raw_errors(
        self,
    ) -> None:
        for data in (b"", gzip.compress(b""), gzip.compress(b"\0" * 1024)):
            try:
                result = read_archive(io.BytesIO(data))
            except ArchiveInvalid:
                continue
            assert result == []

    def test_a_member_with_an_enormous_name_stores_nothing(self) -> None:
        def extra(tar: tarfile.TarFile) -> None:
            add_member(tar, f"{FIXTURE_ROOT}/{'a' * 5000}.txt", data=b"x\n")

        assert paths_of(build_tarball({"ok.txt": b"x\n"}, extra=extra)) == {"ok.txt"}
