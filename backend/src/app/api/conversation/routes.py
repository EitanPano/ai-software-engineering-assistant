"""routes.py belongs: this directory's router. Each endpoint is one `add_api_route`: the handler,
the status and response model, the error responses, the summary and the gates.
It does not belong: request handling or business rules (`controller.py`) or queries
(`service.py`).
"""

from fastapi import APIRouter, Depends

from app.api.conversation.controller import (
    create_conversation,
    get_conversation,
    list_conversation,
    list_message,
    send_message,
)
from app.api.conversation.schema import (
    Conversation,
    ConversationDetail,
    ConversationPage,
    MessagePage,
    SentMessage,
)
from app.config.constants import RATE_LIMITS
from app.middleware.auth import require_auth
from app.middleware.rate_limit import by_caller, rate_limit
from app.services.utils.openapi import error_responses

# `require_auth` is declared before this limiter: the key is the caller, which the auth gate
# resolves (the reverse of the auth routes, whose key is in the body).
send_limit = rate_limit(
    name="message_per_user",
    limit=RATE_LIMITS.message_per_user.limit,
    window=RATE_LIMITS.message_per_user.window,
    key=by_caller,
)

router = APIRouter()

router.add_api_route(
    "",
    create_conversation,
    methods=["POST"],
    status_code=201,
    response_model=Conversation,
    response_description="The created conversation",
    responses={**error_responses(401, 500)},
    summary="Start a conversation",
    tags=["conversation"],
    dependencies=[Depends(require_auth)],
)
router.add_api_route(
    "",
    list_conversation,
    methods=["GET"],
    status_code=200,
    response_model=ConversationPage,
    response_description="A page of the caller's conversations, latest activity first",
    responses={**error_responses(400, 401, 500)},
    summary="List the caller's conversations",
    tags=["conversation"],
    dependencies=[Depends(require_auth)],
)
router.add_api_route(
    "/{id}",
    get_conversation,
    methods=["GET"],
    status_code=200,
    response_model=ConversationDetail,
    response_description="The conversation and its latest run",
    responses={**error_responses(400, 401, 404, 500)},
    summary="Get a conversation",
    tags=["conversation"],
    dependencies=[Depends(require_auth)],
)
router.add_api_route(
    "/{id}/message",
    list_message,
    methods=["GET"],
    status_code=200,
    response_model=MessagePage,
    response_description="A page of messages, newest first",
    responses={**error_responses(400, 401, 404, 500)},
    summary="List a conversation's messages",
    tags=["conversation"],
    dependencies=[Depends(require_auth)],
)
router.add_api_route(
    "/{id}/message",
    send_message,
    methods=["POST"],
    status_code=201,
    response_model=SentMessage,
    response_description="The stored message and the run that answers it",
    responses={**error_responses(400, 401, 404, 409, 429, 500)},
    summary="Send a message",
    tags=["conversation"],
    dependencies=[Depends(require_auth), Depends(send_limit)],
)
