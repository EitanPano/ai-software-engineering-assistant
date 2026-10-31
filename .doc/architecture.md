# System Architecture

The harness fixes the shape: the packages of the stack chosen at the bootstrap (recorded in
`.fullstack/catalog.yaml`) and a contract generated from the server's request schemas
(`AGENTS.md` Stack and Architecture; each package's `AGENTS.md` for its layer map). The
database is this product's choice. This document records what is specific to this product,
and the auth model a product starts from.
Fill every `<!-- FILL: … -->` marker before the first plan that touches the section.

## Primary Components

| Component | Responsibility | Runs as |
| --- | --- | --- |
| `frontend/` | Pages and routes. Server-rendered (Next): its server calls the API. Single-page app (React): static files, the browser calls `/api` on its own origin | Server-rendered: the frontend's container. SPA: the server's container (`single`) or the frontend's static-server container (`split`). Ports: `.fullstack/catalog.yaml` |
| `backend/` | HTTP API, validation, business rules, persistence; serves the SPA's files in `single` | The server's container; port in `.fullstack/catalog.yaml` |
| Stack | The packages and their templates | `react-python-fastapi`: `backend/` from `server/python-fastapi` 1.2.1, `frontend/` from `frontend/react` 2.1.1. A single-page app, because no public page needs search or sharing |
| Data store | System of record | Compose service `database`, port 5432 on loopback |
| `knowledge` MCP server | Our own MCP server: search and read over the knowledge base, on Streamable HTTP | Its own Compose service, from the `backend/` image with a different command |
| GitHub MCP server | GitHub's official MCP server: the agent's GitHub tools, write tools behind approval | Its own Compose service |

## Data Flow

1. A browser request reaches a route in the frontend's routing layer.
2. The page calls its feature's data layer (`server/` in a server-rendered frontend, `api/`
   in a single-page app), which calls the API through the typed API client.
3. The module's router declares the endpoint's gates and names the handler; validation is
   declared once, from the module's request schema (a `validate` middleware in Express, the
   handler's typed parameters in FastAPI; see `backend/AGENTS.md › Adding a module`). The
   controller's handler reads the validated input, applies the rules, reads and writes
   through the module's service (and, across a module boundary, another module's
   controller), publishes events and sends the response in the schema's shape; failures
   leave as the error envelope.
4. Mutations go through the same data layer (the frontend's actions) and refresh the
   affected route.
5. Events: a controller publishes through the server's event service; a subscriber in
   `infra/subscribers/` reacts and may call controllers.
6. Jobs: files in `infra/jobs/`, run by the scheduler; set `JOBS_ENABLED` on one
   replica only.
7. Agent run: a message creates a `run`, which an in-process background task executes outside
   the request, on a hand-written loop over the `anthropic` SDK. Run state lives in Postgres.
   Assistant content blocks are stored unchanged and history is append-only, as the API
   requires of thinking blocks.
8. Streaming: the loop writes every step as a `run_event`; the SSE endpoint reads them, so a
   client reconnects and replays from the last event it saw. A stream polls `run_event` and ends
   cleanly after 60 s, and the client reopens it with `Last-Event-ID`. One replica only until a
   queue replaces the background task; a crash fails the turn in progress, the next boot's sweep
   ends that lost run as `interrupted`, and pending approvals survive.
9. Tools: the backend is the MCP client, never Anthropic's MCP connector, whose tool calls run
   on Anthropic's side where the approval gate cannot intercept them. `tool_policy` decides each
   call: allow, ask or deny. A tool with no policy is denied.
10. Approval: an `ask` call stops the run at `awaiting_approval`, with no process waiting. The
    decision resumes the run from Postgres, so an approval may take hours and survive a restart.
11. Retrieval: hybrid search fuses `pgvector`, full-text and trigram results with reciprocal rank
    fusion (RRF), over the chunks of `ready` sources only. A signed-in person searches at
    `/search`; the agent reaches it only through the `knowledge` MCP server and decides when to
    search again.
12. Memory: `message` rows are one conversation's history. `memory` rows are per-user long-term
    knowledge, extracted after a conversation and retrieved by the agent; the user can list and
    delete them.
13. Eval run: an admin's click stores a `queued` `eval_run`, and a bus reaction executes it beside
    the request, one at a time, through `search_knowledge_base`, the rule the route's limit does
    not reach. A case runs only against a `ready` source at its pinned commit. Scores are stored per
    search and per case, with the corpus and settings, never a hit's content; the next boot's sweep
    ends a lost run as `interrupted`, and nothing restarts one, because a run spends money.

Repository content is untrusted input and prompt injection can steer tool calls, so tool results
never widen permissions and approval is the control on every write. No tool executes code in v1.

## Data Store

The harness ships no database. A provider chosen at the bootstrap wires one; otherwise the
`database` skill lists the options and what the data-layer task delivers. No task may store data while a marker remains here.

- Engine: Postgres 18 with `pgvector` (`pgvector/pgvector:0.8.7-pg18`, pinned by digest in
  `docker-compose.yml`), so one store holds relational rows, JSONB, full-text indexes and vectors.
  Postgres 18's image keeps its data in `/var/lib/postgresql/18/docker` and declares the volume
  one level up, so the named volume `database-pg18` mounts at `/var/lib/postgresql`. A 17 volume
  cannot be reused: `database-data` is left as it was, and removing it is a human's job.
- Keyword search: built-in full-text search and `pg_trgm`, fused with vector results by RRF.
  `ts_rank` has no IDF, so the retrieval evals decide whether a BM25 extension is worth its custom
  image.
- Client library: psycopg 3 async pool (`infra/postgres.py`) and SQL migrations, no ORM.
- Local service: `database` in `docker-compose.yml`, reached through `DATABASE_URL`; the client
  and its Resource live in `infra/postgres.py`, bound through `services/db.py`.
- Test database: `app_test` on the same service, reached only through the package's `testDb` command.

## Data Model

Planned; each task's migration creates its tables and the code wins on conflict. `user` and
`session` ship with the template.

- `conversation`: owner `user`; title.
- `message`: `conversation`, `run`; position, role (`user`, `assistant`, `tool_result`), content
  blocks (JSONB), text.
- `run`: `conversation`, owner `user`; status, error code. No model or token usage yet.
- `run_event`: `run`; sequence number, type, payload (JSONB).
- `tool_call`: `run`; `mcp_server`, tool name, arguments, result, status.
- `approval`: `tool_call`; decision, deciding `user`, reason.
- `tool_policy`: `mcp_server`, tool name; effect (allow, ask, deny).
- `mcp_server`: name, URL, enabled.
- `source`: repository URL, ref, status, error code, indexed commit, counts.
- `document`: `source`; path, language.
- `chunk`: `document`; symbol, line range, content, embedding, and the stored `keyword` that
  full-text search reads.
- `memory`: owner `user`; content, embedding, originating `conversation`.
- `eval_case`: pinned commit, kind, question, expected chunks; the correctness task adds the
  expected answer.
- `eval_run`: status, error code, counts, scores, per-case results, cosine evidence, corpus and
  settings.

## API

- Style: REST, JSON, singular resource paths under `/api/` (`api-design` skill).
- Contract: the OpenAPI document the server's `contract` command produces from
  its request schemas; the frontend's `contract` command regenerates its client types from
  it; both are committed.
- Versioning: none until v1 ships.

## Auth

- Default a product starts from (shipped, change by plan): JWT access token, 15 min,
  stateless. Refresh JWT stored hashed in a session, rotated on use, sliding 30 d with a
  90 d cap, and a replayed token revokes all the caller's sessions. A replay inside the 30 s
  grace window is a concurrent retry and converges: it receives the same token the first
  rotation issued (kept sealed as the session's `graceToken`), and no sibling token is
  minted. OTP by email or phone; an OTP login verifies its target, and a target verified for
  the first time revokes the user's other sessions. A password set before verification stays
  (password reset is the product's remedy; mandatory verification at register is a product
  decision). The access token is stateless: a blocked user or a demoted admin keeps access
  for up to 15 minutes, and a thief's access token lives until expiry after a revoke-all;
  where immediacy matters, read the status or role from the store or shorten
  `ACCESS_TOKEN_TTL`. Roles `user` and `admin`. Tokens travel in the body and in
  cookies; a bearer header wins over the cookie. The access token stays valid until it
  expires, even after logout, and its role claim is trusted: the stated tradeoff of a
  stateless token.
- Client model: single-page app. The browser calls `/api` on the page's own origin (the server
  in `single`), so there is no CORS and no API URL in the bundle. Rate limits key on the client
  address, so `TRUST_PROXY` is the hop count in front of the server (`false` in `single` locally).
- A rate-limiter key is `rl:<name>:<sha256(subject)>`, so no address or target sits in the
  store in clear. A refresh with neither cookie nor body token answers 400.
- OTP: 6 digits, 10 minutes, 5 attempts, single use; attempts are counted before the code
  is compared. Purpose `login` works only for an existing active account and answers 202
  for an unknown target, with delivery detached, so the OTP endpoints do not disclose
  accounts. Purpose `verify` needs a caller and only the caller's own target. Two
  disclosures are accepted: register's 409 tells that an email exists (limited per IP), and
  `PATCH /api/user/me`'s 409 tells that a phone is verified by another account
  (authenticated callers only). A phone claim conflicts only with a verified holder.
- Where authentication is enforced: the route gate is declarative and fails fast. The auth
  gate resolves the caller when a route declares it, and the role gate rejects anonymous or
  unauthorised calls before any handler runs (the names are in the server package's
  `AGENTS.md › Authentication`). The handler resolves the caller and passes it to the
  controller's rules, which decide authority (who may touch which record); the service
  never does.
- Roles and scope: `user` and `admin` as shipped. Conversations, memories and their approvals
  are read and written by the owning user only. Any signed-in user may search the knowledge
  base. Sources, MCP servers, tool policy and eval runs are `admin` only.

## External Dependencies

None in the template. A vendor goes in `services/<vendor>` and is selected by
`MAIL_PROVIDER`, `SMS_PROVIDER` or `WHATSAPP_PROVIDER`.

| Service | Wrapped in | Configured by |
| --- | --- | --- |
| Anthropic API (`claude-opus-5-5`; the agent, memory extraction and the eval judge) | `services/anthropic` | `ANTHROPIC_API_KEY`, `LLM_MODEL`; `ANTHROPIC_BASE_URL` points tests at the fake and is refused in production |
| Voyage AI embeddings (`voyage-code-4`) | `services/voyage` | `VOYAGE_API_KEY`; `VOYAGE_BASE_URL` for the fake, refused in production |
| GitHub's public REST API, anonymous, 60 requests an hour per server address | `services/github` | `GITHUB_BASE_URL` for the fake, refused in production |
| GitHub MCP server | the MCP client, as an `mcp_server` row | `GITHUB_TOKEN`, held by its Compose service |

Tests and the e2e suite use a scripted fake for Anthropic, Voyage and GitHub, so `check` needs no
key; only eval runs exercise the real model.

## Operational Concerns

- Logs: through the server's logger (with redaction), one line per request on stdout
  (the request logger) with `requestId`, method, path (without the query string),
  status and duration; every unexpected error with its stack under the same id. Headers,
  bodies and secrets are never logged.
- Health: `GET /api/health` is the liveness check and never depends on a store.
  `GET /api/health/ready` pings every dependency in the dependency registry
  (`memory`, `pubsub` and `scheduler` in the template, plus the database resource when a
  provider was chosen at the bootstrap; one ping round in flight at a
  time, the answer reused for a second) and answers 503 with the per-dependency map under
  `dependencies` when one is down. The `backend` Compose service's `healthcheck` reads it, so
  `docker compose --profile app up --wait` returns only once the server answers.
- Startup and shutdown: the server's entry file calls `connectAll` (bounded retry)
  before it listens (a dependency that never comes up stops the process with exit code 1);
  on `SIGTERM` or `SIGINT` it stops accepting requests, runs `disconnectAll` in reverse
  order and exits 0, or exits 1 after 10 s if draining hangs.
- Errors: the envelope and status table in the `error-handling` skill.
- Replicas: the template runs as exactly one instance until the data-layer and cache tasks
  (rate limits, the cache and the bus, and sessions when the product has accounts, live in
  one process); after them `JOBS_ENABLED` must be true on exactly one replica.
- Deployment: images run as a non-root user; `docker compose --profile app up --build`
  runs the stack locally.
  - Deploy mode: `single`: one image, the server serves the SPA's files. The `deployment` skill
    changes it; this line wins over provenance.
  - `TRUST_PROXY` hop count: local default `false`; production <!-- FILL: the production value, decided with the
    host: 1 behind a PaaS edge, 2 behind a CDN and a load balancer -->
  - <!-- FILL: the production target (which host, how secrets are injected). -->
- Data migrations: the `backend-migrate` one-shot Compose service runs `migrate` on every deploy,
  and the server starts only after it exits 0.

## Change Log

Date-stamped notes for architecture changes: new routes, auth boundaries, data-model
changes, external dependencies. Newest first.

- 2026-10-31: retrieval evals. Routes `POST` and `GET /api/eval-run` and `GET /api/eval-run/{id}`,
  admin only, and tables `eval_case` and `eval_run` (`0008-eval.sql`). A partial unique index allows
  one active run, and a second start is a 409. A run calls `search_knowledge_base` directly, so
  `search_per_user` does not reach it; the admin role and the one active run bound it, and it has
  no rate limit or spend cap of its own yet. `SearchHitRecord.cosine` is internal: the
  `GET /api/search` wire and every ranking are unchanged. Cases are seeded by
  `infra/scripts/seed_eval_case.py`, from `infra/eval_cases/`.
- 2026-10-31: search limit. `GET /api/search` takes `RATE_LIMITS.search_per_user`, 5 a minute per
  user, after `require_auth`, and answers 429 `rate_limited` before any call to Voyage and before
  any pooled connection. It bounds one account: total spend and the pool across accounts stay open,
  and a call to `search_knowledge_base` that is not this route is not limited. `/search` gains its
  own error boundary for the wait.
- 2026-10-31: search. Route `GET /api/search`, any signed-in account, and the screen `/search`.
  `0006-hybrid-search.sql` adds `pg_trgm`, the stored `chunk.keyword` and the GIN and HNSW indexes,
  and `0007-analyze-search-tables.sql` analyzes the three tables once. An index refreshes their
  statistics when a source turns `ready`, because a table as small as `source` may never reach
  autovacuum's threshold, and the planner then reads every chunk. A search has a 3 s statement
  limit and answers 503 past it, so it holds a pooled connection for 3 s at most. Search text now
  goes to Voyage AI.
- 2026-10-31: sources. Routes `POST` and `GET /api/source` and `POST /api/source/{id}/indexing`,
  admin only, and the screens `/source` and `/source/connect`. Tables `source`, `document` and
  `chunk` (`0005-source.sql`). An index is a bus reaction that reads a public repository's tarball
  without extracting it, and a boot sweep ends what a lost process left. Voyage and GitHub's public
  API are new external dependencies. `tree-sitter` runs only in a child process with no secrets
  and a deadline, because a parse holds the GIL and takes about quadratic time on crafted input.
- 2026-10-30: the `database` service moves to Postgres 18 with `pgvector` on a new volume, and
  `0004-vector-extension.sql` enables `vector`. `grant_admin`, a shell command, makes the first
  admin: it takes the account's password and ends its sessions, because `register` takes any
  address and a verified email proves the mailbox, not the password.
- 2026-10-30: the template's reference module leaves the product. Routes `GET` and
  `POST /api/module`, `GET`, `PATCH` and `DELETE /api/module/{id}` and the table `module` are
  removed (`0003-drop-module.sql`, forward-only); nothing called them. `api/conversation/` is now
  the module to copy.
- 2026-10-30: conversations and agent runs. Routes `POST` and `GET /api/conversation`,
  `GET /api/conversation/{id}`, `GET` and `POST /api/conversation/{id}/message` and the SSE stream
  `GET /api/run/{id}/event`; all owner only, another user's record is a 404. Tables `conversation`,
  `message`, `run` and `run_event` (`0002-conversation.sql`). Limits per user, per 15 min: 30 sends,
  60 stream opens. The Anthropic API is a new external dependency; the real model is offered no
  tools until the task that adds the `knowledge` MCP server. The loop's tool path denies anything
  unregistered.
- 2026-10-30: the `backend` Compose service gains a healthcheck on `/api/health/ready`; CI runs
  `verify`, a production-image start and a secret scan on every push.
- 2026-10-30: initial architecture accepted; react-python-fastapi, deploy single, Postgres 17.
