"""`python -m app.infra.scripts.seed_eval_case <file.json>`: stores the labelled eval cases of one
pinned commit. The file is `{ "pinnedCommit": "<40 hex>", "cases": [{ "kind", "question",
"expectedChunks": [{ "path", "startLine", "endLine" }] }] }`, validated by
`EvalCaseFile` in `api/eval/schema.py`: a `no_answer` case holds no expected chunk, any other
kind at least one, and a question is held to what a search text is.

It replaces that commit's cases in one transaction (a second seed of the file leaves one set;
questions the file no longer holds are dropped; other commits are untouched) and refuses a total
over the run's cap. Exit 0 on success, 1 on a bad file or anything else, writing nothing. Free: no
network and no key. It logs counts, never a question.
"""

import asyncio
import contextlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from app.api.eval.controller import replace_eval_cases
from app.api.eval.schema import EvalCaseFile
from app.infra.loop import selector_loop_factory
from app.infra.postgres import postgres
from app.services.logger import configure_logging, log
from app.services.utils.error import AppError

USAGE: Final = "usage: seed_eval_case <cases.json>"


async def seed(argv: Sequence[str]) -> int:
    if len(argv) != 1 or argv[0].startswith("-"):
        log.error(USAGE)
        return 1
    try:
        text = await asyncio.to_thread(Path(argv[0]).read_text, encoding="utf-8")
        raw = json.loads(text)
        file = EvalCaseFile.model_validate(raw)
    except OSError, ValueError:
        # `ValidationError` and `json.JSONDecodeError` are both `ValueError`s. The message of a
        # validation error holds the offending input, so only where it is is logged.
        log.error("the case file is unreadable or invalid", {"file": Path(argv[0]).name})
        return 1
    try:
        count = await replace_eval_cases(file)
    except AppError as error:
        log.error("the cases were refused", {"reason": error.code})
        return 1
    log.info("seeded eval cases", {"commit": file.pinned_commit, "cases": count})
    return 0


async def main(argv: Sequence[str]) -> int:
    configure_logging()
    try:
        return await seed(argv)
    except Exception as error:
        log.error("seeding eval cases failed", {}, error)
        return 1
    finally:
        with contextlib.suppress(Exception):
            await postgres.close()


if __name__ == "__main__":
    # psycopg refuses Windows' default Proactor loop.
    sys.exit(asyncio.run(main(sys.argv[1:]), loop_factory=selector_loop_factory))
