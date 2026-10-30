import asyncio
import base64
import json
import uuid
from collections.abc import AsyncIterator, Awaitable
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from psycopg import errors
from pydantic import JsonValue

from app.api.user import service as user_service
from app.infra.pubsub import pubsub
from app.models.user.enums import UserRole, UserStatus
from app.models.user.interface import UserRecord
from app.services.security.jwt import AccessClaims, sign_access
from app.services.utils.error import AppError
from app.services.utils.postgres_error import classify_postgres_error
from tests.auth_support import PASSWORD, bearer_of
from tests.store import reset_store, store_backed
from tests.support import error_of

pytestmark = store_backed


def record(
    email: str,
    *,
    user_id: str | None = None,
    role: UserRole = UserRole.user,
    phone: str | None = None,
    password_hash: str | None = None,
    phone_verified_at: datetime | None = None,
    created_at: datetime | None = None,
) -> UserRecord:
    now = datetime.now(UTC) if created_at is None else created_at
    return UserRecord(
        id=str(uuid.uuid4()) if user_id is None else user_id,
        email=email,
        phone=phone,
        password_hash=password_hash,
        role=role,
        status=UserStatus.active,
        phone_verified_at=phone_verified_at,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture(autouse=True)
async def empty_store() -> AsyncIterator[None]:
    await reset_store()
    yield
    await reset_store()


async def conflict_of(call: Awaitable[object]) -> AppError:
    """The `AppError` the classifier makes of the unique violation `call` raises."""
    try:
        await call
    except errors.UniqueViolation as error:
        classified = classify_postgres_error(error)
        assert classified is not None
        return classified
    raise AssertionError("expected a unique violation")


class TestTheUserServiceOnPostgres:
    async def test_maps_a_second_insert_of_the_same_email_to_a_conflict(self) -> None:
        await user_service.insert_user(record("dup@example.com"))

        error = await conflict_of(user_service.insert_user(record("dup@example.com")))

        assert error.code == "conflict"

    async def test_lets_an_unverified_phone_be_claimed_twice_but_a_verified_one_only_once(
        self,
    ) -> None:
        await user_service.insert_user(record("a@example.com", phone="+15550001"))
        await user_service.insert_user(record("b@example.com", phone="+15550001"))
        assert await user_service.find_user_by_verified_phone("+15550001") is None

        await user_service.insert_user(
            record("c@example.com", phone="+15550002", phone_verified_at=datetime.now(UTC))
        )
        error = await conflict_of(
            user_service.insert_user(
                record("d@example.com", phone="+15550002", phone_verified_at=datetime.now(UTC))
            )
        )

        assert error.code == "conflict"
        owner = await user_service.find_user_by_verified_phone("+15550002")
        assert owner is not None
        assert owner.email == "c@example.com"

    async def test_clears_optional_fields_the_record_omits_and_reads_absent_ones_as_none(
        self,
    ) -> None:
        created = await user_service.insert_user(
            record("x@example.com", phone="+15550003", phone_verified_at=datetime.now(UTC))
        )

        updated = await user_service.update_user(
            replace(created, phone=None, phone_verified_at=None)
        )

        assert updated.phone is None
        assert updated.phone_verified_at is None
        assert await user_service.find_user_by_email("x@example.com") == updated

    async def test_round_trips_a_record_and_finds_it_by_id_and_by_email(self) -> None:
        created = await user_service.insert_user(
            record("round@example.com", password_hash="hash", role=UserRole.admin)
        )

        assert await user_service.find_user_by_id(created.id) == created
        assert await user_service.find_user_by_email("round@example.com") == created
        assert await user_service.find_user_by_email("ROUND@example.com") is None
        assert created.role is UserRole.admin
        assert created.password_hash == "hash"

    async def test_pages_users_by_created_at_and_id(self) -> None:
        same = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
        for name in ("d", "a", "c", "b"):
            await user_service.insert_user(
                record(f"{name}@example.com", user_id=name, created_at=same)
            )

        first = await user_service.list_users(cursor=None, limit=3)
        second = await user_service.list_users(cursor=first.next_cursor, limit=3)

        assert [user.id for user in first.items] == ["a", "b", "c"]
        assert [user.id for user in second.items] == ["d"]
        assert second.next_cursor is None

    async def test_returns_timestamps_in_utc_with_their_precision(self) -> None:
        created_at = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
        created = await user_service.insert_user(record("utc@example.com", created_at=created_at))

        found = await user_service.find_user_by_id(created.id)

        assert found == created
        assert found is not None
        assert found.created_at == created_at
        assert found.created_at.utcoffset() == UTC.utcoffset(None)

    async def test_lists_an_empty_table_as_an_empty_page_and_rejects_an_invalid_cursor(
        self,
    ) -> None:
        page = await user_service.list_users(cursor=None, limit=5)

        assert (page.items, page.next_cursor) == ([], None)
        with pytest.raises(AppError) as raised:
            await user_service.list_users(cursor="not-a-cursor", limit=5)
        assert raised.value.code == "validation_failed"

    async def test_sends_every_value_as_a_parameter_never_inside_the_statement(self) -> None:
        hostile = 'x\'); drop table "user"; --@example.com'

        created = await user_service.insert_user(record(hostile, user_id="quoted'id"))

        assert await user_service.find_user_by_id("quoted'id") == created
        assert await user_service.find_user_by_email(hostile) == created
        assert await user_service.find_user_by_id("' or '1'='1") is None
        assert await user_service.find_user_by_email("' or '1'='1") is None


async def admin_headers() -> dict[str, str]:
    boss = await user_service.insert_user(record("boss@example.com", role=UserRole.admin))
    claims = AccessClaims(sub=boss.id, role=UserRole.admin, sid=str(uuid.uuid4()))
    return bearer_of(sign_access(claims).token)


def forged_cursor(payload: JsonValue) -> str:
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class TestCursorIsStrict:
    @pytest.mark.parametrize(
        "created_at",
        [0, 1767225600, True, "2026-01-01", "1767225600", "2026-01-01T00:00:00", None, 1.5],
    )
    async def test_rejects_a_created_at_that_is_not_an_iso_string_with_a_timezone(
        self, client: httpx.AsyncClient, created_at: JsonValue
    ) -> None:
        """A Unix timestamp is not a cursor."""
        cursor = forged_cursor({"created_at": created_at, "id": "a"})

        res = await client.get(
            "/api/user", params={"cursor": cursor}, headers=await admin_headers()
        )

        assert res.status_code == 400
        assert res.json()["error"]["message"] == "invalid cursor"

    async def test_still_accepts_the_cursor_the_list_wrote(self, client: httpx.AsyncClient) -> None:
        headers = await admin_headers()
        await user_service.insert_user(record("second@example.com"))
        first = (await client.get("/api/user?limit=1", headers=headers)).json()

        res = await client.get("/api/user", params={"cursor": first["nextCursor"]}, headers=headers)

        assert res.status_code == 200
        assert [user["email"] for user in res.json()["items"]] == ["second@example.com"]


class TestGetUserOnPostgres:
    async def test_answers_400_validation_failed_for_a_forged_cursor_with_a_non_date_created_at(
        self, client: httpx.AsyncClient
    ) -> None:
        boss = await user_service.insert_user(record("boss@example.com", role=UserRole.admin))
        token = sign_access(
            AccessClaims(sub=boss.id, role=UserRole.admin, sid=str(uuid.uuid4()))
        ).token
        forged = base64.urlsafe_b64encode(
            json.dumps({"created_at": "x", "id": "y"}).encode()
        ).rstrip(b"=")

        res = await client.get(
            "/api/user", params={"cursor": forged.decode()}, headers=bearer_of(token)
        )

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"


class TestRegisterOnPostgres:
    async def test_answers_one_201_and_one_409_conflict_for_two_concurrent_registrations(
        self, client: httpx.AsyncClient
    ) -> None:
        await pubsub.connect()
        try:

            async def send() -> httpx.Response:
                return await client.post(
                    "/api/auth/register",
                    json={"email": "race@example.com", "password": PASSWORD},
                )

            responses = await asyncio.gather(send(), send())

            assert sorted(res.status_code for res in responses) == [201, 409]
            failed = next(res for res in responses if res.status_code == 409)
            assert error_of(failed).code == "conflict"
            assert failed.headers["x-request-id"] == failed.json()["requestId"]
            assert "user_email_idx" not in failed.text
        finally:
            await pubsub.close()
