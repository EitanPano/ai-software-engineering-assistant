"""The mount table: one line per API module, in mount order.

This is the only module that imports a module's routes.py, and only server.py and tests import this
one (both are checked by import-linter). Adding a module is its package, a line here, its component
names in openapi.py, then running `uv run poe contract`: FastAPI derives the OpenAPI paths from the
mounted routers, so there is no registration list.
"""

from fastapi import FastAPI

from app.api.approval.routes import router as approval_router
from app.api.auth.routes import router as auth_router
from app.api.conversation.routes import router as conversation_router
from app.api.eval.routes import router as eval_router
from app.api.health.routes import router as health_router
from app.api.mcp_server.routes import router as mcp_server_router
from app.api.run.routes import router as run_router
from app.api.search.routes import router as search_router
from app.api.source.routes import router as source_router
from app.api.tool_policy.routes import router as tool_policy_router
from app.api.user.routes import router as user_router


def register_routes(app: FastAPI) -> None:
    app.include_router(health_router, prefix="/api/health")
    app.include_router(auth_router, prefix="/api/auth")
    app.include_router(user_router, prefix="/api/user")
    app.include_router(conversation_router, prefix="/api/conversation")
    app.include_router(run_router, prefix="/api/run")
    app.include_router(approval_router, prefix="/api/approval")
    app.include_router(source_router, prefix="/api/source")
    app.include_router(search_router, prefix="/api/search")
    app.include_router(eval_router, prefix="/api/eval-run")
    app.include_router(mcp_server_router, prefix="/api/mcp-server")
    app.include_router(tool_policy_router, prefix="/api/tool-policy")
