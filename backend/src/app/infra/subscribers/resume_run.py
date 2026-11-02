"""resume_run.py belongs: the reaction to `run.resumed`, which hands a run whose last approval was
decided back to the agent. The bus runs it detached from the decision that published it, so the
request answers at once. It does not belong: the loop (`api/agent/controller.py`).

A failure the agent did not turn into a finished run propagates to the bus, which logs it; the run
stays `running` until the next boot's sweep ends it as `interrupted`, and its approved calls have
run at most once.
"""

from app.api.agent.controller import resume_run
from app.infra.pubsub import SubscriberEntry
from app.services.event import RUN_RESUMED, RunResumed, subscriber


async def handle_run_resumed(payload: RunResumed) -> None:
    await resume_run(payload["run_id"])


resume_run_on_resumed: SubscriberEntry = subscriber(RUN_RESUMED, handle_run_resumed)
