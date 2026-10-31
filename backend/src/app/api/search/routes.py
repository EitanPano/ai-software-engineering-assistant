"""routes.py belongs: this directory's router. Each endpoint is one `add_api_route`: the handler,
the status and response model, the error responses, the summary and the gates. Any signed-in
account may search, so the gate takes no role.
It does not belong: request handling or business rules (`controller.py`).
"""

from fastapi import APIRouter, Depends

from app.api.search.controller import search
from app.api.search.schema import SearchResult
from app.middleware.auth import require_auth
from app.services.utils.openapi import error_responses

router = APIRouter()

router.add_api_route(
    "",
    search,
    methods=["GET"],
    status_code=200,
    response_model=SearchResult,
    response_description="The best chunks of every ready source, best first",
    responses={**error_responses(400, 401, 500, 503)},
    summary="Search the knowledge base",
    tags=["search"],
    dependencies=[Depends(require_auth)],
)
