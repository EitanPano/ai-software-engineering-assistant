"""The only module that reads `os.environ`.

Parsed once at import; a missing or malformed variable stops the process with a message naming it.
A fresh clone runs with no environment at all: every variable has a development default or is
optional, except the secrets in production, which must be supplied (outside production they fall
back to a plainly fake default and `defaulted_secrets` names them so the entry can warn). A
variable the product adds (a provider key) is declared here and in the example env file.

No `.env` loading and no pydantic-settings: secrets never live in a file in the working tree, and
`BaseSettings` would merge `os.environ` into an explicit mapping, JSON-decode list fields and match
names case-insensitively.
"""

import base64
import binascii
import ipaddress
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
)

type TrustProxy = bool | int | str
type Network = ipaddress.IPv4Network | ipaddress.IPv6Network

_TRUST_PRESETS: Final = {
    "loopback": ("127.0.0.0/8", "::1/128"),
    "linklocal": ("169.254.0.0/16", "fe80::/10"),
    "uniquelocal": ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"),
}


class EnvError(ValueError):
    """The environment is unusable; the message names each variable and what is wrong."""


_SECRET_NAMES: Final = (
    "JWT_ACCESS_SECRET",
    "JWT_REFRESH_SECRET",
    "OTP_SECRET",
    "ENCRYPTION_KEY",
    "DATABASE_URL",
    "ANTHROPIC_API_KEY",
    "VOYAGE_API_KEY",
    "KNOWLEDGE_MCP_TOKEN",
)

# The `knowledge` process (`APP_PROCESS=knowledge`) needs these and no other secret: it signs
# nothing and calls no model, so the rest get a random value at each boot and nothing signed there
# verifies anywhere.
_KNOWLEDGE_SECRET_NAMES: Final = ("DATABASE_URL", "VOYAGE_API_KEY", "KNOWLEDGE_MCP_TOKEN")

# The GitHub gateway (`APP_PROCESS=github_gateway`) holds a write credential, so it needs these two
# in every environment, with no development default, and no secret of the API. Any other process
# that is handed the personal access token refuses to boot: `load_env` leaves `os.environ`
# untouched, so a token in the API's environment would stay there, and dropping it silently would
# hide that.
_GATEWAY_SECRET_NAMES: Final = ("GITHUB_MCP_PAT", "GITHUB_MCP_TOKEN")
# What GitHub's tokens start with: classic, fine-grained, OAuth, user-to-server, server-to-server.
_PAT_PREFIXES: Final = ("ghp_", "github_pat_", "gho_", "ghu_", "ghs_")

_DEVELOPMENT_DEFAULTS: Final = {
    # Not a real key and not shaped like one: development and every test run on the scripted fake.
    "ANTHROPIC_API_KEY": "dev-only-anthropic-key-not-real",
    "VOYAGE_API_KEY": "dev-only-voyage-key-not-real",
    "JWT_ACCESS_SECRET": "dev-only-access-secret-change-me-0123456789",
    "JWT_REFRESH_SECRET": "dev-only-refresh-secret-change-me-012345678",
    "OTP_SECRET": "dev-only-otp-secret-change-me-0123456789abc",
    # 32 bytes, base64.
    "ENCRYPTION_KEY": "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    # The provider's local service. The URL carries the password, so it is a secret.
    "DATABASE_URL": "postgres://app:app@127.0.0.1:5432/app",
    "KNOWLEDGE_MCP_TOKEN": "dev-only-knowledge-mcp-token-not-real-0123456789",
}

# Docker Compose passes an unset `${VAR}` as an empty string; blank means unset.
_BLANK_IS_UNSET: Final = (
    "CORS_ORIGINS",
    "COOKIE_DOMAIN",
    "MAIL_FROM",
    "STATIC_DIR",
    "TRUST_PROXY",
    "ANTHROPIC_BASE_URL",
    "VOYAGE_BASE_URL",
    "GITHUB_BASE_URL",
    "APP_PROCESS",
    "KNOWLEDGE_MCP_URL",
    "GITHUB_MCP_URL",
    "GITHUB_MCP_TOKEN",
    "GITHUB_MCP_PAT",
    "GITHUB_MCP_UPSTREAM_URL",
)

_MIN_SECRET_LENGTH: Final = 32
type Secret = Annotated[str, Field(min_length=_MIN_SECRET_LENGTH)]
type CookieDomain = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_DEFAULT_MAIL_FROM: Final = "no-reply@example.com"


def trusted_networks(entries: str) -> tuple[Network, ...]:
    """The networks a comma list of addresses, subnets and presets names (`loopback`, `linklocal`,
    `uniquelocal`). Pure, so the environment can refuse a bad list at import and the proxy
    middleware can compile the same list; a bad entry is a ValueError naming it.
    """
    networks: list[Network] = []
    for entry in entries.split(","):
        text = entry.strip()
        try:
            # A bare address is a one-address network; a netmask (`10.0.0.0/255.0.0.0`) works too.
            networks.extend(
                ipaddress.ip_network(part, strict=False)
                for part in _TRUST_PRESETS.get(text, (text,))
            )
        except ValueError:
            raise ValueError(
                f"entry {entry!r} is not an address, a subnet or one of {', '.join(_TRUST_PRESETS)}"
            ) from None
    return tuple(networks)


def _check_trust_proxy(value: TrustProxy) -> TrustProxy:
    if isinstance(value, str):
        trusted_networks(value)
    return value


def _check_encryption_key(value: str) -> str:
    try:
        decoded = base64.b64decode(value, validate=True)
    except binascii.Error:
        decoded = b""
    if len(decoded) != 32:
        raise ValueError("must be base64 that decodes to 32 bytes")
    return value


def _check_database_url(value: str) -> str:
    # The message never carries the value: the URL holds the password.
    if not value.startswith(("postgres://", "postgresql://")):
        raise ValueError("must be a postgres:// or postgresql:// URL")
    return value


def _parse_trust_proxy(value: object) -> object:
    # A boolean, a hop count or an address list, the three forms a proxy setting takes. The
    # digits are ASCII only: `str.isdigit` accepts Unicode digits.
    if value == "true":
        return True
    if value == "false":
        return False
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return value


def _split_origins(value: object) -> object:
    if isinstance(value, str):
        return tuple(origin.strip() for origin in value.split(",") if origin.strip() != "")
    return value


def _resolve_dir(value: Path | None) -> Path | None:
    return None if value is None else value.resolve()


def _parse_boolean_text(value: object) -> object:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("must be true or false")


class Env(BaseModel):
    """The parsed environment. Field `port` reads variable `PORT`, and so on."""

    model_config = ConfigDict(
        alias_generator=str.upper,
        validate_by_alias=True,
        validate_by_name=False,
        extra="ignore",
        frozen=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    # Which process this is: the API (and its migrate and grant-admin commands), the `knowledge`
    # MCP server or the GitHub gateway. Required in production, so a service started without it
    # fails at boot.
    app_process: Literal["backend", "knowledge", "github_gateway"] = "backend"
    port: Annotated[int, Field(gt=0, le=65535)] = 8000
    trust_proxy: Annotated[
        TrustProxy, BeforeValidator(_parse_trust_proxy), AfterValidator(_check_trust_proxy)
    ] = False
    cors_origins: Annotated[tuple[str, ...] | None, BeforeValidator(_split_origins)] = None
    # The built SPA to serve, resolved once to an absolute path; blank is unset and serves none.
    static_dir: Annotated[Path | None, AfterValidator(_resolve_dir)] = None
    jwt_access_secret: Secret
    jwt_refresh_secret: Secret
    otp_secret: Secret
    encryption_key: Annotated[str, AfterValidator(_check_encryption_key)]
    database_url: Annotated[str, AfterValidator(_check_database_url)]
    cookie_domain: CookieDomain | None = None
    mail_provider: Annotated[str, Field(min_length=1)] = "console"
    sms_provider: Annotated[str, Field(min_length=1)] = "console"
    whatsapp_provider: Annotated[str, Field(min_length=1)] = "console"
    mail_from: Annotated[str, Field(min_length=1)] = _DEFAULT_MAIL_FROM
    jobs_enabled: Annotated[bool, BeforeValidator(_parse_boolean_text)] = True
    # Multiplies every limit in RATE_LIMITS (middleware/rate_limit.py). An e2e run sets it so a
    # journey suite is not limited; production keeps 1. At most 1000, so no value is a bypass.
    rate_limit_scale: Annotated[float, Field(ge=1, le=1000, allow_inf_nan=False)] = 1
    anthropic_api_key: Annotated[str, Field(min_length=1)]
    # No date suffix (`.doc/conventions.md`, Claude API).
    llm_model: Annotated[str, Field(min_length=1)] = "claude-opus-5-5"
    # The model of a side call (memory extraction): a job beside the agent, on the person's own key.
    # A side call never sends `fallbacks`, so a model without them is fine.
    llm_side_model: Annotated[str, Field(min_length=1)] = "claude-haiku-5-5"
    # Points the SDK at another server: the scripted fake in tests and e2e. Refused in production.
    anthropic_base_url: Annotated[str, Field(min_length=1)] | None = None
    # Embeds the code chunks (`services/voyage.py`); paid per token.
    voyage_api_key: Annotated[str, Field(min_length=1)]
    # Point the Voyage and GitHub clients at the scripted fakes in tests and e2e. Refused in
    # production.
    voyage_base_url: Annotated[str, Field(min_length=1)] | None = None
    github_base_url: Annotated[str, Field(min_length=1)] | None = None
    # Where the API reaches the `knowledge` server, and the bearer token both sides share. The
    # token is a secret: the server compares it in constant time.
    knowledge_mcp_url: Annotated[str, Field(min_length=1)] = "http://127.0.0.1:8001/mcp"
    knowledge_mcp_token: Secret
    # Where the API reaches the GitHub gateway, and the bearer token both sides share. Optional:
    # an install with no GitHub token leaves it unset and the `github` server is never accepted.
    github_mcp_url: Annotated[str, Field(min_length=1)] = "http://127.0.0.1:8002/mcp"
    github_mcp_token: Secret | None = None
    # Only the gateway process holds these: the personal access token, and the address of
    # `github-mcp-server` it forwards to (which sees the token per request and stores it nowhere).
    github_mcp_pat: Secret | None = None
    github_mcp_upstream_url: Annotated[str, Field(min_length=1)] = "http://127.0.0.1:8082/"


@dataclass(frozen=True)
class LoadedEnv:
    env: Env
    defaulted_secrets: list[str]


def _random_secrets() -> dict[str, str]:
    """A value for every secret the `knowledge` process does not use, new at each boot."""
    return {
        "JWT_ACCESS_SECRET": secrets.token_urlsafe(48),
        "JWT_REFRESH_SECRET": secrets.token_urlsafe(48),
        "OTP_SECRET": secrets.token_urlsafe(48),
        "ENCRYPTION_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
        "ANTHROPIC_API_KEY": secrets.token_urlsafe(48),
    }


def _gateway_unused() -> dict[str, str]:
    """A value for every secret the GitHub gateway does not use, new at each boot: it holds no model
    key, no store and no signing secret, whatever its shell exported."""
    return _random_secrets() | {
        "VOYAGE_API_KEY": secrets.token_urlsafe(48),
        "KNOWLEDGE_MCP_TOKEN": secrets.token_urlsafe(48),
        # Never connected: the gateway has no store.
        "DATABASE_URL": "postgres://unused:unused@127.0.0.1:1/unused",
    }


def _placeholder_problems(source: Mapping[str, str], names: tuple[str, ...]) -> list[str]:
    """A copied example file or the development default must not reach production: the secrets
    would be public. Only the name is reported, never the value."""
    problems: list[str] = []
    for name in names:
        value = source.get(name, "")
        if value == "":
            continue
        # "<" opens the README's `<a random string ...>` placeholder.
        if value.startswith(("change-me", "dev-only-", "<")) or value == _DEVELOPMENT_DEFAULTS.get(
            name
        ):
            problems.append(f"{name}: is a placeholder, set a real secret")
    access = source.get("JWT_ACCESS_SECRET", "")
    if "JWT_ACCESS_SECRET" in names and access != "" and access == source.get("JWT_REFRESH_SECRET"):
        problems.append("JWT_REFRESH_SECRET: must differ from JWT_ACCESS_SECRET")
    return problems


def _issue_messages(error: ValidationError) -> list[str]:
    messages: list[str] = []
    for issue in error.errors(include_url=False, include_input=False, include_context=False):
        name = ".".join(str(part) for part in issue["loc"])
        messages.append(f"{name}: {issue['msg'].removeprefix('Value error, ')}")
    return messages


def load_env(source: Mapping[str, str]) -> LoadedEnv:
    """Parse `source`; an explicit mapping, so tests never read the real environment."""
    production = source.get("APP_ENV") == "production"
    defaulted: list[str] = []
    values = {
        name: value
        for name, value in source.items()
        if not (name in _BLANK_IS_UNSET and value.strip() == "")
    }
    process = values.get("APP_PROCESS", "backend")
    gateway = process == "github_gateway"
    if "GITHUB_MCP_PAT" in values and not gateway:
        # Named, never its value. It would stay in this process's environment, which is the API's.
        raise EnvError(
            "invalid environment: GITHUB_MCP_PAT: is only for the GitHub gateway "
            "(APP_PROCESS=github_gateway); keep it out of this process's environment"
        )
    knowledge = production and process == "knowledge"
    if not production and not gateway:
        for name in _SECRET_NAMES:
            if source.get(name, "") == "":
                values[name] = _DEVELOPMENT_DEFAULTS[name]
                defaulted.append(name)
    if knowledge:
        # Never the model key this process was handed by mistake: it holds none.
        values |= _random_secrets()
    if gateway:
        absent = [f"{name}: Field required" for name in _GATEWAY_SECRET_NAMES if name not in values]
        if absent:
            raise EnvError(f"invalid environment: {'; '.join(absent)}")
        # A write credential sits here, so a copied example value is refused in every environment,
        # and the personal access token is never also the shared bearer token.
        problems = _placeholder_problems(source, _GATEWAY_SECRET_NAMES)
        if values["GITHUB_MCP_PAT"] == values["GITHUB_MCP_TOKEN"]:
            problems.append("GITHUB_MCP_TOKEN: must differ from GITHUB_MCP_PAT")
        if problems:
            raise EnvError(f"invalid environment: {'; '.join(problems)}")
        values |= _gateway_unused()
    if values.get("GITHUB_MCP_TOKEN", "").startswith(_PAT_PREFIXES):
        # The bearer token is shared with the API and so sits in its environment; a personal access
        # token there would be past the boundary. Only the name is reported.
        raise EnvError(
            "invalid environment: GITHUB_MCP_TOKEN: looks like a GitHub token; "
            "generate a random string instead"
        )

    if production and not gateway:  # the gateway's names were checked above
        names = _KNOWLEDGE_SECRET_NAMES if knowledge else (*_SECRET_NAMES, "GITHUB_MCP_TOKEN")
        problems = _placeholder_problems(source, names)
        if problems:
            raise EnvError(f"invalid environment: {'; '.join(problems)}")
    missing_process = ["APP_PROCESS: is required in production"] if production else []
    if "APP_PROCESS" in values:
        missing_process = []

    try:
        parsed = Env.model_validate(values)
    except ValidationError as error:
        raise EnvError(
            f"invalid environment: {'; '.join([*_issue_messages(error), *missing_process])}"
        ) from None
    if missing_process:
        raise EnvError(f"invalid environment: {missing_process[0]}")
    if parsed.mail_provider != "console" and "MAIL_FROM" not in values:
        raise EnvError(
            "invalid environment: MAIL_FROM: is required when MAIL_PROVIDER is not console"
        )
    if production and parsed.anthropic_base_url:
        raise EnvError("invalid environment: ANTHROPIC_BASE_URL: is not allowed in production")
    if production and parsed.voyage_base_url:
        raise EnvError("invalid environment: VOYAGE_BASE_URL: is not allowed in production")
    if production and parsed.github_base_url:
        raise EnvError("invalid environment: GITHUB_BASE_URL: is not allowed in production")
    if production and parsed.static_dir and not (parsed.static_dir / "index.html").is_file():
        raise EnvError(f"invalid environment: STATIC_DIR: {parsed.static_dir} has no index.html")
    return LoadedEnv(env=parsed, defaulted_secrets=defaulted)


_loaded: Final = load_env(os.environ)
env: Final = _loaded.env
defaulted_secrets: Final = _loaded.defaulted_secrets
