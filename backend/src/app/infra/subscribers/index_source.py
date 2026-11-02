"""index_source.py belongs: the reaction to `source.queued`, which hands the source to the indexer.
The bus runs it detached from the connect or retry that published it, so the request answers at
once and the index goes on beside it. It does not belong: the index (`api/source/controller.py`).

`index_source` ends the source `ready` or `failed` on every exit, so a failure never reaches the
bus; one that does is logged there, and the next boot's sweep ends the source as `interrupted`.
"""

from app.api.source.controller import index_source
from app.infra.pubsub import SubscriberEntry
from app.services.event import SOURCE_QUEUED, SourceQueued, subscriber


async def handle_source_queued(payload: SourceQueued) -> None:
    await index_source(payload["source_id"])


index_source_on_queued: SubscriberEntry = subscriber(SOURCE_QUEUED, handle_source_queued)
