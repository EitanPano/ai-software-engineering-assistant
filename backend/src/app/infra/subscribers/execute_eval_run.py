"""execute_eval_run.py belongs: the reaction to `eval_run.queued`, which hands the run to the eval
module. The bus runs it detached from the start that published it, so the request answers at once
and the run goes on beside it. It does not belong: the run (`api/eval/controller.py`).

`execute_eval_run` ends the run `completed` or `failed` on every exit, so a failure never reaches
the bus; one that does is logged there, and the next boot's sweep ends the run as `interrupted`.
"""

from app.api.eval.controller import execute_eval_run
from app.infra.pubsub import SubscriberEntry
from app.services.event import EVAL_RUN_QUEUED, EvalRunQueued, subscriber


async def handle_eval_run_queued(payload: EvalRunQueued) -> None:
    await execute_eval_run(payload["eval_run_id"])


execute_eval_run_on_queued: SubscriberEntry = subscriber(EVAL_RUN_QUEUED, handle_eval_run_queued)
