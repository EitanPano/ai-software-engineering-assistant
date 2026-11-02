"""routes.py belongs: this directory's router, one `add_api_route` per endpoint with its gates.
It does not belong: request handling or business rules (`controller.py`) or queries
(`service.py`).
"""

from fastapi import APIRouter, Depends
from fastapi.sse import EventSourceResponse

from app.api.run.controller import stream_run_event
from app.config.constants import RATE_LIMITS
from app.middleware.auth import require_auth
from app.middleware.rate_limit import by_caller, rate_limit
from app.services.utils.openapi import error_responses

# After `require_auth`: the key is the caller. A stream holds database connections for as long as
# it is open, so opens are limited per user and each open ends at `AGENT_STREAM_MAX_SECONDS`.
stream_limit = rate_limit(
    name="run_stream_per_user",
    limit=RATE_LIMITS.run_stream_per_user.limit,
    window=RATE_LIMITS.run_stream_per_user.window,
    key=by_caller,
)

router = APIRouter()

router.add_api_route(
    "/{id}/event",
    stream_run_event,
    methods=["GET"],
    status_code=200,
    response_class=EventSourceResponse,
    response_description="The run's events as server-sent events; each `id` is the sequence",
    responses={**error_responses(400, 401, 404, 429, 500)},
    summary="Stream a run's events",
    tags=["run"],
    dependencies=[Depends(require_auth), Depends(stream_limit)],
)
