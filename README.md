# AI Software Engineering Assistant

## Table of Contents

- [About](#about)
- [Features](#features)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Usage](#usage)
  - [Acting on GitHub](#acting-on-github)
- [Configuration](#configuration)
- [Running Tests](#running-tests)
- [Contributing](#contributing)
- [License](#license)

## About

An AI Software Engineering Assistant, built as a proper agent platform rather than a basic
chatbot. Admins connect GitHub repositories, engineers ask the agent about that code and get answers
cited to file and line. Anything the agent wants to change on GitHub needs their approval.

A typical AI chatbot does not know a team's codebase, forgets between chats, cannot show how
good its answers are and cannot be trusted to act. This one is built to do all four.

## Features

- Multiple MCP servers: our own `knowledge` server gives the agent its search, and GitHub's official server, which you opt into, lets it read and act on GitHub; a third-party server's tools are pinned when an admin accepts them, and a changed definition is denied
- Knowledge sources: an admin connects a public GitHub repository, indexed by symbol and embedded
- Hybrid RAG: semantic and keyword search over connected GitHub repositories
- Agentic RAG: the agent decides when to search, searches again when a result does not answer, and cites file and line
- Persistent agent memory: conversation history distinct from long-term knowledge (planned)
- Tool execution permissions: a tool set to `ask` waits for a person to approve its exact arguments, across a restart, and writing an issue or a comment on GitHub is such a tool
- Streaming responses: intermediate tool activity shown as it happens
- Evaluation pipelines: an admin measures retrieval quality with an eval run; answer correctness (planned)
- Structured outputs: results validated against schemas (planned)

## Getting Started

### Prerequisites

- uv 0.12.23+
- bun 1.4+
- node 24+
- git
- Docker with Compose v2

### API keys

The project is free and open source, but two features call paid APIs, so you bring your own keys.
They stay in your environment.

| Key | Needed for |
| --- | --- |
| `VOYAGE_API_KEY` | Connecting a repository and searching it |
| `ANTHROPIC_API_KEY` | Chatting with the agent |

Add a payment method to your Voyage account: its published rate limits start there, and its free
tokens still apply. Connected code and search text go to Voyage to be embedded, so don't search for
a secret. Connecting a repository needs no GitHub key, because public repositories are read
anonymously; only the optional [Acting on GitHub](#acting-on-github) takes a token. Without keys the
app still starts in development, and the test suites run on scripted fakes.

Set them in your shell, or for local development keep them in `backend/.env`, which git ignores:

```bash
cd backend
# .env holds only the lines you need, for example VOYAGE_API_KEY=...
uv run --env-file .env python -m app.main
```

The app never loads that file by itself, so use this command when you want your keys. The agent's
search runs in the `knowledge` server, which needs `VOYAGE_API_KEY` too, so start it the same way:
`uv run --env-file .env poe knowledge`.

### Installation

```bash
git clone <repository-url>
cd ai-software-engineering-assistant
# backend
cd backend
uv sync
cd ..
# frontend
cd frontend
bun install
cd ..
```

## Usage

```bash
# Run each of these in its own terminal.
# backend
cd backend
uv run python -m app.main --reload
cd ..
# knowledge server: the agent's search tool
cd backend
uv run poe knowledge
cd ..
# frontend
cd frontend
bun run dev
cd ..
```

Open http://localhost:5173 once the dev servers are up.

Start the `knowledge` server before your first conversation. A conversation keeps the tools it
started with, so one started before the server was ever reached has no search: start a new one.

To run the whole stack with Docker Compose (the app is then at http://localhost:8000):

```bash
docker compose --profile app up --build
```

This stack is built to run on your own machine. Compose publishes the app, the database and, under
the `github` profile, GitHub's server on port 8082 on `127.0.0.1` only, the bundled database uses
`app` / `app` as a Postgres superuser, and agent runs
spend your Anthropic key with no spend cap yet. To host it publicly, set your own database password,
connect with a non-superuser role, change the app's `ports` line in `docker-compose.yml`, and set
`TRUST_PROXY` to your proxy hop count if a proxy sits in front of it. Leave the `github` profile off
on a public host: every account that can register acts with your one GitHub token, reads wherever
it reaches with no approval, and approves its own writes.

### Acting on GitHub

This is optional. Without it the agent searches the knowledge base and nothing else changes. With
it, the agent uses GitHub's own MCP server: a read runs at once, and writing an issue or a comment
waits for your approval.

Create a fine-grained personal access token limited to the repositories you name, with Contents and
Pull requests read and Issues read and write. Keep it in `backend/.env.github`, which git ignores
and only the gateway loads. Never put it in `backend/.env`: the API refuses to boot with it.

```bash
# backend/.env.github
GITHUB_MCP_PAT=<your token>
GITHUB_MCP_TOKEN=<a random string of at least 32 characters>
```

Add the same `GITHUB_MCP_TOKEN` to `backend/.env`, then start the two GitHub services and accept the
server's tools. The accept prints every tool whole and stores what you read after your yes.

```bash
# GitHub's server, in Docker, with no token of its own
docker compose --profile github up -d github-mcp
cd backend
# the gateway, in its own terminal: the one process that holds your token
uv run --env-file .env.github poe github-gateway
# once, in another terminal
uv run poe migrate
uv run --env-file .env python -m app.infra.scripts.accept_mcp_server github
# optional and free: check the real server, with no model turn
uv run --env-file .env python -m tests.live_github
cd ..
```

With the whole stack in Compose, pass the same file and accept through `backend-migrate`:

```bash
docker compose --env-file backend/.env.github --profile app --profile github up --build
docker compose --env-file backend/.env.github --profile app --profile github run --rm \
  backend-migrate python -m app.infra.scripts.accept_mcp_server github
```

Three things to expect:

- A conversation keeps the tools it started with, so start a new one after an accept. An older
  conversation never gets GitHub, and one started before a changed definition was accepted is
  denied that tool.
- If GitHub changes a tool's definition, for example after a new image, that tool is denied until
  you accept it again.
- Lockdown mode is on, because repository text can try to steer the agent. On a public repository,
  an issue or pull request by someone without push access reads as restricted, so most issues on
  other people's projects will not be readable. Files are not affected.

## Configuration

<!-- configuration:start -->
| Variable | Description | Default |
| --- | --- | --- |
| `APP_ENV` | backend: development, test or production. | `development` |
| `PORT` | backend: Port the API listens on. | `8000` |
| `TRUST_PROXY` | backend: Proxy trust: true, false, a hop count (1 behind one reverse proxy), or a comma list of addresses, subnets and the presets loopback, linklocal and uniquelocal. | `false` |
| `CORS_ORIGINS` | backend: Comma-separated browser origins allowed by CORS. Leave unset to disable CORS (no browser calls the API from another origin). | — |
| `STATIC_DIR` | backend: Directory of a built single-page app to serve after the API (the single image sets it). Unset serves none. | — |
| `JWT_ACCESS_SECRET` | backend: Signs access tokens. Required in production, at least 32 characters; a fake default applies elsewhere. | — |
| `JWT_REFRESH_SECRET` | backend: Signs refresh tokens. Required in production, at least 32 characters, different from the access secret. | — |
| `OTP_SECRET` | backend: Keys the one-time-code hash. Required in production, at least 32 characters. | — |
| `ENCRYPTION_KEY` | backend: Base64 of 32 random bytes, encrypts stored secrets. Required in production. | — |
| `COOKIE_DOMAIN` | backend: Cookie domain for auth cookies. Optional; unset keeps them host-only. | — |
| `MAIL_PROVIDER` | backend: Mail provider: console (prints in development) or a registered provider name. | `console` |
| `SMS_PROVIDER` | backend: SMS provider: console or a registered provider name. | `console` |
| `WHATSAPP_PROVIDER` | backend: WhatsApp provider: console or a registered provider name. | `console` |
| `MAIL_FROM` | backend: Sender address. Required when MAIL_PROVIDER is not console. | `no-reply@example.com` |
| `JOBS_ENABLED` | backend: Run the scheduled jobs in this process: true or false. | `true` |
| `RATE_LIMIT_SCALE` | backend: Multiplies every rate limit (1 to 1000). Production keeps 1; an e2e run raises it so a journey suite is not limited. There is no switch that turns limiting off. | `1` |
| `ANTHROPIC_API_KEY` | backend: Anthropic API key for the agent. Required in production; a fake default applies elsewhere, and tests and e2e run on a scripted fake. | — |
| `LLM_MODEL` | backend: The model the agent runs on, without a date suffix. | `claude-opus-5-5` |
| `ANTHROPIC_BASE_URL` | backend: Points the SDK at another server (the scripted fake in e2e). Leave unset; refused in production. | — |
| `VOYAGE_API_KEY` | backend: Voyage AI key for the code embeddings (voyage-code-4, paid per token). Required in production; a fake default applies elsewhere, and tests and e2e run on a scripted fake. | — |
| `VOYAGE_BASE_URL` | backend: Points the Voyage client at another server (the scripted fake in e2e). Leave unset; refused in production. | — |
| `GITHUB_BASE_URL` | backend: Points the GitHub client at another server (the scripted fake in e2e). Leave unset; refused in production. | — |
| `APP_PROCESS` | backend: Which process this is: backend (the API and its commands), knowledge (the MCP server that offers the agent its search tool; it needs only DATABASE_URL, VOYAGE_API_KEY and KNOWLEDGE_MCP_TOKEN) or github_gateway (holds GITHUB_MCP_PAT; it needs only that, GITHUB_MCP_TOKEN and GITHUB_MCP_UPSTREAM_URL). Required in production; elsewhere it defaults to backend. | `backend` |
| `KNOWLEDGE_MCP_URL` | backend: Where the agent reaches the knowledge MCP server (`uv run poe knowledge`, port 8001). | `http://127.0.0.1:8001/mcp` |
| `KNOWLEDGE_MCP_TOKEN` | backend: Bearer token both sides share; the knowledge server refuses a call without it. Required in production, at least 32 characters; a fake default applies elsewhere. | — |
| `GITHUB_MCP_URL` | backend: Where the agent reaches the GitHub gateway (`uv run poe github-gateway`, port 8002). | `http://127.0.0.1:8002/mcp` |
| `GITHUB_MCP_TOKEN` | backend: Bearer token the backend and the gateway share; the gateway refuses a call without it. Optional: unset keeps the GitHub server unreachable. At least 32 characters; generate it, never reuse a PAT. | — |
| `GITHUB_MCP_UPSTREAM_URL` | backend: The GitHub gateway is its own process (APP_PROCESS=github_gateway). It alone reads the personal access token, GITHUB_MCP_PAT, which belongs in a git-ignored backend/.env.github loaded by the gateway's terminal only (any other process refuses to boot with it), never in this file or in backend/.env. Where the gateway forwards (the github-mcp service in Compose): | `http://127.0.0.1:8082/` |
| `DATABASE_URL` | backend: database/postgres provider Postgres connection URL. Required in production; outside production it defaults to the local service. Tests (testDb) use postgres://app:app@127.0.0.1:5432/app_test; override with TEST_DATABASE_URL. Browser tests (e2eDb) use postgres://app:app@127.0.0.1:5432/app_e2e; override with E2E_DATABASE_URL. | `postgres://app:app@127.0.0.1:5432/app` |
<!-- configuration:end -->

## Running Tests

```bash
# backend
cd backend
uv run poe check
uv run poe test
cd ..
# frontend
cd frontend
bun run check
bun run test
bun run test:e2e
cd ..
```

## Contributing

How work moves through the dev loop is in [`.claude/README.md`](.claude/README.md). The
project's own agent rules are in [`.doc/conventions.md`](.doc/conventions.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
