"""github.py belongs: the GitHub client and the reader of its archives. It speaks to the public REST
API anonymously (60 requests an hour per server address): no `Authorization` header is ever sent,
because `.doc/conventions.md` keeps the GitHub token in its MCP server's container, and it follows
no redirect on its own. A connect spends two requests (the repository, the commit) and an index two
more (the archive's redirect, and the archive).

The archive (`GET /repos/{owner}/{repo}/tarball/{commit}`) is streamed to a spooled temporary file
under its byte cap and read as a stream, never extracted: nothing is written to a path the
repository names, so there is no path to traverse. It is hostile input all the same:

- the one redirect GitHub answers with is followed only to `codeload.github.com` or to the
  configured base URL's own host, once, and a second redirect is refused;
- every byte the archive decompresses to is counted as it is read, skipped members included
  (skipping one still decompresses it), and reading stops at the cap;
- only regular files are read; a link, a device or a fifo, and a name that is absolute, holds `..`
  or a backslash, stores nothing;
- a file that is too large, binary, not UTF-8 or blank is skipped, never decoded with an error.

The sources of `ref`, `owner` and `repo` are validated by the schema, and each is percent-encoded
as one path segment here. It does not belong: chunking, embedding or storage.
"""

import gzip
import re
import tarfile
import tempfile
import zlib
from dataclasses import dataclass
from typing import IO, Final, cast
from urllib.parse import quote, urljoin, urlsplit

import httpx2

from app.config.constants import (
    ARCHIVE_REDIRECT_HOST,
    INDEX_CAPS,
    SKIPPED_DIRECTORIES,
    SKIPPED_FILE_NAMES,
    SKIPPED_SUFFIXES,
    IndexCaps,
)
from app.config.env import env
from app.models.source.type import SourceFile

DEFAULT_BASE_URL: Final = "https://api.github.com"
API_VERSION: Final = "2022-11-28"
SHA_MEDIA_TYPE: Final = "application/vnd.github.sha"
_HEADERS: Final = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": API_VERSION,
    # GitHub refuses a request without one.
    "User-Agent": "ai-software-engineering-assistant",
}
_REDIRECTS: Final = frozenset({301, 302, 303, 307, 308})
_FULL_NAME: Final = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
_SHA: Final = re.compile(r"^[0-9a-f]{40}$")
# An archive stays in memory up to this size, then goes to a temporary file.
_SPOOL_BYTES: Final = 8 * 1024 * 1024
_MAX_PATH_CHARS: Final = 1024


class GithubError(Exception):
    """Base of what this module raises. It carries no message (nothing GitHub sent is repeated),
    only the HTTP status where there was one, so a log can tell a rate limit from a 5xx."""

    def __init__(self, status: int | None = None) -> None:
        super().__init__()
        self.status = status


class RepositoryNotFound(GithubError):  # noqa: N818  # named for what it says
    """No such public repository, ref or archive, or an empty repository."""


class GithubUnavailable(GithubError):  # noqa: N818
    """GitHub is unreachable, limiting this address, or answered something unexpected."""


class ArchiveRefused(GithubUnavailable):
    """The archive's redirect points somewhere it may not."""


class ArchiveInvalid(GithubError):  # noqa: N818
    """The archive is not a readable gzip tarball."""


class ArchiveTooLarge(GithubError):  # noqa: N818
    """Over an `IndexCaps` cap: the archive, its members, what it unpacks to, its documents, its
    text, or (counted by the controller) the chunks and embedded text chunking produces."""


@dataclass(frozen=True)
class Repository:
    url: str
    default_branch: str


_state: dict[str, httpx2.AsyncClient] = {}


def _client() -> httpx2.AsyncClient:
    client = _state.get("client")
    if client is None:
        client = httpx2.AsyncClient(
            base_url=env.github_base_url or DEFAULT_BASE_URL,
            follow_redirects=False,
            timeout=httpx2.Timeout(30.0, connect=10.0),
        )
        _state["client"] = client
    return client


def use_client(client: httpx2.AsyncClient | None) -> None:
    """Replaces the client (a test points it at the scripted fake); `None` forgets it."""
    if client is None:
        _state.pop("client", None)
    else:
        _state["client"] = client


def _segment(value: str) -> str:
    return quote(value, safe="")


async def _get(path: str, *, accept: str | None = None) -> httpx2.Response:
    headers = _HEADERS if accept is None else {**_HEADERS, "Accept": accept}
    try:
        return await _client().get(path, headers=headers)
    except httpx2.HTTPError as error:
        raise GithubUnavailable from error


def _json(response: httpx2.Response) -> dict[str, object]:
    try:
        body = response.json()
    except ValueError as error:
        raise GithubUnavailable from error
    if not isinstance(body, dict):
        raise GithubUnavailable(response.status_code)
    return body


def _require_ok(response: httpx2.Response, *, missing: frozenset[int] = frozenset()) -> None:
    status = response.status_code
    if status == 200:
        return
    # A redirect means the repository moved: it is not followed, so this name finds nothing.
    if status == 404 or status in _REDIRECTS or status in missing:
        raise RepositoryNotFound(status)
    # 403 and 429 are the rate limit, and a 5xx is GitHub's own trouble: both are retryable later.
    raise GithubUnavailable(status)


async def lookup_repository(owner: str, repo: str) -> Repository:
    """The repository in GitHub's own spelling, with its default branch."""
    response = await _get(f"/repos/{_segment(owner)}/{_segment(repo)}")
    _require_ok(response)
    body = _json(response)
    full_name, branch = body.get("full_name"), body.get("default_branch")
    if body.get("private") is True:
        raise RepositoryNotFound(response.status_code)
    if not (
        isinstance(full_name, str)
        and _FULL_NAME.fullmatch(full_name)
        and isinstance(branch, str)
        and branch
    ):
        raise GithubUnavailable(response.status_code)
    return Repository(url=f"https://github.com/{full_name}", default_branch=branch)


async def resolve_commit(owner: str, repo: str, ref: str) -> str:
    """The commit a branch, tag or commit names. A `ref` with a slash is one path segment.

    Asks for the sha alone (`application/vnd.github.sha`, GitHub's media type for it: the body is
    the 40 characters as plain text). The default answer is the whole commit, and its size is the
    repository author's choice, through the diff.
    """
    response = await _get(
        f"/repos/{_segment(owner)}/{_segment(repo)}/commits/{_segment(ref)}",
        accept=SHA_MEDIA_TYPE,
    )
    # 409 is an empty repository and 422 a ref that names nothing.
    _require_ok(response, missing=frozenset({409, 422}))
    sha = response.text.strip()
    if not _SHA.fullmatch(sha):
        raise GithubUnavailable(response.status_code)
    return sha


def _allowed_archive_origin(target: str) -> bool:
    parts = urlsplit(target)
    if parts.username is not None or parts.password is not None or parts.hostname is None:
        return False
    base = urlsplit(str(_client().base_url))
    if (parts.scheme, parts.netloc) == (base.scheme, base.netloc):
        return True
    return parts.scheme == "https" and parts.netloc == ARCHIVE_REDIRECT_HOST


async def download_archive(
    owner: str, repo: str, commit: str, *, max_bytes: int = INDEX_CAPS.archive_bytes
) -> tempfile.SpooledTemporaryFile[bytes]:
    """The commit's tarball, in a spooled file positioned at its start; the caller closes it.
    Follows exactly one redirect, and only to an allowed host."""
    client = _client()
    path = f"/repos/{_segment(owner)}/{_segment(repo)}/tarball/{_segment(commit)}"
    try:
        async with client.stream("GET", path, headers=_HEADERS) as first:
            if first.status_code not in _REDIRECTS:
                return await _spool(first, max_bytes)
            location = first.headers.get("location")
            if not location:
                raise GithubUnavailable(first.status_code)
            target = urljoin(str(first.url), location)
        if not _allowed_archive_origin(target):
            raise ArchiveRefused(first.status_code)
        async with client.stream("GET", target, headers=_HEADERS) as second:
            if second.status_code in _REDIRECTS:
                raise ArchiveRefused(second.status_code)
            return await _spool(second, max_bytes)
    except httpx2.HTTPError as error:
        raise GithubUnavailable from error


async def _spool(response: httpx2.Response, max_bytes: int) -> tempfile.SpooledTemporaryFile[bytes]:
    _require_ok(response)
    declared = response.headers.get("content-length", "")
    if declared.isascii() and declared.isdigit() and int(declared) > max_bytes:
        raise ArchiveTooLarge
    spool: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(  # noqa: SIM115
        max_size=_SPOOL_BYTES
    )
    try:
        total = 0
        # Raw: the bytes are a gzip stream whatever `Content-Encoding` says.
        async for chunk in response.aiter_raw():
            total += len(chunk)
            if total > max_bytes:
                raise ArchiveTooLarge
            spool.write(chunk)
        spool.seek(0)
    except BaseException:
        spool.close()
        raise
    return spool


class _CountedStream:
    """The decompressed bytes of an archive, counted as they are read. tarfile reads every member
    through here, skipped ones too, so a bomb is stopped at the cap, not after it."""

    def __init__(self, stream: gzip.GzipFile, limit: int) -> None:
        self._stream = stream
        self._limit = limit
        self._total = 0

    def read(self, size: int = -1) -> bytes:
        data = self._stream.read(size if size > 0 else 65536)
        self._total += len(data)
        if self._total > self._limit:
            raise ArchiveTooLarge
        return data


def _repository_path(name: str) -> str | None:
    """A member's path below the archive's root directory, or `None` when it must store nothing."""
    if name.startswith("/") or "\\" in name or "\x00" in name:
        return None
    parts = [part for part in name.split("/") if part not in {"", "."}]
    if ".." in parts or len(parts) < 2:
        return None
    path = "/".join(parts[1:])
    try:
        path.encode("utf-8")  # a name that is not valid UTF-8 cannot be stored
    except UnicodeEncodeError:
        return None
    return path if len(path) <= _MAX_PATH_CHARS else None


def _is_skipped(path: str) -> bool:
    *directories, name = path.split("/")
    return (
        any(d in SKIPPED_DIRECTORIES for d in directories)
        or name.lower() in SKIPPED_FILE_NAMES
        or path.lower().endswith(tuple(SKIPPED_SUFFIXES))
    )


def _text_of(data: bytes) -> str | None:
    """The text of a file, or `None` for a binary, bytes that are not UTF-8, or blank text."""
    if b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    return text if text.strip() else None


def read_archive(archive: IO[bytes], caps: IndexCaps = INDEX_CAPS) -> list[SourceFile]:
    """The text files of a gzip tarball, with the root directory stripped off their paths.

    Raises `ArchiveTooLarge` over a cap and `ArchiveInvalid` for anything that is not a readable
    tarball. A member that is not worth storing is skipped silently.
    """
    files: list[SourceFile] = []
    seen: set[str] = set()
    text_bytes = 0
    try:
        with gzip.GzipFile(fileobj=archive, mode="rb") as unpacked:
            counted = cast("IO[bytes]", _CountedStream(unpacked, caps.unpacked_bytes))
            # `stream=True`: otherwise tarfile keeps a `TarInfo` for every member it has read
            # (about 480 bytes each), and a tarball of empty members is a gigabyte of heap.
            with tarfile.open(  # type: ignore[call-overload]  # typeshed lacks `stream` (3.13+)
                fileobj=counted, mode="r|", stream=True
            ) as tar:
                members = 0
                for member in tar:
                    members += 1
                    if members > caps.members:
                        raise ArchiveTooLarge
                    path = _repository_path(member.name) if member.isreg() else None
                    if path is None or path in seen:
                        continue
                    if member.size > caps.file_bytes or _is_skipped(path):
                        continue
                    stream = tar.extractfile(member)
                    text = None if stream is None else _text_of(stream.read())
                    if text is None:
                        continue
                    seen.add(path)
                    text_bytes += len(text.encode("utf-8"))
                    if len(files) + 1 > caps.documents or text_bytes > caps.text_bytes:
                        raise ArchiveTooLarge
                    files.append(SourceFile(path=path, text=text))
    except (tarfile.TarError, OSError, EOFError, zlib.error) as error:
        raise ArchiveInvalid from error
    return files


__all__ = [
    "ArchiveInvalid",
    "ArchiveRefused",
    "ArchiveTooLarge",
    "GithubError",
    "GithubUnavailable",
    "Repository",
    "RepositoryNotFound",
    "download_archive",
    "lookup_repository",
    "read_archive",
    "resolve_commit",
    "use_client",
]
