"""The API's boundary is loopback, and DNS rebinding crosses a published port: after the rebind a
page is same-origin with the API, so CORS never applies. Its requests still name the attacker's
host, and that is what this middleware refuses."""

import pytest
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config.env import EnvError, load_env
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.trusted_host import TrustedHostMiddleware
from app.server import create_app
from tests.support import error_of, http_client


async def _answers_ok(scope: Scope, receive: Receive, send: Send) -> None:
    await PlainTextResponse("ok")(scope, receive, send)


def _guarded(*allowed: str) -> ASGIApp:
    return RequestIdMiddleware(TrustedHostMiddleware(_answers_ok, allowed=allowed))


class TestTheHostCheck:
    @pytest.mark.parametrize(
        "host",
        [
            "localhost",
            "localhost:5173",  # the Vite proxy keeps the page's `Host`
            "127.0.0.1",
            "127.0.0.1:8000",  # the Compose health check
            "[::1]",
            "[::1]:8000",
            "LOCALHOST:8000",
        ],
    )
    async def test_answers_on_a_loopback_name(self, host: str) -> None:
        async with http_client(create_app()) as http:
            res = await http.get("/api/health", headers={"host": host})

        assert res.status_code == 200

    @pytest.mark.parametrize(
        "host",
        [
            "evil.example",
            "evil.example:8000",
            "localhost.evil.example",
            "127.0.0.1.evil.example",
            "localhost@evil.example",
            "127.0.0.1:8000@evil.example",
            "[::1",
            "[::1].evil.example",
            "",
        ],
    )
    async def test_refuses_any_other_name(self, host: str) -> None:
        async with http_client(create_app()) as http:
            res = await http.get("/api/health", headers={"host": host})

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            # What a rebinding page calls first: it answers with a token in the body.
            ("POST", "/api/auth/register"),
            ("GET", "/openapi.json"),
            ("GET", "/"),
        ],
    )
    async def test_refuses_before_any_route_runs(self, method: str, path: str) -> None:
        async with http_client(create_app()) as http:
            res = await http.request(method, path, headers={"host": "evil.example:8000"})

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"

    async def test_a_refusal_keeps_the_request_id_and_the_security_headers(self) -> None:
        async with http_client(create_app()) as http:
            res = await http.get("/api/health", headers={"host": "evil.example"})

        assert res.headers["x-request-id"] != ""
        assert res.headers["x-content-type-options"] == "nosniff"

    async def test_refuses_two_host_lines_even_when_one_is_allowed(self) -> None:
        async with http_client(_guarded()) as http:
            res = await http.get("/", headers=[("host", "localhost"), ("host", "evil.example")])

        assert res.status_code == 400

    async def test_lets_a_scope_that_is_not_a_request_through(self) -> None:
        seen: list[str] = []

        async def inner(scope: Scope, receive: Receive, send: Send) -> None:
            seen.append(scope["type"])

        async def no_receive() -> Message:
            raise AssertionError

        async def no_send(message: Message) -> None:
            raise AssertionError

        await TrustedHostMiddleware(inner, allowed=())({"type": "lifespan"}, no_receive, no_send)

        assert seen == ["lifespan"]


class TestAllowedHosts:
    async def test_adds_names_and_keeps_the_loopback_ones(self) -> None:
        config = load_env({"ALLOWED_HOSTS": "Assistant.Example.com, other.example"}).env

        async with http_client(create_app(config=config)) as http:
            for host in ("assistant.example.com:443", "other.example", "127.0.0.1:8000"):
                assert (await http.get("/api/health", headers={"host": host})).status_code == 200
            refused = await http.get("/api/health", headers={"host": "evil.example"})

        assert refused.status_code == 400

    def test_is_empty_when_unset_or_blank(self) -> None:
        assert load_env({}).env.allowed_hosts == ()
        assert load_env({"ALLOWED_HOSTS": "  "}).env.allowed_hosts == ()

    def test_lower_cases_and_trims_the_names(self) -> None:
        env = load_env({"ALLOWED_HOSTS": " A.example ,, b.example,"}).env

        assert env.allowed_hosts == ("a.example", "b.example")

    @pytest.mark.parametrize(
        "value",
        [
            "https://a.example",
            "a.example:443",
            "a.example/path",
            "*",
            "*.a.example",
            "a.example, evil example",
        ],
    )
    def test_refuses_at_boot_what_is_not_a_host_name(self, value: str) -> None:
        with pytest.raises(EnvError, match="ALLOWED_HOSTS"):
            load_env({"ALLOWED_HOSTS": value})
