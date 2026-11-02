# Backend

Python 3.14, FastAPI, Postgres through psycopg 3 and plain SQL migrations, with no ORM. How to run
the whole project is in the [root README](../README.md). The layer map and the rules every change
follows are in [`AGENTS.md`](AGENTS.md).

## One image, three processes

Each process has its own entry point and its own secrets, so a process holds only what it needs.

| Process | Start it with | Port | Holds |
| --- | --- | --- | --- |
| API, the agent loop and the tool gate | `uv run python -m app.main --reload` | 8000 | The Anthropic and Voyage keys, the signing secrets |
| `knowledge` MCP server | `uv run poe knowledge` | 8001 | The Voyage key and the database URL |
| GitHub gateway, optional | `uv run --env-file .env.github poe github-gateway` | 8002 | The GitHub token, and nothing else |

Each listens on loopback outside production. In production the container listens on every
interface, and Compose decides what is published.

## Commands

| Command | What it does |
| --- | --- |
| `uv sync` | Install from the lockfile |
| `uv run poe check` | Lint, layer rules, format, types and unit tests; needs no Docker and no keys |
| `uv run poe test` | Unit tests only |
| `uv run poe test-db` | The whole suite on the test database |
| `uv run poe migrate` | Apply the SQL migrations |
| `uv run poe contract` | Write `openapi.json` from the request schemas |
| `uv run poe format` | Rewrite the files |

The app reads its settings from the environment, once, in `src/app/config/env.py`, and never loads
an env file by itself. Every variable is listed in [`.env.example`](.env.example).

## Where things live

| Path | What it holds |
| --- | --- |
| `src/app/api/<module>/` | One domain: `routes` declares the gates, `controller` holds the rules, `schema` the wire shapes, `service` the queries |
| `src/app/models/` | An entity's types |
| `src/app/services/` | Shared capabilities: `anthropic`, `voyage`, `mcp`, `tool`, `chunk`, `github` |
| `src/app/middleware/` | Auth, roles, rate limits, security headers, logging, the error envelope |
| `src/app/infra/migrations/` | SQL migrations, in numbered order |
| `src/app/infra/subscribers/` | What runs after an event: a run, an index, a memory extraction |
| `src/app/infra/scripts/` | Commands a person runs: `grant_admin`, `accept_mcp_server`, `seed_eval_case` |
| `tests/` | Unit tests, `tests/db/` for the database suites, and the scripted fakes `fake_anthropic`, `fake_voyage` and `fake_github` |

## Changing the API

A change to an endpoint or a schema regenerates both sides of the contract, and both results are
committed:

```bash
uv run poe contract
cd ../frontend
bun run api:types
```

The `layers` rules in `pyproject.toml` run as part of `uv run poe lint`, so an import that crosses a
boundary fails the check.
