"""execute_run.py belongs: the reaction to `run.created`, which hands the run to the agent. The bus
runs it detached from the send that published it, so the request answers at once and the run goes
on beside it. It does not belong: the loop (`api/agent/controller.py`).

A failure the agent did not turn into a finished run propagates to the bus, which logs it; the run
stays active until the next boot's sweep ends it as `interrupted`.
"""

from app.api.agent.controller import execute_run
from app.infra.pubsub import SubscriberEntry
from app.services.event import RUN_CREATED, RunCreated, subscriber


async def handle_run_created(payload: RunCreated) -> None:
    await execute_run(payload["run_id"])


execute_run_on_created: SubscriberEntry = subscriber(RUN_CREATED, handle_run_created)
