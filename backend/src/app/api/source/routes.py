"""routes.py belongs: the source module's router. Each endpoint is one `add_api_route`: the handler,
the status and response model, the error responses, the summary and the gates. Every route is
admin-only.
It does not belong: request handling or business rules (`controller.py`) or queries
(`service.py`).
"""

from fastapi import APIRouter, Depends

from app.api.source.controller import connect_source, list_source, retry_source
from app.api.source.schema import Source, SourcePage
from app.middleware.role import require_role
from app.models.user.enums import UserRole
from app.services.utils.openapi import error_responses

router = APIRouter()

require_admin = require_role(UserRole.admin)

router.add_api_route(
    "",
    connect_source,
    methods=["POST"],
    status_code=201,
    response_model=Source,
    response_description="The connected source, queued for indexing",
    responses={**error_responses(400, 401, 403, 404, 409, 500, 503)},
    summary="Connect a GitHub repository (admin)",
    tags=["source"],
    dependencies=[Depends(require_admin)],
)
router.add_api_route(
    "",
    list_source,
    methods=["GET"],
    status_code=200,
    response_model=SourcePage,
    response_description="A page of sources, newest first",
    responses={**error_responses(400, 401, 403, 500)},
    summary="List sources (admin)",
    tags=["source"],
    dependencies=[Depends(require_admin)],
)
router.add_api_route(
    "/{id}/indexing",
    retry_source,
    methods=["POST"],
    status_code=202,
    response_model=Source,
    response_description="The failed source, queued again",
    responses={**error_responses(400, 401, 403, 404, 409, 500)},
    summary="Retry indexing a failed source (admin)",
    tags=["source"],
    dependencies=[Depends(require_admin)],
)
