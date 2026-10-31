"""Helpers for the source suites: the fake GitHub and the fake Voyage reached in process, an admin
for the gates, and readers for the stored documents and chunks."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import httpx2
import pytest

from app.api.user import controller as user
from app.models.user.enums import UserRole
from app.models.user.type import CreateUserInput
from app.services import github, voyage
from app.services.db import fetch_all
from app.services.security.jwt import AccessClaims, sign_access
from tests import fake_github, fake_voyage
from tests.auth_support import PASSWORD, bearer_of, mint_token

HELLO_WORLD = "https://github.com/octocat/Hello-World"


def repository_url(name: str) -> str:
    return f"https://github.com/octocat/{name}"


@pytest.fixture
async def fakes(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """The app's GitHub and Voyage clients pointed at the scripted fakes, with no pause between
    Voyage's retries."""
    fake_github.reset()
    fake_voyage.reset()
    git = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=fake_github.app), base_url="http://fake-github"
    )
    vector = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=fake_voyage.app), base_url="http://fake-voyage"
    )
    github.use_client(git)
    voyage.use_client(vector)

    async def no_pause(seconds: float) -> None:
        del seconds

    monkeypatch.setattr("app.services.voyage.pause", no_pause)
    try:
        yield
    finally:
        github.use_client(None)
        voyage.use_client(None)
        await git.aclose()
        await vector.aclose()


def role_bearer(role: UserRole) -> dict[str, str]:
    """A caller for the route gates, which read only the access token: no account is stored."""
    claims = AccessClaims(sub=str(uuid.uuid4()), role=role, sid=str(uuid.uuid4()))
    return {"Authorization": f"Bearer {sign_access(claims).token}"}


def admin_bearer() -> dict[str, str]:
    return role_bearer(UserRole.admin)


def member_bearer() -> dict[str, str]:
    return role_bearer(UserRole.user)


async def make_admin(email: str = "boss@example.com") -> dict[str, str]:
    """A stored account promoted to admin, for a test that needs the account to exist."""
    account = await user.create_user(CreateUserInput(email=email, password=PASSWORD))
    admin = await user.set_user_role(account.id, UserRole.admin)
    return bearer_of(mint_token(admin))


async def connect(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    url: str = HELLO_WORLD,
    ref: str | None = None,
) -> httpx.Response:
    body: dict[str, str] = {"url": url} if ref is None else {"url": url, "ref": ref}
    return await client.post("/api/source", headers=headers, json=body)


@dataclass(frozen=True)
class StoredDocument:
    id: str
    source_id: str
    path: str


@dataclass(frozen=True)
class StoredChunk:
    id: str
    path: str
    symbol: str | None
    start_line: int
    end_line: int
    content: str
    dimensions: int


async def stored_documents(source_id: str) -> list[StoredDocument]:
    return await fetch_all(
        StoredDocument,
        "select id, source_id, path from document where source_id = %s order by path",
        (source_id,),
    )


async def stored_chunks(source_id: str) -> list[StoredChunk]:
    return await fetch_all(
        StoredChunk,
        "select c.id, d.path, c.symbol, c.start_line, c.end_line, c.content, "
        "vector_dims(c.embedding) as dimensions "
        "from chunk c join document d on d.id = c.document_id where d.source_id = %s "
        "order by d.path, c.start_line, c.id",
        (source_id,),
    )
