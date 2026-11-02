"""routes.py belongs: this directory's router. Each endpoint is one `add_api_route`: the handler,
the status and response model, the error responses, the summary and the gates.
It does not belong: request handling or business rules (`controller.py`) or queries
(`service.py`).
"""

from fastapi import APIRouter, Depends

from app.api.memory.controller import delete_memory, list_memory
from app.api.memory.schema import MemoryPage
from app.middleware.auth import require_auth
from app.services.utils.openapi import error_responses

router = APIRouter()

router.add_api_route(
    "",
    list_memory,
    methods=["GET"],
    status_code=200,
    response_model=MemoryPage,
    response_description="A page of the caller's memories, newest first",
    responses={**error_responses(400, 401, 500)},
    summary="List the caller's memories",
    tags=["memory"],
    dependencies=[Depends(require_auth)],
)
router.add_api_route(
    "/{id}",
    delete_memory,
    methods=["DELETE"],
    status_code=204,
    response_description="The memory is deleted",
    responses={**error_responses(400, 401, 404, 500)},
    summary="Delete one of the caller's memories",
    tags=["memory"],
    dependencies=[Depends(require_auth)],
)
