"""routes.py belongs: this directory's router, one `add_api_route` per endpoint with its gates.
It does not belong: request handling or business rules (`controller.py`).
"""

from fastapi import APIRouter, Depends

from app.api.approval.controller import decide_approval
from app.api.approval.schema import Approval
from app.middleware.auth import require_auth
from app.services.utils.openapi import error_responses

router = APIRouter()

# No role and no limiter: a decision spends a row the run's budget already bounded.
router.add_api_route(
    "/{id}/decision",
    decide_approval,
    methods=["POST"],
    status_code=200,
    response_model=Approval,
    response_description="The recorded decision",
    responses={**error_responses(400, 401, 404, 409, 500)},
    summary="Approve or reject a waiting tool call",
    tags=["approval"],
    dependencies=[Depends(require_auth)],
)
