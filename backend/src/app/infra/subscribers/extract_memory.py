"""extract_memory.py belongs: the reaction to `run.completed`, which hands the run to memory
extraction. The bus runs it detached from the run that published it, so the run is already over and
a failure of the side call can touch nothing of it. It does not belong: the extraction itself
(`api/memory/controller.py`).

The bus is in process, so a crash between `run_finished` and this reaction loses that one
extraction; the person can say the fact again.
"""

from app.api.memory.controller import extract_memory
from app.infra.pubsub import SubscriberEntry
from app.services.event import RUN_COMPLETED, RunCompleted, subscriber


async def handle_run_completed(payload: RunCompleted) -> None:
    await extract_memory(run_id=payload["run_id"])


extract_memory_on_completed: SubscriberEntry = subscriber(RUN_COMPLETED, handle_run_completed)
