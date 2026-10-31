"""`python -m tests.seed_eval_fixture`: stores the fixture repository's eval cases (`tests/
eval_support.py`) in the database `DATABASE_URL` names, for the e2e suite. Free: no network and no
key. It replaces the cases of the fixture commit, so running it twice leaves one set.
"""

import asyncio
import contextlib
import sys

from app.api.eval.controller import replace_eval_cases
from app.infra.loop import selector_loop_factory
from app.infra.postgres import postgres
from tests.eval_support import fixture_case_file


async def main() -> int:
    try:
        await replace_eval_cases(fixture_case_file())
    finally:
        with contextlib.suppress(Exception):
            await postgres.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(), loop_factory=selector_loop_factory))
