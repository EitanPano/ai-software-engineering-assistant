import asyncio
import io
from collections.abc import Callable
from dataclasses import replace

import httpx
import pytest

from app.api.user import controller as user
from app.api.user import service as user_service
from app.infra.scripts import grant_admin as script
from app.infra.scripts.grant_admin import main
from app.models.user.enums import ContactType, UserRole, UserStatus
from app.models.user.type import ContactTarget, CreateUserInput, PublicUser
from app.server import app
from app.services.logger import Logger
from tests.auth_support import PASSWORD
from tests.store import reset_store, store_backed
from tests.support import LineSink, http_client, recording_logger

pytestmark = store_backed

EMAIL = "boss@example.com"
OTHER = "other@example.com"
WRONG = "not the right password"
HOSTILE = "boss@example.com'; update \"user\" set role='admin'; --"


@pytest.fixture(autouse=True)
async def empty_store() -> None:
    await reset_store()


async def account(email: str = EMAIL, *, verified: bool = False) -> PublicUser:
    created = await user.create_user(CreateUserInput(email=email, password=PASSWORD))
    return await user.mark_verified(created.id, ContactType.email) if verified else created


async def current(email: str = EMAIL) -> PublicUser:
    found = await user.find_user_by_target(ContactTarget(type=ContactType.email, value=email))
    assert found is not None
    return found


def typed(password: str) -> Callable[[], str]:
    return lambda: password


async def run(argv: list[str], password: str = PASSWORD, *, logger: Logger | None = None) -> int:
    chosen = recording_logger()[0] if logger is None else logger
    return await main(argv, logger=chosen, read_password=typed(password))


async def sign_in(client: httpx.AsyncClient, email: str = EMAIL) -> httpx.Response:
    return await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})


class TestGrantAdmin:
    async def test_promotes_with_the_password_and_the_next_sign_in_reaches_the_admin_list(
        self, client: httpx.AsyncClient
    ) -> None:
        await account()
        logger, sink = recording_logger()

        assert await run([EMAIL], logger=logger) == 0

        assert (await current()).role is UserRole.admin
        assert (await sign_in(client)).status_code == 200
        assert (await client.get("/api/user")).status_code == 200
        assert [line for line in sink.lines if "promoted" in line]

    async def test_ends_the_sessions_opened_before_the_promotion(
        self, client: httpx.AsyncClient
    ) -> None:
        await account()
        old = (await sign_in(client)).json()["tokens"]["refreshToken"]

        assert await run([EMAIL]) == 0

        async with http_client(app) as bare:  # no cookie jar, so the body token is the one read
            res = await bare.post("/api/auth/refresh", json={"refreshToken": old})
        assert res.status_code == 401

    async def test_leaves_another_accounts_sessions_alone(self, client: httpx.AsyncClient) -> None:
        await account()
        await account(OTHER, verified=True)
        other = (await sign_in(client, OTHER)).json()["tokens"]["refreshToken"]

        assert await run([EMAIL]) == 0

        async with http_client(app) as bare:
            res = await bare.post("/api/auth/refresh", json={"refreshToken": other})
        assert res.status_code == 200

    async def test_a_second_run_writes_nothing_and_keeps_the_sessions(
        self, client: httpx.AsyncClient
    ) -> None:
        await account()
        await run([EMAIL])
        first = await current()
        fresh = (await sign_in(client)).json()["tokens"]["refreshToken"]

        assert await run([EMAIL]) == 0

        assert await current() == first
        refreshed = await client.post("/api/auth/refresh", json={"refreshToken": fresh})
        assert refreshed.status_code == 200

    async def test_matches_the_email_in_any_letter_case_and_with_surrounding_space(self) -> None:
        await account()
        bystander = await account(OTHER, verified=True)

        assert await run([" Boss@Example.com "]) == 0

        assert (await current()).role is UserRole.admin
        assert await current(OTHER) == bystander

    async def test_two_runs_at_once_leave_one_admin(self) -> None:
        await account()
        logger, _ = recording_logger()

        results = await asyncio.gather(run([EMAIL], logger=logger), run([EMAIL], logger=logger))

        assert list(results) == [0, 0]
        assert (await current()).role is UserRole.admin


class TestGrantAdminRefuses:
    async def test_a_pre_registered_account_stays_unpromoted_even_with_its_email_verified(
        self, client: httpx.AsyncClient
    ) -> None:
        """The attack: someone registered the address with their own password; the owner then
        verified the mailbox by code, which keeps that password."""
        await account(verified=True)
        refresh = (await sign_in(client)).json()["tokens"]["refreshToken"]
        before = await current()

        assert await run([EMAIL], WRONG) == 1

        assert await current() == before
        assert before.role is UserRole.user
        refreshed = await client.post("/api/auth/refresh", json={"refreshToken": refresh})
        assert refreshed.status_code == 200

    async def test_an_unknown_email_and_a_wrong_password_give_the_same_line(self) -> None:
        bystander = await account(OTHER)
        wrong_logger, wrong = recording_logger()
        unknown_logger, unknown = recording_logger()

        assert await run([OTHER], WRONG, logger=wrong_logger) == 1
        assert await run(["nobody@example.com"], logger=unknown_logger) == 1

        assert wrong.lines == unknown.lines
        assert await current(OTHER) == bystander

    async def test_a_blocked_account_exits_one_and_writes_nothing(self) -> None:
        await account()
        record = await user_service.find_user_by_email(EMAIL)
        assert record is not None
        await user_service.update_user(replace(record, status=UserStatus.blocked))
        before = await current()
        logger, sink = recording_logger()

        assert await run([EMAIL], logger=logger) == 1

        assert await current() == before
        assert before.role is UserRole.user
        assert sink.lines

    @pytest.mark.parametrize(
        "argv",
        [
            [],
            [EMAIL, PASSWORD],
            [EMAIL, "--password", PASSWORD],
            [f"--password={PASSWORD}", EMAIL],
            [EMAIL, "--allow-unverified"],
            [EMAIL, "--admin"],
            ["-x"],
            ["--", EMAIL],
            ["--allow-unverified"],
        ],
    )
    async def test_a_wrong_argument_exits_one_and_writes_nothing(self, argv: list[str]) -> None:
        before = await account(verified=True)
        logger, sink = recording_logger()

        assert await run(argv, logger=logger) == 1

        assert await current() == before
        assert sink.lines
        assert PASSWORD not in "\n".join(sink.lines)

    @pytest.mark.parametrize("email", ["", " ", "%", HOSTILE])
    async def test_an_invalid_email_exits_one_cleanly_and_promotes_nobody(self, email: str) -> None:
        before = await account(verified=True)
        logger, sink = recording_logger()

        assert await run([email], logger=logger) == 1

        assert await current() == before
        text = "\n".join(sink.lines)
        assert sink.lines
        assert "Traceback" not in text
        assert "update" not in text

    async def test_a_password_that_fails_validation_exits_one_without_echoing_it(self) -> None:
        before = await account()
        logger, sink = recording_logger()

        assert await run([EMAIL], "x", logger=logger) == 1

        assert await current() == before
        assert sink.lines
        assert not [line for line in sink.lines if line.endswith("x") or "'x'" in line]

    async def test_an_empty_password_exits_one(self) -> None:
        before = await account()

        assert await run([EMAIL], "") == 1

        assert await current() == before


class TestReadingThePassword:
    async def test_empty_stdin_exits_one_and_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        before = await account()
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        logger, sink = recording_logger()

        assert await main([EMAIL], logger=logger) == 1

        assert await current() == before
        assert sink.lines

    async def test_reads_one_line_of_stdin_without_its_newline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await account()
        monkeypatch.setattr("sys.stdin", io.StringIO(f"{PASSWORD}\nignored\n"))
        logger, _ = recording_logger()

        assert await main([EMAIL], logger=logger) == 0

        assert (await current()).role is UserRole.admin

    async def test_prompts_without_echo_on_a_terminal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Terminal(io.StringIO):
            def isatty(self) -> bool:
                return True

        prompts: list[str] = []

        def fake_getpass(prompt: str) -> str:
            prompts.append(prompt)
            return "typed"

        monkeypatch.setattr("sys.stdin", Terminal(""))
        monkeypatch.setattr(script, "getpass", fake_getpass)

        assert script.read_password() == "typed"
        assert len(prompts) == 1


class TestGrantAdminLogs:
    async def test_the_failure_branch_exits_one_and_logs_without_the_password(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await account()

        async def broken(*_args: object, **_kwargs: object) -> PublicUser:
            raise RuntimeError("the store fell over")

        monkeypatch.setattr(script, "verify_credentials", broken)
        logger, sink = recording_logger()

        assert await run([EMAIL], logger=logger) == 1

        assert sink.lines == ["error granting admin failed"]

    async def test_no_line_holds_the_password_the_hash_or_the_email(self) -> None:
        await account()
        await account(OTHER, verified=True)
        await account("blocked@example.com")
        record = await user_service.find_user_by_email("blocked@example.com")
        assert record is not None
        await user_service.update_user(replace(record, status=UserStatus.blocked))
        sink = LineSink()
        logger = Logger(quiet=False, sink=sink)

        await run([EMAIL], logger=logger)
        await run([EMAIL], logger=logger)
        await run([OTHER], WRONG, logger=logger)
        await run(["blocked@example.com"], logger=logger)
        await run(["nobody@example.com"], logger=logger)
        await run([EMAIL, PASSWORD], logger=logger)

        text = "\n".join(sink.lines)
        assert text
        assert PASSWORD not in text
        assert WRONG not in text
        assert "argon2" not in text
        assert "@example.com" not in text
