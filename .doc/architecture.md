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
| Stack | The packages and their templates | <!-- FILL: written by the bootstrap from .fullstack/catalog.yaml: stack id; per package its directory, template and version --> |
| Data store | System of record | <!-- FILL: the compose service and port of the engine chosen under Data Store --> |

<!-- FILL: add any other component (queue, object storage, email provider) or write "none". -->

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

<!-- FILL: describe any flow that differs from the above (webhooks, external callbacks). -->

## Data Store

The harness ships no database. A provider chosen at the bootstrap wires one; otherwise the
`database` skill lists the options and what the data-layer task delivers. No task may store data while a marker remains here.

- Engine: <!-- FILL: Postgres 17 | MongoDB 8 | decide later -->
- Client library: <!-- FILL: per the server package's AGENTS.md › Adding the data layer, or the provider chosen at the bootstrap -->
- Local service: <!-- FILL: the docker-compose.yml service name and the URL variable, written by the generator when a provider was chosen at the bootstrap, else by the data-layer task; the client and its Resource live under the server's `infra/`, bound through its db service -->
- Test database: `app_test` on the same service, reached only through the package's `testDb` command.

## Data Model

<!-- FILL: one line per entity: name (singular), owner entity if tenanted, key fields.
     Keep it in sync with the model files or schema the data-layer task created; the code
     wins on conflict. -->

## API

- Style: REST, JSON, singular resource paths under `/api/` (`api-design` skill).
- Contract: the OpenAPI document the server's `contract` command produces from
  its request schemas; the frontend's `contract` command regenerates its client types from
  it; both are committed.
- Versioning: <!-- FILL: none until v1 ships | /api/v1 prefix from day one -->

## Auth

<!-- auth-start -->
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
<!-- auth-end -->
<!-- noauth: - Auth: none. The product has no accounts and every endpoint is public. -->
<!-- noauth:   Adding accounts is a planned change; a scaffold with the `auth` flag on is the -->
<!-- noauth:   reference. -->
- Client model: <!-- FILL: written by the bootstrap per frontend kind. Server-rendered: the
  frontend's server is the backend's client (no browser fetch). SPA: the browser calls `/api` on
  the page's own origin, no CORS, `TRUST_PROXY` is the hop count in front of the server -->
<!-- auth-start -->
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
- <!-- FILL: the roles and scope rule beyond `user`/`admin`, or "every signed-in user is equal" -->
<!-- auth-end -->

## External Dependencies

None in the template. A vendor goes in `services/<vendor>` and is selected by
`MAIL_PROVIDER`, `SMS_PROVIDER` or `WHATSAPP_PROVIDER`.

<!-- FILL: third-party services the product adds, the file that wraps each, and the env
     variable that configures it. Or "none". -->

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
  `dependencies` when one is down. Nothing in the shipped compose file reads it; a
  `HEALTHCHECK` or a compose `healthcheck` that points at it is the data-layer task's or
  the deployment's to add.
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
  - Deploy mode: <!-- FILL: single | split. `single`: one image, the server serves the
    SPA's files; `split`: one image per package. Written by the bootstrap from
    `.fullstack/catalog.yaml` `deploy:`, or "n/a" when it has none (a stack with no frontend or
    no server). The `deployment` skill changes it; this line wins over provenance. -->
  - `TRUST_PROXY` hop count: local default <!-- FILL: written by the bootstrap: `false` in
    `single`, 1 in `split` -->; production <!-- FILL: the production value, decided with the
    host: 1 behind a PaaS edge, 2 behind a CDN and a load balancer -->
  - <!-- FILL: the production target (which host, how secrets are injected). -->
- Data migrations: <!-- FILL: who runs the server's `migrate` command in production and when, once the data layer exists; with a provider chosen at the bootstrap, answer it at the bootstrap -->

## Change Log

Date-stamped notes for architecture changes: new routes, auth boundaries, data-model
changes, external dependencies. Newest first.

- <!-- FILL: YYYY-MM-DD — initial architecture accepted -->
