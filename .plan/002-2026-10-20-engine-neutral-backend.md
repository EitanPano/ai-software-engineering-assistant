# Engine-neutral backend template

Status: done (executed and validated 2026-10-20; uncommitted, awaiting Eitan's review)
Owner: Eitan
Last updated: 2026-10-20
Branch: `feat/fullstack-capability`
Stages: harness only (no role agents; the interactive session executed it)
Supersedes: the backend layout, database and logging parts of
`.plan/001-2026-10-20-fullstack-capability.md` (Tasks 3–5 and the matching Assumptions).
Revision: `.plan/003-2026-10-20-infra-layer.md` (2026-10-20) supersedes C1 (`server.ts`
listens; no `index.ts`) and C5 (bare `console` logging), and moves the `database` skill's
`backend/src/db/` paths to `backend/src/infra/db/`. Everything else here stands.

Revision: `.plan/004-2026-10-21-module-boundary.md` (2026-10-21) supersedes C3 (controllers
as Express handlers that validate and respond) and the cross-module half of C7 (a module
reaches another through its `service`): `controller.ts` is the module's public API,
`route.ts` is the HTTP adapter (middleware, validation, status), and modules cross only
through controllers.

Revision: `.plan/005-2026-10-21-backend-architecture.md` (2026-10-21) supersedes C2 (one
`api.use` line per module in `server.ts`: now one line per module in `config/routes.ts`), C6
(no auth stub ships: auth ships) and C12 (`lib/pagination.ts`: `lib/` is deleted, the helper is
`services/utils/pagination.ts`).

## Goal

Eitan's review of plan 001 (2026-10-20): the harness was "too specific with specific
stack templates"; no SQL-specific templates or code because the developer may pick a NoSQL
engine; modules hold `route`, `controller`, `service`, `schema` files under an `api/`
folder; `app.ts` is `server.ts` and mounts each module's route; `drizzle-orm` and `pino`
go. After this plan the harness scaffolds a backend that persists nothing, asks the
developer for the engine during the bootstrap, and keeps the engine specifics in one
skill instead of in the templates.

## Scope

- In: `templates/backend` (layout, dependencies, tests, lint zones), `templates/root`
  (compose without a database), `scripts/bootstrap.mjs` (next steps), `AGENTS.md`
  (Stack, Architecture, Naming, Definition of done, Skills), the `database` skill
  (replaces `database-schema`), the `api-design`, `writing-tests`, `error-handling`,
  `bootstrap-project`, `dev-loop`, `writing-plans`, `code-review` skills, the `backend`,
  `reviewer`, `qa`, `orchestrator` agents, `.doc/architecture.md`, `README.md`,
  `.claude/settings.json`, the backlog grammar.
- Out: the frontend template (unchanged except one comment), the hooks (unchanged; they
  already cover Postgres and MongoDB clients), the contract chain.

## Assumptions

Eitan's answers on 2026-10-20:

- A1 — The template ships no database; the bootstrap asks Postgres / MongoDB / decide
  later, records the answer in `.doc/architecture.md` (Data store), and the first backlog
  line is the data-layer task.
- A2 — The OpenAPI chain stays: zod → `backend/openapi.json` → `frontend/src/lib/api/schema.d.ts`
  with `openapi-fetch`.

Calls made while executing (reversible, listed for review):

- C1 — `server.ts` exports `app` and listens only under `import.meta.main`, so tests
  import the same file that runs; `index.ts` is gone.
- C2 — The `/api` prefix is mounted once: `const api = Router(); api.use('/health',
  healthRoute); app.use('/api', api)`. Each module adds one `api.use` line.
- C3 — Controllers are plain async Express 5 handlers; validation is an explicit
  `validate(schema, value, part)` call from `lib/validate.ts` (400 envelope naming the
  part). The `endpoint()` wrapper is gone; a `ZodError` that escapes anyway is still
  mapped to 400 by the error handler.
- C4 — Cross-cutting handlers live in `middleware/` (`request-id`, `request-log`,
  `not-found`, `error-handler`); `lib/http.ts` and `lib/log.ts` are gone.
- C5 — Logging is `console`: one line per request (silent under `bun test`), every 5xx
  with its stack. `LOG_LEVEL` is gone from `env.ts`.
- C6 — No auth stub ships (`auth.ts`, `lib/caller.ts` removed). The `api-design` skill
  says where `middleware/auth.ts` and `requireCaller()` go when the first protected
  endpoint lands.
- C7 — The data layer's file is `api/<name>/repository.ts` (plus `model.ts` for engines
  that define models in code); the lint zones already refuse it from controllers and
  routes, and refuse another module's `repository`/`model`.
- C8 — The `database` skill fixes the engine-neutral rules (one model source, repository
  per module, `app_test`, `describeDb`, migrations or indexes shipped with the change,
  destructive operations by humans) and has a Postgres and a MongoDB section; the
  data-layer task delivers the compose service, `db/client.ts`, `db/migrate.ts`,
  `tests/db.ts`, `test:db`.
- C9 — `docker-compose.yml` keeps both app images behind the `app` profile so the
  database service (added later, no profile) can be started alone with
  `docker compose up -d <service>`.
- C10 — The backlog grammar gains `stack:backend` (no frontend stage) for the data-layer
  task; `dev-loop`, `writing-plans` and the orchestrator honour it.
- C11 — Naming: SQL tables and columns snake_case; MongoDB collections singular with
  camelCase fields (so the service maps only `_id` and dates).
- C12 — `lib/pagination.ts` stays (engine-neutral cursor pagination); the `endpoint()`
  response stripping is replaced by typed service return values.

## Open Questions

None open. Eitan answered the two that changed the work (A1, A2).

## Steps

1. [x] `templates/backend`: delete `drizzle*`, `db/`, `module/`, `app.ts`, `index.ts`,
   `auth.ts`, `lib/{caller,http,log}.ts`, `bunfig.toml`, `tests/{db,db.test,http.test,setup}.ts`;
   write `server.ts`, `env.ts`, `openapi.ts`, `api/health/{schema,service,controller,route}.ts`,
   `middleware/*.ts`, `lib/validate.ts`, `lib/express.d.ts`; `package.json` without
   `drizzle-orm`, `drizzle-kit`, `pino`, `test:db`, `db:*`; `Dockerfile` runs `src/server.ts`;
   `eslint.config.mjs` zones for `route → controller → service → repository`.
2. [x] `templates/root`: compose without the `db` service; `db/init.sql` removed.
   `templates/frontend/playwright.config.ts` comment.
3. [x] `scripts/bootstrap.mjs`: no database in the next steps or the docker warning.
4. [x] `AGENTS.md`, `.doc/architecture.md` (Data store section), `README.md`,
   `.claude/settings.json` (`docker compose up -d *`), `.plan/000-backlog.md` grammar.
5. [x] Skills: `database` (new, replaces `database-schema`), `api-design` (worked `post`
   module in the new layout), `writing-tests`, `error-handling`, `bootstrap-project`
   (engine question, verify steps, first backlog lines), `dev-loop`, `writing-plans`
   and its template, `code-review`.
6. [x] Agents: `backend` (rewritten), `reviewer`, `qa`, `orchestrator` (edited).
7. [x] Validation below in a fresh scratch root.

## Validation

- V01 — `node scripts/bootstrap.mjs --root <scratch> --name demo` exits 0 — proof: run
  2026-10-20, `exit=0` in the bootstrap log. PASS
- V02 — `bun run check` in the scaffolded `backend/` is green — proof: typecheck, lint,
  format:check, `bun test` 15 pass / 0 fail across 4 files. PASS
- V03 — `bun run check` in the scaffolded `frontend/` is green — proof: `next typegen`,
  tsc, eslint, prettier, Vitest 7 pass. PASS
- V04 — The e2e journey reaches the API through both dev servers — proof:
  `bun run test:e2e` 1 passed (`home page reaches the API and has no serious
  accessibility violations`). PASS
- V05 — Every lint zone fires — proof: six mis-layered probe files produce 11 errors:
  schema→service, route→schema, route→service, controller→repository, service→route
  (two zones), service→server, lib→module, cross-module `../health/controller`
  (`no-restricted-imports`), `process.env` in a controller. PASS
- V06 — The `api-design` worked example compiles and lints in the scaffold — proof:
  blocks extracted from the skill into `src/api/post/` with a stub repository; `tsc
  --noEmit` exit 0, `eslint src/api/post` exit 0. PASS
- V07 — The compose file is valid and the backend image builds — proof: `docker compose
  --profile app config --services` lists backend, frontend; `build backend` exits 0
  (`Image demo-backend Built`). PASS
- V08 — No stale reference to Drizzle, pino, Postgres defaults, `app.ts`, `module/`,
  `endpoint()`, `database-schema` remains outside plan 001 and the `database` skill —
  proof: repository grep on 2026-10-20; the remaining hits are the engine-neutral terms
  (`repository.ts`, `test:db`, `describeDb`) defined by the `database` skill. PASS
- V09 — `.claude/settings.json` parses — proof: `JSON.parse` run 2026-10-20. PASS
- V10 — Templates match the Prettier output of the scaffold — proof: `diff -r` after
  the bootstrap's `bun run format` differs only in `__PROJECT_NAME__` substitutions
  (`eslint.config.mjs` re-synced). PASS
- V11 — The request log is silent under `bun test` — proof: no request lines in the
  V02 output (Bun sets `NODE_ENV=test`). PASS

## Risks

- The data-layer task is now the first real exercise of the `database` skill; its
  engine sections were written, not executed. Mitigation: the skill lists exactly what
  the task delivers, and the dev loop reviews it like any task. Running it once for
  Postgres and once for MongoDB in a scratch project is the next validation worth doing.
- A developer who picks an engine not in the skill (MySQL, SQLite, DynamoDB) gets only
  the engine-neutral rules. Mitigation: the skill says to add a section before the task.
- Without a database the health module is the only worked code; the `api-design`
  example carries the rest and is compiled in V06 so it cannot drift silently.

## Rollout Order

templates → bootstrap script → AGENTS.md → skills → agents → docs → validation.

## Rollback

Revert the working tree to the state of plan 001 (`git checkout` of the files is not
available to agents; a human discards the changes). No data or generated artifacts are
affected; the scratch scaffold under the session scratchpad can be deleted at any time.
