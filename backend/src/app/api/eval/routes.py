"""routes.py belongs: the eval module's router. Each endpoint is one `add_api_route`: the handler,
the status and response model, the error responses, the summary and the gates. Every route is
admin-only, and the start has no rate limit of its own: the admin role and the one active run bound
it.
It does not belong: request handling or business rules (`controller.py`) or queries
(`service.py`).
"""

from fastapi import APIRouter, Depends

from app.api.eval.controller import get_eval_run, list_eval_run, start_eval_run
from app.api.eval.schema import EvalRun, EvalRunDetail, EvalRunPage
from app.middleware.role import require_role
from app.models.user.enums import UserRole
from app.services.utils.openapi import error_responses

router = APIRouter()

require_admin = require_role(UserRole.admin)

router.add_api_route(
    "",
    start_eval_run,
    methods=["POST"],
    status_code=201,
    response_model=EvalRun,
    response_description="The eval run, queued",
    responses={**error_responses(401, 403, 409, 500)},
    summary="Start an eval run (admin)",
    tags=["eval-run"],
    dependencies=[Depends(require_admin)],
)
router.add_api_route(
    "",
    list_eval_run,
    methods=["GET"],
    status_code=200,
    response_model=EvalRunPage,
    response_description="A page of eval runs, newest first",
    responses={**error_responses(400, 401, 403, 500)},
    summary="List eval runs (admin)",
    tags=["eval-run"],
    dependencies=[Depends(require_admin)],
)
router.add_api_route(
    "/{id}",
    get_eval_run,
    methods=["GET"],
    status_code=200,
    response_model=EvalRunDetail,
    response_description="One eval run with its scores and cases",
    responses={**error_responses(400, 401, 403, 404, 500)},
    summary="Get an eval run (admin)",
    tags=["eval-run"],
    dependencies=[Depends(require_admin)],
)
