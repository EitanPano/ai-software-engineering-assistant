# AI Software Engineering Assistant

## Table of Contents

- [About](#about)
- [Features](#features)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Usage](#usage)
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

- Multiple MCP servers: our own `knowledge` server and GitHub's official server (planned)
- Knowledge sources: an admin connects a public GitHub repository, indexed by symbol and embedded
- Hybrid RAG: semantic and keyword search over connected GitHub repositories (planned)
- Agentic RAG: the agent decides when to retrieve more information (planned)
- Persistent agent memory: conversation history distinct from long-term knowledge (planned)
- Tool execution permissions: human approval for sensitive actions (planned)
- Streaming responses: intermediate tool activity shown as it happens
- Evaluation pipelines: retrieval quality and answer correctness measured (planned)
- Structured outputs: results validated against schemas (planned)

## Getting Started

### Prerequisites

- uv 0.12.23+
- bun 1.4+
- node 24+
- git
- Docker with Compose v2

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
# frontend
cd frontend
bun run dev
cd ..
```

Open http://localhost:5173 once the dev servers are up.

To run the whole stack with Docker Compose (the app is then at http://localhost:8000):

```bash
docker compose --profile app up --build
```

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

No license has been chosen yet.
