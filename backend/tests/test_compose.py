"""`docker-compose.yml` holds the GitHub gateway's boundary: the personal access token is named on
the gateway alone, `github-mcp` is pinned by digest and limited to the seven tools, and nothing of
the GitHub half starts without the `github` profile. The file is read as text (no YAML parser is a
dependency, and the checks are about which service names which variable)."""

import re
from pathlib import Path
from typing import Final

import pytest

from tests.fake_github_mcp import recorded_tools

COMPOSE: Final = Path(__file__).resolve().parents[2] / "docker-compose.yml"
SERVICE: Final = re.compile(r"^  ([a-z][a-z0-9-]*):\s*$")
DIGEST: Final = re.compile(r"^ghcr\.io/github/github-mcp-server@sha256:[0-9a-f]{64}$")


def blocks() -> dict[str, list[str]]:
    """Each service's lines, comments dropped, keyed by its name."""
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    inside = False
    for line in COMPOSE.read_text(encoding="utf-8").splitlines():
        if line.startswith("services:"):
            inside = True
            continue
        if inside and line and not line.startswith(" "):
            break
        match = SERVICE.match(line)
        if inside and match:
            current = found.setdefault(match.group(1), [])
        elif current is not None and not line.strip().startswith("#"):
            current.append(line)
    return found


def value(service: str, key: str) -> str:
    """The scalar after `key:` in the service's block (first match), unquoted."""
    for line in blocks()[service]:
        stripped = line.strip()
        if stripped.startswith(f"{key}:"):
            return stripped.split(":", 1)[1].strip().strip("\"'")
    raise AssertionError(f"{service} has no {key}")


def names(service: str) -> set[str]:
    return {line.strip().split(":", 1)[0] for line in blocks()[service] if ":" in line}


class TestPatBoundary:
    def test_the_pat_is_named_on_the_gateway_alone(self) -> None:
        holders = [name for name, lines in blocks().items() if "GITHUB_MCP_PAT" in "\n".join(lines)]

        assert holders == ["github-gateway"]

    def test_no_service_names_a_broad_token_variable(self) -> None:
        for name, lines in blocks().items():
            text = "\n".join(lines)
            assert "GITHUB_TOKEN" not in text, name
            assert "GITHUB_PERSONAL_ACCESS_TOKEN" not in text, name

    def test_the_upstream_is_sent_no_token_at_all(self) -> None:
        # It sees the PAT per request, from the gateway, and stores it nowhere.
        assert not {n for n in names("github-mcp") if "TOKEN" in n or "PAT" in n}

    def test_the_gateway_takes_the_pat_and_the_generated_token_and_nothing_secret_else(
        self,
    ) -> None:
        secrets = {n for n in names("github-gateway") if n.isupper() and n != "APP_ENV"}

        assert {"GITHUB_MCP_PAT", "GITHUB_MCP_TOKEN"} <= secrets
        assert not secrets & {
            "DATABASE_URL",
            "ANTHROPIC_API_KEY",
            "VOYAGE_API_KEY",
            "JWT_ACCESS_SECRET",
            "KNOWLEDGE_MCP_TOKEN",
        }

    @pytest.mark.parametrize("service", ["backend", "backend-migrate"])
    def test_the_api_and_its_migrate_command_know_the_gateway_but_not_the_pat(
        self, service: str
    ) -> None:
        assert value(service, "GITHUB_MCP_URL") == "http://github-gateway:8002/mcp"
        assert "GITHUB_MCP_TOKEN" in names(service)
        assert "GITHUB_MCP_PAT" not in names(service)


class TestGithubMcp:
    def test_is_pinned_by_digest_with_its_version_in_a_comment(self) -> None:
        assert DIGEST.match(value("github-mcp", "image"))
        assert "v2.0.3" in COMPOSE.read_text(encoding="utf-8")

    def test_serves_http_and_limits_the_tools_to_the_seven_with_lockdown_on(self) -> None:
        assert value("github-mcp", "command") == "http"
        tools = value("github-mcp", "GITHUB_TOOLS").split(",")
        assert sorted(tools) == sorted(tool.name for tool in recorded_tools())
        assert value("github-mcp", "GITHUB_LOCKDOWN_MODE") == "true"

    def test_publishes_on_loopback_only(self) -> None:
        ports = [line.strip() for line in blocks()["github-mcp"] if "8082" in line]

        assert ports
        assert all("127.0.0.1:8082:8082" in line for line in ports)

    @pytest.mark.parametrize("service", ["github-mcp", "github-gateway"])
    def test_starts_only_under_the_github_profile(self, service: str) -> None:
        assert re.search(r'profiles:\s*\[\s*"github"\s*\]', "\n".join(blocks()[service]))


class TestGateway:
    def test_is_the_backend_image_running_the_gateway_entry(self) -> None:
        assert value("github-gateway", "command") == "python -m app.github_gateway_main"
        assert value("github-gateway", "APP_PROCESS") == "github_gateway"
        assert "build" in names("github-gateway")

    def test_publishes_no_port(self) -> None:
        assert "ports" not in names("github-gateway")

    def test_forwards_to_github_mcp(self) -> None:
        assert value("github-gateway", "GITHUB_MCP_UPSTREAM_URL") == "http://github-mcp:8082/"

    def test_the_other_services_do_not_depend_on_it(self) -> None:
        # An outage of the GitHub half never stops the API: no `depends_on` entry names it.
        for service in ("backend", "backend-migrate", "knowledge"):
            assert not [
                line for line in blocks()[service] if re.match(r"^\s+github-[a-z]+:\s*$", line)
            ]
