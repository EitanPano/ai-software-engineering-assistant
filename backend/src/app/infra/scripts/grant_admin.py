"""`python -m app.infra.scripts.grant_admin <email>`: makes an existing account an admin. There is
no endpoint for it; this is the first admin's only way in, and a person with shell access runs it.

`register` takes any address, and a verified email proves the mailbox, not the password, so the
script asks for the account's password and checks it through auth's `verify_credentials`: whoever
pre-registered the address with another password cannot be promoted by it. The password is read
from a hidden prompt on a terminal, otherwise from one line of stdin (for automation), and never
from the arguments, which a process list shows. Exactly one argument is accepted, the email.

A wrong password and an unknown email give the same message. Once the password checks out, an
account that is already an admin is left alone (exit 0, nothing written). Otherwise the script
ends the account's sessions, because a refresh re-reads the role and would hand a session opened
before the promotion an admin token, then sets the role. The promoted account signs in again.

It logs the user id only: never the email, the password or the hash. Exit 0 on success, 1 on
anything else.
"""

import asyncio
import contextlib
import sys
from collections.abc import Callable, Sequence
from getpass import getpass
from typing import Final

from pydantic import ValidationError

from app.api.auth.controller import verify_credentials
from app.api.auth.schema import Credentials
from app.api.user.controller import set_user_role
from app.infra.loop import selector_loop_factory
from app.infra.postgres import postgres
from app.models.user.enums import UserRole
from app.services.logger import Logger, configure_logging, log
from app.services.session import revoke_all_sessions
from app.services.utils.error import AppError

USAGE: Final = "usage: grant_admin <email>; the password is prompted for or read from stdin"
REFUSED: Final = "invalid email or password"


def read_password() -> str:
    """A hidden prompt on a terminal, else one line of stdin without its line ending."""
    if sys.stdin.isatty():
        return getpass("Password: ")
    return sys.stdin.readline().rstrip("\r\n")


async def grant_admin(argv: Sequence[str], logger: Logger, password: Callable[[], str]) -> int:
    if len(argv) != 1 or argv[0].startswith("-"):
        logger.error(USAGE)
        return 1
    typed = password()
    if not typed:
        logger.error("no password was given")
        return 1

    try:
        # Built here, inside the handled path: its fields are validated, and a failure must not
        # echo the value.
        credentials = Credentials.model_validate({"email": argv[0], "password": typed})
        account = await verify_credentials(credentials)
    except ValidationError:
        logger.error(REFUSED)
        return 1
    except AppError as error:
        logger.error(REFUSED if error.code == "unauthenticated" else "the account is blocked")
        return 1

    if account.role is UserRole.admin:
        logger.info("already an admin", {"userId": account.id})
        return 0
    await revoke_all_sessions(account.id)
    await set_user_role(account.id, UserRole.admin)
    logger.info("promoted to admin; the account signs in again", {"userId": account.id})
    return 0


async def main(
    argv: Sequence[str], *, logger: Logger = log, read_password: Callable[[], str] = read_password
) -> int:
    configure_logging()
    try:
        return await grant_admin(argv, logger, read_password)
    except Exception as error:
        logger.error("granting admin failed", {}, error)
        return 1
    finally:
        with contextlib.suppress(Exception):
            await postgres.close()


if __name__ == "__main__":
    # psycopg refuses Windows' default Proactor loop (ADR 0002, M4-19).
    sys.exit(asyncio.run(main(sys.argv[1:]), loop_factory=selector_loop_factory))
