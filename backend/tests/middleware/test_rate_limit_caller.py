from collections.abc import AsyncIterator

import pytest
from fastapi import Depends, FastAPI

from app.infra.memory import memory
from app.middleware.auth import require_auth
from app.middleware.rate_limit import by_caller, rate_limit
from app.server import create_app
from tests.agent_support import bearer
from tests.support import error_of, http_client


@pytest.fixture(autouse=True)
async def empty_cache() -> AsyncIterator[None]:
    yield
    await memory.close()


def caller_limited_app() -> FastAPI:
    app = create_app()

    # `require_auth` first: the key is the caller it resolves.
    @app.post(
        "/hit",
        dependencies=[
            Depends(require_auth),
            Depends(rate_limit(name="t-caller", limit=1, window="1m", key=by_caller)),
        ],
    )
    async def hit() -> dict[str, bool]:
        return {"ok": True}

    return app


class TestByCaller:
    async def test_limits_each_caller_on_their_own(self) -> None:
        first, second = bearer(), bearer()

        async with http_client(caller_limited_app()) as http:
            one = await http.post("/hit", headers=first)
            again = await http.post("/hit", headers=first)
            other = await http.post("/hit", headers=second)

        assert one.status_code == 200
        assert again.status_code == 429
        assert error_of(again).code == "rate_limited"
        assert again.headers["retry-after"] == "60"
        assert other.status_code == 200

    async def test_answers_401_before_it_counts_anything(self) -> None:
        async with http_client(caller_limited_app()) as http:
            first = await http.post("/hit")
            second = await http.post("/hit")

        assert (first.status_code, second.status_code) == (401, 401)
