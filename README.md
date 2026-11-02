# AI Software Engineering Assistant

An agent that answers questions about your codebase with file-and-line citations, remembers what
you tell it, and waits for your approval before it changes anything on GitHub.

It is built as a small agent platform rather than a chatbot: a hand-written agent loop, two MCP
servers, hybrid search, a permission gate enforced on the server, and evals that measure retrieval
quality. You bring your own Anthropic and Voyage AI keys; nothing is hosted for you.

| A typical chatbot | This project |
| --- | --- |
| Does not know your code | Indexes a GitHub repository by symbol, searches it by meaning and by keyword, and cites file and line |
| Forgets between chats | Keeps the facts you state, per person, on a screen where you can read and delete them |
| Cannot show how good it is | Scores retrieval with recall@k, MRR and nDCG in stored eval runs |
| Cannot be trusted to act | Checks every tool call on the server, and holds sensitive ones until a person approves the exact arguments |

## Table of Contents

- [How it works](#how-it-works)
- [Features](#features)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Run it locally](#run-it-locally)
  - [Run it in Docker](#run-it-in-docker)
- [Usage](#usage)
  - [Measuring retrieval](#measuring-retrieval)
  - [Acting on GitHub](#acting-on-github)
- [Security](#security)
  - [Hosting it publicly](#hosting-it-publicly)
- [Configuration](#configuration)
- [Running Tests](#running-tests)
- [Project layout](#project-layout)
- [Contributing](#contributing)
- [License](#license)

## How it works

```mermaid
flowchart LR
    person([You]) --> web["Web app<br/>React"]
    web -- "REST and SSE" --> api["API<br/>FastAPI, agent loop, tool gate"]
    api --> db[("Postgres<br/>with pgvector")]
    api -- "agent turns" --> claude["Anthropic API"]
    api -- "MCP" --> knowledge["knowledge server<br/>search, recall"]
    knowledge --> db
    knowledge -- "embed the query" --> voyage["Voyage AI"]
    api -- "embed code and memories" --> voyage
    api -- "read public repositories" --> github["GitHub"]
    api -. "MCP, optional" .-> gateway["GitHub gateway<br/>holds your token"]
    gateway -.-> ghmcp["GitHub's MCP server<br/>seven tools"]
    ghmcp -.-> github
```

What happens when you send a message:

1. Your message creates a **run**, which a background task executes outside the request.
2. The agent loop calls Claude and writes every step to Postgres as a `run_event`. The browser reads
   those over SSE, so a dropped stream reconnects and replays what it missed.
3. When Claude asks for a tool, the **tool gate** checks the tool's policy and pinned definition and
   validates the arguments before anything runs:
   - `allow`: the tool runs.
   - `ask`: the run parks in Postgres with no process waiting. You see the exact arguments, and your
     decision resumes the run, even after a restart.
   - `deny`, or no policy at all: Claude gets a denied result and carries on.
4. Claude searches again if a result did not answer, then replies, citing file and line.
5. After the run, a small side call reads your message and stores any lasting fact as a **memory**,
   which a later conversation can recall.

## Features

- **Multiple MCP servers:** our own `knowledge` server gives the agent its search and recall, and GitHub's official server, which you opt into, lets it read and act on GitHub; a third-party server's tools are pinned when an admin reads and accepts them on the MCP servers screen, a changed definition is denied until they accept it again, and an admin can turn a server off
- **Knowledge sources:** an admin connects a public GitHub repository, indexed by symbol and embedded
- **Hybrid RAG:** semantic and keyword search over connected GitHub repositories
- **Agentic RAG:** the agent decides when to search, searches again when a result does not answer, and cites file and line
- **Persistent agent memory:** the agent keeps durable facts you state, recalls them in a new conversation when it decides to, for you alone, and you read and delete them on the Memory screen; conversation history stays apart from long-term knowledge
- **Tool execution permissions:** an admin sets each tool to allow, ask or deny; a tool set to `ask` waits for a person to approve its exact arguments, across a restart, and writing an issue or a comment on GitHub can never be set to allow
- **Streaming responses:** intermediate tool activity shown as it happens
- **Evaluation pipelines:** an admin measures retrieval quality with an eval run; answer correctness (planned)
- **Structured outputs:** results validated against schemas (planned)

## Getting Started

### Prerequisites

| Tool | Version | Used for |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | 0.12.23+ | The backend; it installs Python 3.14 for you |
| [Bun](https://bun.sh/) | 1.4+ | The frontend |
| [Node](https://nodejs.org/) | 24+ | The repository's scripts |
| [Docker](https://docs.docker.com/get-docker/) with Compose | 2.35+ | The database, and the optional whole stack |
| git | any | |

You also need two API keys. The project is free and open source, but these two services are paid:

| Key | Needed for |
| --- | --- |
| `ANTHROPIC_API_KEY` | Chatting with the agent |
| `VOYAGE_API_KEY` | Connecting a repository, searching it and remembering facts |

Add a payment method to your Voyage account: its published rate limits start there, and its free
tokens still apply. Connecting a repository needs no GitHub key, because public repositories are
read anonymously. Without keys the app still starts in development, and every test suite runs on
scripted fakes.

Prompts and retrieved code go to Anthropic. Connected code, search text and the facts the agent
remembers go to Voyage to be embedded. Don't search for a secret or tell the agent one.

### Run it locally

**1. Install**

```bash
git clone <repository-url>
cd ai-software-engineering-assistant
cd backend
uv sync
cd ../frontend
bun install
cd ..
```

**2. Add your keys.** Create `backend/.env`, which git ignores, with the lines you need:

```bash
ANTHROPIC_API_KEY=<your key>
VOYAGE_API_KEY=<your key>
```

The app never loads this file by itself, which is why the commands below name it. You can export
the keys in your shell instead.

**3. Start the database and create its tables**

```bash
docker compose up -d database
cd backend
uv run poe migrate
cd ..
```

**4. Start the three processes,** each in its own terminal:

```bash
# Terminal 1: the API, on port 8000
cd backend
uv run --env-file .env python -m app.main --reload
```

```bash
# Terminal 2: the knowledge server, which gives the agent search and recall, on port 8001
cd backend
uv run --env-file .env poe knowledge
```

```bash
# Terminal 3: the web app, on port 5173
cd frontend
bun run dev
```

Start the `knowledge` server before your first conversation. A conversation keeps the tools it
started with, so one started before the server was ever reached has no search: start a new one.

**5. Create your account and make it an admin.** Sign up at <http://localhost:5173/sign-up>. There
is no admin screen for this step, by design: a person with shell access runs a command, which asks
for that account's password.

```bash
cd backend
uv run python -m app.infra.scripts.grant_admin you@example.com
cd ..
```

Sign in again, because the command ends the account's sessions. Then continue with
[Usage](#usage).

### Run it in Docker

The whole stack can run from one command. Compose runs it in production mode, which refuses
placeholder secrets, so generate them once into a file git ignores:

```bash
# Bash, or Git Bash on Windows. Put your two keys in place of the placeholders.
{
  for name in JWT_ACCESS_SECRET JWT_REFRESH_SECRET OTP_SECRET ENCRYPTION_KEY KNOWLEDGE_MCP_TOKEN; do
    echo "$name=$(openssl rand -base64 32)"
  done
  echo "DATABASE_URL=postgres://app:app@database:5432/app"
  echo "ANTHROPIC_API_KEY=<your key>"
  echo "VOYAGE_API_KEY=<your key>"
} > backend/.env.compose

docker compose --env-file backend/.env.compose --profile app up --build
```

Open <http://localhost:8000> and sign up. Use `localhost`, not an IP address: production mode marks
the auth cookies `Secure`, and browsers accept those over plain HTTP only on `localhost`. Then make
yourself an admin:

```bash
docker compose --env-file backend/.env.compose --profile app run --rm \
  backend-migrate python -m app.infra.scripts.grant_admin you@example.com
```

## Usage

| Screen | Who | What it is for |
| --- | --- | --- |
| Conversations, `/conversation` | Everyone | Chat with the agent, watch its tool calls, approve or reject the ones that wait for you |
| Search, `/search` | Everyone | Run the hybrid search yourself and see why each result matched |
| Memory, `/memory` | Everyone | Read and delete what the agent remembers about you |
| Sources, `/source` | Admin | Connect a public GitHub repository and watch it index |
| Eval runs, `/eval-run` | Admin | Measure retrieval quality and read past scores |
| MCP servers, `/mcp-server` | Admin | Turn servers on and off, accept tool definitions, set each tool to allow, ask or deny |

A good first session: connect a small repository under Sources, wait until it reads `ready`, then
ask the agent about that code in a new conversation.

### Measuring retrieval

An eval run scores the search against labelled questions and stores recall@k, MRR and nDCG. The
repository ships one set of cases, for the `pallets/click` repository at tag `8.5.0`. An eval run
calls Voyage, so it costs money. Connect that repository at that ref under Sources, load the cases
once, then start a run on the Eval runs screen:

```bash
cd backend
uv run python -m app.infra.scripts.seed_eval_case src/app/infra/eval_cases/click-8.5.0.json
cd ..
```

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
server's tools as an admin, on the MCP servers screen: it shows every tool whole and pins exactly
what you read. The `accept_mcp_server` command does the same from a shell, after your yes.

```bash
# GitHub's server, in Docker, with no token of its own
docker compose --profile github up -d github-mcp
cd backend
# the gateway, in its own terminal: the one process that holds your token
uv run --env-file .env.github poe github-gateway
# with the API running, accept on the screen; or from a shell:
uv run --env-file .env python -m app.infra.scripts.accept_mcp_server github
# optional and free: check the real server, with no model turn
uv run --env-file .env python -m tests.live_github
cd ..
```

With the whole stack in Compose, add the same file and accept through `backend-migrate`:

```bash
docker compose --env-file backend/.env.compose --env-file backend/.env.github \
  --profile app --profile github up --build
docker compose --env-file backend/.env.compose --env-file backend/.env.github \
  --profile app --profile github run --rm \
  backend-migrate python -m app.infra.scripts.accept_mcp_server github
```

Three things to expect:

- A conversation keeps the tools it started with, so start a new one after an accept. An older
  conversation never gets GitHub, and one started before a changed definition was accepted is
  denied that tool. The same holds for any server: a conversation started while it is off never
  gets its tools.
- If GitHub changes a tool's definition, for example after a new image, that tool is denied until
  you accept it again.
- Lockdown mode is on, because repository text can try to steer the agent. On a public repository,
  an issue or pull request by someone without push access reads as restricted, so most issues on
  other people's projects will not be readable. Files are not affected.

## Security

The agent reads text that anyone can write, such as repository files and GitHub issues, so the
design assumes the model can be steered and keeps every control outside it.

| Risk | What stands in the way |
| --- | --- |
| Text in a repository or a tool result tries to steer the agent | It stays in tool results, never reaches the system prompt, and cannot change a policy |
| The agent calls a tool it should not | `tool_policy` is enforced on the server before execution, and a tool with no policy is denied |
| The agent writes to GitHub on its own | Writing an issue or a comment can only be `ask` or `deny`, and an approval binds to the exact arguments you saw |
| A server changes a tool after you accepted it | Definitions are pinned, and a changed one is denied until it is accepted again |
| An answer carries data out through a link | Images never load by themselves, only web links work, and every link that leaves the app shows its real host in front of its words |
| A web page reaches the app on your machine | Every port is published on `127.0.0.1`, and the API refuses a `Host` that is not its own, which stops DNS rebinding |
| The GitHub token leaks | One process, the gateway, holds it, and the API refuses to boot with it |
| One person reads another's data | Conversations, runs, approvals and memories answer only to their owner, admins included |
| Connecting a repository reaches an internal host | A source must be `https://github.com/<owner>/<repo>`, and its files are parsed in a child process that holds no secrets |
| The agent runs code | No tool executes code |

Know the limits. A link's host removes the disguise but does not stop a click, so read it before
you follow a link in an answer. Agent runs spend your Anthropic key with no spend cap yet. The
bundled database uses `app` / `app` as a Postgres superuser. With GitHub on, every account acts with
your one token.

### Hosting it publicly

This stack is built to run on your own machine, and Compose publishes the app, the database and,
under the `github` profile, GitHub's server on port 8082 on `127.0.0.1` only. A public host is yours
to harden:

1. Set your own database password and connect with a non-superuser role.
2. Change the app's `ports` line in `docker-compose.yml`.
3. Set `ALLOWED_HOSTS` to your host name, or the API refuses every request that uses it.
4. Set `TRUST_PROXY` to your proxy hop count if a proxy sits in front of the app.
5. Put your own access control in front of it. Anyone who reaches the app can register, and there
   is no switch to close sign-up, so every visitor could spend your keys.
6. Leave the `github` profile off. Every account that can register acts with your one GitHub token,
   reads wherever it reaches with no approval, and approves its own writes.

## Configuration

Every variable is optional in local development except the keys you want to use. Compose's
production mode requires the secrets listed under [Run it in Docker](#run-it-in-docker).

<details>
<summary>All environment variables</summary>

<!-- configuration:start -->
| Variable | Description | Default |
| --- | --- | --- |
| `APP_ENV` | backend: development, test or production. | `development` |
| `PORT` | backend: Port the API listens on. | `8000` |
| `TRUST_PROXY` | backend: Proxy trust: true, false, a hop count (1 behind one reverse proxy), or a comma list of addresses, subnets and the presets loopback, linklocal and uniquelocal. | `false` |
| `CORS_ORIGINS` | backend: Comma-separated browser origins allowed by CORS. Leave unset to disable CORS (no browser calls the API from another origin). | — |
| `ALLOWED_HOSTS` | backend: Comma-separated host names the API answers to, besides localhost, 127.0.0.1 and [::1], which always work. Any other Host header is refused, which stops DNS rebinding. A public host must list its own name. | — |
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
| `LLM_SIDE_MODEL` | backend: The model of the side call that extracts memories after a run, without a date suffix. | `claude-haiku-5-5` |
| `ANTHROPIC_BASE_URL` | backend: Points the SDK at another server (the scripted fake in e2e). Leave unset; refused in production. | — |
| `VOYAGE_API_KEY` | backend: Voyage AI key for the code embeddings (voyage-code-4, paid per token). Required in production; a fake default applies elsewhere, and tests and e2e run on a scripted fake. | — |
| `VOYAGE_BASE_URL` | backend: Points the Voyage client at another server (the scripted fake in e2e). Leave unset; refused in production. | — |
| `GITHUB_BASE_URL` | backend: Points the GitHub client at another server (the scripted fake in e2e). Leave unset; refused in production. | — |
| `APP_PROCESS` | backend: Which process this is: backend (the API and its commands), knowledge (the MCP server that offers the agent its search and recall tools; it needs only DATABASE_URL, VOYAGE_API_KEY and KNOWLEDGE_MCP_TOKEN) or github_gateway (holds GITHUB_MCP_PAT; it needs only that, GITHUB_MCP_TOKEN and GITHUB_MCP_UPSTREAM_URL). Required in production; elsewhere it defaults to backend. | `backend` |
| `KNOWLEDGE_MCP_URL` | backend: Where the agent reaches the knowledge MCP server (`uv run poe knowledge`, port 8001). | `http://127.0.0.1:8001/mcp` |
| `KNOWLEDGE_MCP_TOKEN` | backend: Bearer token both sides share; the knowledge server refuses a call without it. Required in production, at least 32 characters; a fake default applies elsewhere. | — |
| `GITHUB_MCP_URL` | backend: Where the agent reaches the GitHub gateway (`uv run poe github-gateway`, port 8002). | `http://127.0.0.1:8002/mcp` |
| `GITHUB_MCP_TOKEN` | backend: Bearer token the backend and the gateway share; the gateway refuses a call without it. Optional: unset keeps the GitHub server unreachable. At least 32 characters; generate it, never reuse a PAT. | — |
| `GITHUB_MCP_UPSTREAM_URL` | backend: The GitHub gateway is its own process (APP_PROCESS=github_gateway). It alone reads the personal access token, GITHUB_MCP_PAT, which belongs in a git-ignored backend/.env.github loaded by the gateway's terminal only (any other process refuses to boot with it), never in this file or in backend/.env. Where the gateway forwards (the github-mcp service in Compose): | `http://127.0.0.1:8082/` |
| `DATABASE_URL` | backend: database/postgres provider Postgres connection URL. Required in production; outside production it defaults to the local service. Tests (testDb) use postgres://app:app@127.0.0.1:5432/app_test; override with TEST_DATABASE_URL. Browser tests (e2eDb) use postgres://app:app@127.0.0.1:5432/app_e2e; override with E2E_DATABASE_URL. | `postgres://app:app@127.0.0.1:5432/app` |
<!-- configuration:end -->

</details>

## Running Tests

No suite needs a key or the network: Anthropic, Voyage and GitHub are scripted fakes.

| Command | Where | What it runs | Needs |
| --- | --- | --- | --- |
| `uv run poe check` | `backend/` | Lint, layer rules, format, types, unit tests | Nothing |
| `uv run poe test-db` | `backend/` | The whole suite on the test database | The database |
| `bun run check` | `frontend/` | Types, lint, format, unit tests | Nothing |
| `bun run test:e2e` | `frontend/` | Playwright on a phone and a desktop, with an accessibility scan | The database, and ports 8000 and 5173 free |
| `node scripts/verify.mjs` | The root | All of the above, as CI does | The database, and those ports free |

## Project layout

```text
backend/                 One image, three processes: the API, the knowledge server, the GitHub gateway
  src/app/
    api/<module>/        One folder per domain: routes, controller, schema, service
    services/            Shared capabilities: Anthropic, Voyage, MCP, the tool gate, chunking
    infra/               Postgres, SQL migrations, event subscribers, admin scripts
    middleware/          Auth, rate limits, headers, logging, errors
  tests/                 Unit and database suites, and the scripted fakes
frontend/src/            React, with imports pointing down this list (lint enforces it)
  app/                   Routes
  widget/                Screen sections
  feature/               User actions
  entity/                Domain nouns
  shared/                UI kit, auth, and the API client generated from the OpenAPI contract
db/                      Postgres first-run script
.doc/                    Product definition, architecture, glossary, conventions
.plan/                   The backlog and one plan per task
.claude/                 The agents, skills and hooks that build this project
scripts/                 `verify` and README tooling
```

Where to start reading, all under `backend/src/app/`:

| To understand | Read |
| --- | --- |
| The agent loop | `api/agent/controller.py`, from `execute_run` |
| The tool gate and tool pinning | `services/tool.py` |
| How the agent reaches MCP servers | `services/mcp.py` |
| Approvals | `api/approval/controller.py` and `infra/subscribers/resume_run.py` |
| Our MCP server | `knowledge_main.py` |
| The process that holds the GitHub token | `github_gateway_main.py` |
| Hybrid search | `SEARCH_STATEMENT` in `api/source/service.py` |
| Code chunking | `services/chunk.py` and `services/parse_worker.py` |
| Memory | `infra/subscribers/extract_memory.py` and `api/memory/` |
| Evals | `api/eval/` |

Deeper reading:

| Document | What it holds |
| --- | --- |
| [`.doc/product-definition.md`](.doc/product-definition.md) | Scope and acceptance criteria |
| [`.doc/architecture.md`](.doc/architecture.md) | Data flow, data model and the change log |
| [`.doc/conventions.md`](.doc/conventions.md) | Technology choices and why, and the agent security rules |
| [`.doc/glossary.md`](.doc/glossary.md) | What each domain term means |
| [`backend/README.md`](backend/README.md), [`frontend/README.md`](frontend/README.md) | Working in each package |
| [`.plan/000-backlog.md`](.plan/000-backlog.md) | What is planned next |

## Contributing

How work moves through the dev loop is in [`.claude/README.md`](.claude/README.md). The
project's own agent rules are in [`.doc/conventions.md`](.doc/conventions.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
