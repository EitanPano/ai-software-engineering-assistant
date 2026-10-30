# The first capability: Postgres for bun-express, catalog v1.0.0

Status: done
Status set by the session on Eitan's delegation; Eitan confirms.
Owner: Eitan
Last updated: 2026-10-23
Approval: Eitan's instruction on 2026-10-22, "start working on milestone 3 plan … if there is
anything to do before working on it, do it automatically … completed after … a PR is opened on
both this repo and the templates repo to a dev branch". Open questions are resolved by their
recommended answers; the session records any deviation in the ledger
(`.superpowers/sdd/008-2026-10-22-postgres-capability/progress.md`, git-ignored).
Branch: `feat/postgres-capability` in both repositories, cut from `dev`
Base: harness `4dc84b4`, catalog `304a78a` (`dev` = `main` at the time the branches were cut;
both `dev` branches were created from `main` as this plan's prerequisite)
Stages: harness and catalog only (no role agents; the interactive session executes it with
Sonnet implementers per task, a Sonnet review per task and one Opus final review per
repository), ending in one pull request per repository into `dev`

## Goal

Milestone 3 of ADR 0001 (`fullstack-templates/docs/adr/0001-catalog-architecture.md`, D3 and
Delivery order item 3). After this plan the catalog ships its first capability: the
`database/postgres` provider and the `bun-express` overlay that binds it.
`bun tools/generate.ts --stack next-bun-express --capability database=postgres` writes a project
whose backend stores modules, users and sessions in Postgres through Bun's built-in `SQL`
client. That project ships migrations, a `migrate` command and a `testDb` command against a
separate `app_test` database, a `database` Compose service with a healthcheck and `db/init.sql`.
Its `.fullstack/catalog.yaml` records `testDb` and `migrate`. Its `check` still needs no
Docker. CI generates the `postgres`, `auth-off-postgres` and `stack-postgres` cases, starts the
provider with Compose, and runs `check`, `migrate`, `testDb` and e2e. Projects generated without a
capability keep the in-memory store and the harness's data-layer task, so both paths stay valid
(ADR Anti-goals). The harness's bootstrap skill, agents and skills then work with a provider
chosen at the bootstrap. `testDb` and `migrate` resolve from the provenance file first. A
bootstrapped Postgres project passes every gate with the database up. The catalog is ready to
tag `v1.0.0` once Eitan merges it; the harness lock bump follows that tag.

## Scope

- In, catalog side (`fullstack-templates`, branch `feat/postgres-capability`, PR into `dev`):
  - Schemas `schemas/provider.schema.json` and `schemas/capability.schema.json`; the
    provenance schema's `providers` map typed.
  - Tools: loading providers and overlays with cross-checks, capability routing in the plan,
    capability selections for markers, `.sql` marker syntax, the overlay step of the
    pipeline, script and command merging, provider Compose and env assembly, provider files,
    provenance, the validate dry-run over capability options, case coverage for capabilities,
    `test-generated --with-services`. Unit tests for each with the fixture catalog.
  - `shared/providers/database/postgres/` (manifest, Compose fragment, `db/init.sql`).
  - `server/bun-express`: the test seam `tests/store.ts` and `@database` markers in `base/`;
    `capabilities/database/postgres/` (manifest and overlay tree); `template.yaml` lists
    `postgres`; cases `postgres`, `auth-off-postgres`, `stack-postgres`; version `2.1.0`;
    `AGENTS.md` sections for the wired engine.
  - CI: `--with-services` in both workflows that run cases; `push` also on `dev`.
  - Docs: `docs/capabilities.md` (shipped), `CONTRIBUTING.md` (adding a provider and an
    overlay), `README.md` (status, a database example, the generated matrix), ADR amendments
    (`v1.0.0`), template `CHANGELOG.md`.
- In, harness side (this repository, branch `feat/postgres-capability`, PR into `dev`):
  - `AGENTS.md` (Repository layout row, Stack command table): `testDb` and `migrate` come from
    `.fullstack/catalog.yaml` when a provider was chosen at the bootstrap, else from the
    package's `AGENTS.md › Adding the data layer`.
  - `.claude/agents/backend.md`, `.claude/agents/qa.md`, `.claude/skills/dev-loop/SKILL.md`,
    `.claude/skills/writing-tests/SKILL.md`: the same resolution rule.
  - `.claude/skills/bootstrap-project/SKILL.md`: verification with a provider (start the
    service, `migrate`, `check`, `testDb`, e2e); the "fresh server package" paragraph for
    both paths; the Data store row filled from the provider.
  - `.claude/skills/database/SKILL.md`: a wired provider is the data-layer task already done;
    the test-database rule matches the overlay (store-backed suites skip outside `testDb`).
  - `.doc/architecture.md`: the Data store hints name the provider path.
  - `scripts/bootstrap.mjs`: next steps name the provider service, `migrate` and `testDb`
    when a capability was passed.
  - `README.md`: the capability flag in the bootstrap example.
  - This plan.
- Out:
  - Tagging `v1.0.0` and bumping `catalog.lock`. A tag needs Eitan's explicit yes
    (`.claude/rules/git-workflow.md`), and it belongs on `main` after `dev` merges. The lock
    bump is then a one-line harness PR with a fresh-cache V20.
  - MongoDB, cache (redis) and messaging providers (after v1, ADR Delivery order).
  - Updating an existing project to a newer template version (ADR non-goal).
  - Moving `services/cache.ts` off the memory store: the cache stays in process memory in
    the Postgres variant until the cache task.
  - A seed script and an admin bootstrap (the user controller's `setUserRole` is the hook).
  - A CI workflow for the harness repository (it has none).

## Assumptions

- ADR 0001 is accepted with its v0.1.0 and v0.1.1 amendments; D3 is the design this plan
  builds. It reopens nothing and records each "left to the builder" call as an amendment.
- Catalog `main` (`304a78a`, `v0.1.1`) is green on CI. The harness pins it (`catalog.lock`).
  Both `dev` branches start equal to `main`.
- `server/bun-express/base/AGENTS.md › Adding the data layer` is the specification of the
  overlay: `infra/<engine>.ts` as a `Resource`, `services/db.ts` rewritten, every module's
  `service.ts` and `services/session.ts` rewritten with their signatures kept,
  `infra/scripts/migrate.ts` and `db:migrate`, `DATABASE_URL`, a test database and `test:db`,
  and the auth assumptions (conditional rotation, unique email, phone unique among verified
  phones). Where this plan corrects that text (the executor argument, where the test-database
  preload lives), the overlay's `AGENTS.md` blocks carry the correction.
- Bun 1.4's built-in `SQL` (`import { SQL } from 'bun'`) is the client: no new package
  (ADR D3), so `bun.lock` does not change. `bun test --path-ignore-patterns` and `--preload`
  exist in Bun 1.4.0 (checked: `bun test --help`). Bun SQL's exact API (lazy connect, `begin`,
  `unsafe`, identifier helper, error classes and codes) is checked against
  `node_modules/bun-types/sql.d.ts` and a live database before it is relied on.
- `memory` stays in `dependencies` in the Postgres variant: `services/cache.ts`, rate limits
  and OTP keys still use it (ADR; base `AGENTS.md`).
- Docker Desktop is available on the author's machine; GitHub's `ubuntu-latest` runners have
  Docker and Compose v2, so the service cases run on Compose rather than service containers
  (the "left to the builder" CI choice).
- The user's rules hold: implementers and task reviewers on Sonnet, the final review on Opus;
  Conventional Commits; commits, pushes and the two PRs are authorised by the instruction
  above; no tag, no merge, no force-push.

## Open Questions

1. Where do migration files live: `src/infra/migrations/` or `migrations/` at the package root?
   Recommended: `src/infra/migrations/NNNN-<topic>.sql`. The Dockerfile already copies `src`, so
   `bun run db:migrate` works inside the image without a Dockerfile change, and the layer map
   keeps "what runs on a live connection" under `infra/`.
2. How do the store-backed tests stay Docker-free in `check`: move them to `tests/db/` in the
   overlay (copies of the base tests), or keep one file per module and let a test seam skip it
   outside `testDb`? Recommended: the seam (decision M3-12). One test file per module in every
   variant, and no 1,700-line copy of the base tests that drifts. `check` reports those suites
   as skipped and `testDb` runs them. A conditional skip in a seam is the pattern the base
   `AGENTS.md` already names (`describeDb`); it is not a `.skip` in the diff.
3. When is `v1.0.0` tagged? Recommended: after `dev` merges into `main`, by Eitan, on the merge
   commit. Then a harness PR bumps `catalog.lock` with a fresh-cache V20. `dev` stays bootstrappable
   meanwhile because the harness changes work with both `v0.1.1` (no providers listed: the
   skill offers "decide later" only) and `v1.0.0`.
4. One more CI job for the whole stack on Postgres (`stack-postgres`)? Recommended: yes. It is the
   path the harness bootstrap takes, and it proves the frontend's e2e boots a backend that
   connects to Postgres.
5. Id column type: `uuid` or `text`? Recommended: `text`. Ids are strings the controller
   generates (ADR "Shape of every record"). A `uuid` column turns a lookup of a malformed id
   (`send-welcome`'s `'missing'`) into a 500 instead of a not-found.
6. Is `DATABASE_URL` a secret (required in production, defaulted with a boot warning elsewhere)?
   Recommended: yes. It carries credentials, and the env module already has exactly that
   treatment for secrets.

## Steps

### Decisions (the "left to the builder" calls, recorded as ADR amendments)

- **M3-1 Overlay layout.** `<template>/capabilities/<kind>/<provider>/capability.yaml` beside an
  `overlay/` tree that mirrors `base/` (D1 said "capability.yaml + the overlay files"; a
  separate tree keeps the manifest out of the package).
- **M3-2 Capability manifest** (`schemas/capability.schema.json`):
  ```yaml
  schemaVersion: 1
  kind: database                       # matches the directory
  provider: postgres                   # matches the directory; a provider of that kind
  summary: Postgres through Bun's built-in SQL client, migrations and a test database
  dependencies: { add: { … }, remove: [ … ] }   # optional; through the template's adapter
  scripts: { db:migrate: …, test:db: … }        # optional; npm adapter: package.json scripts
  commands: { testDb: bun run test:db, migrate: bun run db:migrate }   # optional
  ```
  A script or command name the base already defines is a validation error, not an override.
- **M3-3 Provider manifest** (`schemas/provider.schema.json`): the ADR's shape plus `service`
  (the Compose service the provider adds and packages depend on) and a one-line `summary` per
  env entry:
  ```yaml
  schemaVersion: 1
  kind: database
  id: postgres
  name: PostgreSQL 17
  service: database
  compose: compose.yaml                # a partial Compose document: services.<service>, volumes
  env:
    - name: DATABASE_URL
      summary: Postgres connection URL. Required in production; defaults to the local service elsewhere.
      local: postgres://app:app@localhost:5432/app
      compose: postgres://app:app@database:5432/app
      test: postgres://app:app@localhost:5432/app_test
  files: [db/init.sql]                 # copied to the project root when absent
  ```
- **M3-4 Pipeline per package.** Copy `base/`, then copy each selected overlay's `overlay/`
  over it (same path replaces), then apply flags: `onlyPaths` removal, which also drops overlay
  files at those paths (an overlay file that exists only with a flag lives under one of that
  flag's `onlyPaths` or uses markers). Then the marker pass, the leftover sweep, the flags'
  dependency removals, the capabilities' dependency additions and scripts, and placeholders.
- **M3-5 Selections.** For every capability kind a template declares, `<kind>` is true when a
  provider is selected; for every provider it lists, `<kind>:<provider>` is true when that one is
  selected. `@database`, `@nodatabase`, `@database:postgres`, `@nodatabase:postgres` and their
  `-start`/`-end` blocks all resolve.
- **M3-6 `.sql` files** take markers in `--` comments.
- **M3-7 Root assembly.** The provider's partial Compose document is merged into
  `docker-compose.yml`: its service, unless a rerun finds it present (logged, kept), and its
  `volumes`. The service of each package that selected the capability gains
  `environment.<NAME>: ${<NAME>:-<compose value>}` per env entry and
  `depends_on.<service>: { condition: service_healthy }`. The package's `.env.example` gains a
  block headed `# <kind>/<id> provider`, with a `# <summary>` line and `<NAME>=<local>` per entry
  and a comment naming the `test` value. The provider's `files` are copied to the project root
  when absent (logged and kept when present).
- **M3-8 Commands and provenance.** A package's recorded commands are the template's plus its
  capabilities'. Provenance records `packages.<dir>.capabilities`, the merged `commands` and
  `providers: { <kind>: <id> }`, typed in the schema as a string map. `schemaVersion` stays 1
  (additive), so v1.0.0 is the deliberate 1.0 of D10, not a schema break.
- **M3-9 Validation.** The loader refuses: a listed provider without its overlay directory,
  manifest or `overlay/`; an overlay on disk that the template does not list; a manifest whose
  `kind`/`provider` differs from its path; a provider with no `shared/providers/<kind>/<id>/
  provider.yaml`; a provider whose `kind` or `id` differs from its path; a missing provider
  `compose` or `files` entry; a script or command clash. The marker dry-run covers every flag,
  `server` and every kind's options (none, each provider), over `base/` plus the selected
  overlay. Case coverage adds, per listed provider, a case with only that capability and a case
  with that capability and every flag false.
- **M3-10 Routing.** `--capability <kind>=<provider>` goes to the one package whose template
  declares the kind. If no package declares it, the error is "unknown capability"; if two do,
  it is ambiguous (set it in an answers file); a provider not listed is an error naming the
  listed ones. Answers are checked the same way. The early refusal ("no provider overlays exist
  in this catalog yet") and its comment go.
- **M3-11 `test-generated --with-services`.** For a case that selects providers, it runs
  `docker compose -p <unique> up -d --wait <services>` in the generated directory. Then per
  package, in order: `migrate` (when defined), `check`, `testDb` (when defined), e2e. Last, always,
  `docker compose -p <unique> down -v --remove-orphans`. Without the flag a provider case runs
  `check` only and prints `SKIP testDb <dir>: needs --with-services`. A missing `docker` fails
  the case with that reason.
- **M3-12 The store test seam (base).** `tests/store.ts` exports `describeStore`,
  `resetStore()`, `recordExists(collection, id)` and `deleteRecord(collection, id)`. Every
  store-backed suite (`module`, `user`, `auth`, `session-cleanup`, `send-welcome`, the
  readiness-through-`app` case in `health`, the bind-failure case in `entry`) uses it instead of
  `memory` or `getDb()`. Suites over the cache (`memory`, `cache`, `otp`, `rate-limit`) keep
  `memory`. In base, `describeStore` is `describe` and `resetStore` is `memory.close()`, so the
  base behaviour is unchanged.
- **M3-13 The Postgres test model.** `tests/store.ts` (overlay): `describeStore` runs a suite
  only when `DATABASE_URL` names a database ending in `_test`, else `describe.skip`, so `check`
  runs no store-backed test. `resetStore` asserts `current_database()` ends in `_test`, truncates
  every table but `schema_migration`, and clears memory (the cache). `test:db` is
  `bun test --preload ./tests/db/setup.ts`. `setup.ts` defaults `TEST_DATABASE_URL` to the
  provider's test URL, refuses a database name not ending in `_test`, points `DATABASE_URL` at
  it before `config/env.ts` loads, and migrates it; an unreachable database fails with the
  `docker compose up -d database` hint.
- **M3-14 Errors.** `src/services/utils/postgres-error.ts` (overlay, pure) classifies an unknown
  error: connection failures → `upstream_unavailable` (503), SQLSTATE `23505` → `conflict`
  (409). `middleware/error-handler.ts` applies it under `@database:postgres` markers. No query
  text, no driver message reaches the client.
- **M3-15 Executor.** `services/db.ts` (overlay) exports `getDb(): SQL` and `type Executor`
  (the client or an open transaction). Every overlay `service.ts` function keeps its signature
  and takes an optional last `db: Executor = getDb()`. `api/module/service.ts` exports
  `withTransaction(work)` as the reference for a controller-owned transaction. The `AGENTS.md`
  text "as its first argument" becomes "as its optional last argument" (a controller cannot
  import `services/db.ts`, by lint).
- **M3-16 Migrations.** `src/infra/migrations/NNNN-<topic>.sql`, applied in name order, each in
  its own transaction, recorded in `schema_migration(name text primary key, applied_at
  timestamptz)`, under a Postgres advisory lock so two migrators cannot interleave. An applied
  file is never edited. The overlay ships `0001-init.sql`: `module`, and under `@auth` blocks
  `"user"` (quoted, a reserved word) and `session`. Tables, columns and indexes follow the
  `database` skill: snake_case, `text` ids, `timestamptz`, `(created_at, id)` for every
  paginated table, `"user"(email)` unique, `"user"(phone)` unique where `phone_verified_at is not
  null`, `session(user_id)`, `session(expires_at)`. Queries take time from the caller (JS
  `Date`), never `now()`, so `setSystemTime` drives them in tests.
- **M3-17 Env.** `src/config/env.ts` (base) gains `DATABASE_URL` under `@database` markers as a
  secret: listed in `SECRET_NAMES`, required in production, defaulted to the provider's local
  URL elsewhere with the boot warning. Its `postgres://` format check and dev default sit under
  `@database:postgres`.
- **M3-18 Versions.** `server/bun-express` `2.1.0` (a capability added; the default layout
  moves no file); `frontend/next` unchanged; catalog `v1.0.0`, tagged after merge (Open
  Question 3).

### Catalog, tools (paths relative to `fullstack-templates/`)

1. T1, schemas and loader. `schemas/provider.schema.json`, `schemas/capability.schema.json`,
   `schemas/provenance.schema.json` (`providers` a string map), `tools/lib/schema.ts` (the new
   names), `tools/lib/catalog.ts` (`ProviderManifest`, `CapabilityManifest`, loaded overlays per
   template, the M3-9 checks, case coverage for capabilities, `index` unaffected). Fixture:
   `tools/tests/fixtures/catalog/shared/providers/database/fake/` and
   `tools/tests/fixtures/catalog/server/mini/capabilities/database/fake/`, with cases.
   Tests in `tools/tests/catalog.test.ts` and `tools/tests/schema.test.ts`.
2. T2, plan, markers, dry-run. `tools/lib/plan.ts` (M3-10, `capabilities` in `PackagePlan`,
   selections per M3-5), `tools/lib/markers.ts` (`.sql` → `--`), `tools/lib/dry-run.ts` (M3-9
   combinations over `base/` plus each overlay). Tests in `tools/tests/plan.test.ts`,
   `markers.test.ts`, `dry-run.test.ts`.
3. T3, generate. `tools/lib/generate.ts` (M3-4, M3-7, M3-8), `tools/lib/dependencies.ts` (the
   npm adapter applies `scripts`, refusing an existing name), `tools/lib/compose.ts` (merge a
   partial document: services and volumes; add env and `depends_on` to a package service),
   `tools/lib/provenance.ts`, a small `tools/lib/env-example.ts` if the append outgrows
   `generate.ts`. Tests in `generate.test.ts`, `compose.test.ts`, `dependencies.test.ts`,
   `generate-cli.test.ts` (a `--capability` run on the fixture).
4. T4, test-generated and CI. `tools/test-generated.ts` (M3-11), `tools/lib/cases.ts` if needed;
   `.github/workflows/test-generated.yml` and `release.yml` pass `--with-services`;
   `test-generated.yml` and `validate.yml` also run on `push` to `dev`. Tests in
   `tools/tests/test-generated-cli.test.ts` (the SKIP line without the flag; argument parsing).

### Catalog, provider and template

5. T5, provider. `shared/providers/database/postgres/provider.yaml` (M3-3);
   `shared/providers/database/postgres/compose.yaml`. The service `database` runs
   `postgres:17-alpine` with `POSTGRES_USER/PASSWORD/DB` set to `app`, publishes
   `127.0.0.1:5432:5432`, has a `pg_isready` healthcheck, the named volume `database-data` and
   the read-only mount `./db/init.sql:/docker-entrypoint-initdb.d/init.sql`, and no profile.
   `shared/providers/database/postgres/db/init.sql` creates `app_test` owned by `app`.
6. T6, base seam and markers (`server/bun-express/base/`). `tests/store.ts` (M3-12) and the
   suites it lists, switched to it. Markers (M3-5) in: `src/config/env.ts` (M3-17),
   `src/infra/dependency.ts` (import `postgres`; `dependencies` is
   `[memory, postgres, pubsub, scheduler]`; the comment), `src/middleware/error-handler.ts`
   (M3-14), `tests/infra/dependency.test.ts` (the names), `tests/health.test.ts` (`postgres: 'ok'`
   in the through-`app` readiness case), `server/bun-express/compose.yaml` (the replica comment)
   and `AGENTS.md`. The `AGENTS.md` blocks cover Persistence, the layer map (`infra/postgres.ts`,
   `infra/migrations/`), The engine seam, Adding the data layer and Tests. In the Postgres
   variant, Adding the data layer says what exists and how to change the model: a new migration
   file, `bun run db:migrate`, `bun run test:db`, never edit an applied file. Base `check` stays
   green for `default`, `auth-off` and `stack-auth-off`.
7. T7, the overlay (`server/bun-express/capabilities/database/postgres/`). `capability.yaml`:
   no dependencies; scripts `db:migrate: bun run src/infra/scripts/migrate.ts` and
   `test:db: bun test --preload ./tests/db/setup.ts`; commands `testDb: bun run test:db`,
   `migrate: bun run db:migrate`. `overlay/`:
   - `src/infra/postgres.ts`: the `Resource` named `postgres`. The client is built lazily
     from `env.DATABASE_URL` with a connect timeout below the attempt timeout and its own
     initial-connect retry off. `connect` does `select 1` and releases the client when it
     rejects; `ping` does `select 1`; `close` closes and forgets the client. No I/O at import.
   - `src/services/db.ts`: `getDb()`, `Executor` (M3-15).
   - `src/infra/migrations/0001-init.sql` (M3-16, `@auth` blocks).
   - `src/infra/scripts/migrate.ts`: exports `migrate({ client?, directory?, logger? })` (M3-16); run as a
     script it migrates, logs each applied file, closes and exits non-zero on failure.
   - `src/api/module/service.ts`: SQL, signatures kept plus the optional executor, the
     `(created_at, id)` cursor, `withTransaction`.
   - `src/api/user/service.ts`: SQL for every query; the verified-phone lookup; row mapping
     with absent optionals omitted (`exactOptionalPropertyTypes`).
   - `src/services/session.ts`: the lock removed. Rotation is a conditional update
     (`where id = … and token_hash = … and revoked_at is null returning *`) with the
     re-read and grace decision of the base kept. Revoke-all is one filtered update that also
     clears `grace_token`, and purge is one delete.
   - `src/services/utils/postgres-error.ts` (M3-14).
   - `tests/store.ts` (M3-13), `tests/db/setup.ts` (M3-13).
   - `tests/db/postgres.test.ts`: the test database is `app_test`; `connect`, `ping` and
     `close` of the resource; `close` then `connect` works again. Migrating twice applies
     nothing new, and a failing migration rolls back and leaves no record. A
     `withTransaction` that throws writes nothing.
   - `tests/services/postgres-error.test.ts`: the classifier (no database needed, runs in
     `check`).
   - `tests/services/session.test.ts`: the base suite against Postgres through the seam,
     plus a real concurrent rotation (two `rotateSession` calls in `Promise.all`: one new
     token, the other answered from grace with the same token).
   - Tests for the 409 on a racing duplicate email, and for a 503 envelope when the store is
     unreachable, in the user and error-handler suites or in `tests/db/`, wherever the seam fits.
   Then `template.yaml` (`capabilities.database.providers: [postgres]`, version `2.1.0`) and
   `tests/cases.yaml`: `postgres` (`capabilities: { database: postgres }`),
   `auth-off-postgres` (adds `flags: { auth: false }`), `stack-postgres` (`stack:
   next-bun-express` with the capability).
8. T8, docs and release notes. `index.yaml` (`2.1.0`), `README.md` (status v1.0.0, a
   `--capability database=postgres` example, `bun tools/validate.ts --readme` for the matrix),
   `docs/capabilities.md` (status: shipped; the provider and overlay shapes as built),
   `CONTRIBUTING.md` (adding a provider, adding an overlay, the case rule, the seam),
   `docs/adr/0001-catalog-architecture.md` (`## Amendments (v1.0.0)`: M3-1 to M3-17 in one line
   each), `server/bun-express/CHANGELOG.md` (`2.1.0`), `server/bun-express/README.md`.

### Harness (paths relative to this repository)

9. H1, text. `AGENTS.md` (the `db/` layout row; the `testDb` and `migrate` rows and the
   paragraph under the command table), `.claude/agents/backend.md` (Gates),
   `.claude/agents/qa.md`, `.claude/skills/dev-loop/SKILL.md`,
   `.claude/skills/writing-tests/SKILL.md`: resolve `testDb` and `migrate` from
   `.fullstack/catalog.yaml`, else from the package's `AGENTS.md › Adding the data layer`.
   `.claude/skills/bootstrap-project/SKILL.md` §4 and §5: with a provider, start its Compose
   service, run `check`, `migrate`, `testDb`, then e2e, and fill Data store from the provider.
   §4's "fresh server package" paragraph covers both paths. `.claude/skills/database/SKILL.md`
   (the wired provider; the test-database rule). `.doc/architecture.md` (the hints at Data
   store). `README.md`.
10. H2, `scripts/bootstrap.mjs` `printNextSteps`: when `--capability` (or an answers file)
    selected a provider, print `docker compose up -d <service>` and "run the server package's
    `migrate` then `testDb` command (`.fullstack/catalog.yaml`)". Dependency-free, no YAML
    parsing.
11. H3, proof (V20–V23): bootstrap scratch roots from the local catalog checkout on the feature
    branch (`--templates`, `--root` under `.superpowers/s008/`), one with
    `--capability database=postgres` and one without, and run every gate.

## Validation

- V01 — `tools` passes its own gates — proof: `cd tools && bun run check`
- V02 — the catalog validates, the README matrix is current and lockfiles are in sync — proof:
  `bun tools/validate.ts`; `bun tools/validate.ts --lockfiles`
- V03 — the loader refuses each M3-9 inconsistency with a message naming the path — proof:
  `tools/tests/catalog.test.ts` cases per check
- V04 — routing: unknown capability, ambiguous capability, unlisted provider, answers with an
  unknown kind, each a `PlanError`; a valid shorthand routes to the declaring package — proof:
  `tools/tests/plan.test.ts`
- V05 — `@<kind>`, `@no<kind>`, `@<kind>:<provider>` lines and blocks resolve under each
  selection, and `.sql` uses `--` — proof: `tools/tests/markers.test.ts`, `dry-run.test.ts`
- V06 — generating the fixture with its capability copies the overlay over base, adds scripts
  and commands, merges the provider service, volume, env and `depends_on`, appends
  `.env.example`, copies the provider file only when absent, and records `providers` — proof:
  `tools/tests/generate.test.ts`, `compose.test.ts`, `dependencies.test.ts`
- V07 — a capability case without `--with-services` prints `SKIP testDb` and passes on `check`
  — proof: `tools/tests/test-generated-cli.test.ts`
- V08 — the no-capability cases are unchanged and green — proof: `bun tools/test-generated.ts
  --case server/bun-express/default --case server/bun-express/auth-off --case
  server/bun-express/stack-auth-off --case frontend/next/default --case frontend/next/alone
  --e2e`
- V09 — the Postgres cases pass with services: migrate, check (store suites skipped), testDb
  (every suite, including session concurrency and the test-database check), e2e for the stack —
  proof: `bun tools/test-generated.ts --case server/bun-express/postgres --case
  server/bun-express/auth-off-postgres --case server/bun-express/stack-postgres --e2e
  --with-services`
- V10 — a generated Postgres backend's `check` passes with no database running — proof: the
  `check` step inside V09 runs before services matter (and `bun run check` in a kept case dir
  with Docker stopped)
- V11 — the generated tree is right: `docker-compose.yml` has `database` with a healthcheck and
  volume, `backend` depends on it healthy and carries `DATABASE_URL`, `db/init.sql` exists,
  `.env.example` lists `DATABASE_URL`, `.fullstack/catalog.yaml` records `testDb`, `migrate`
  and `providers.database: postgres` — proof: `bun tools/generate.ts --stack next-bun-express
  --capability database=postgres --out <scratch> --name demo`, inspected, plus a generate test
  on the real catalog without post-generate
- V12 — no secret, query text or driver message reaches a client; a racing duplicate email is
  a 409 envelope and an unreachable store a 503 envelope — proof: the overlay tests named in T7
- V13 — CI is green on the catalog PR: validate and every case job, with services — proof: the
  PR's checks
- V20 — a harness bootstrap with `--capability database=postgres` from the local catalog: the
  backend's `check`; `docker compose up -d database`; `migrate`; `testDb`; the frontend's
  `check` and `testE2e` — proof: the commands in a `.superpowers/s008/pg-root` scratch root
- V21 — a harness bootstrap without a capability is unchanged — proof: the same gates in
  `.superpowers/s008/plain-root`
- V22 — no harness root file names a framework or a package manager command — proof: `grep`
  of `AGENTS.md`, `.claude/rules`, `.claude/agents`, `.claude/skills` for `bun run`, `zod`,
  `Express`, `Bun SQL`, with every hit justified
- V23 — the harness hooks still pass their probes — proof: `node .claude/hooks/*` unaffected (no
  hook file changes; `git diff dev -- .claude/hooks` is empty)

## Risks

- Bun SQL behaviour differs from the documentation the code assumes (lazy connect, error
  codes, `close` then reuse, multi-statement `unsafe`) — T7 verifies each against
  `bun-types` and a live database before writing on top of it. V09 is the end-to-end proof.
- The seam's skip hides a store-backed suite that should have run — `describeStore` keys on
  the database name, `testDb` must report the suites as passed (not skipped), and V09 checks
  the `testDb` output has 0 skipped.
- A developer's shell `DATABASE_URL` points at a real database and `check` truncates it — the
  seam runs only against a `*_test` name, and `resetStore` re-checks `current_database()` before
  truncating.
- Port 5432 is taken on a developer machine or a CI runner — the case fails with Compose's
  bind error, and test-generated tears down per case. The Compose project name is unique per
  case, so two cases never share a volume.
- Windows holds files after Docker or Bun exit — the generator's rename retry covers the move.
  test-generated's `down -v` runs before the temp directory is removed.
- Marker combinations grow (flags × server × providers) — the dry-run enumerates them. With one
  flag and one provider that is 8 runs per file; it is linear in providers per kind.
- The overlay drifts from base (a base service changes, the overlay copy does not) — the
  overlay replaces only the engine-bound files (`db.ts`, each `service.ts`, `session.ts`, the
  test seam). CI runs both variants on every PR.

## Rollout Order

Catalog T1 → T2 → T3 → T4 (tools, sequential), with T5 and T6 alongside them (disjoint paths),
then T7 (needs the tools and the base), then T8. A Sonnet review after each task. One Opus final
review of the catalog branch and one fix wave. Then V08–V11 locally, push, the PR into `dev`, and
V13 on CI. Harness H1 and H2 run after T7 (the skill text describes what T7 built), then H3
against the local catalog checkout, one Opus final review and a fix wave, then the PR into
`dev`.

## Rollback

Each repository's change is one branch merged into `dev`; revert the merge commit there. The
catalog keeps `v0.1.1` and the harness lock still pins it, so a revert leaves `main` and every
bootstrap untouched. No data migration runs against anything but throwaway case databases and
scratch roots. The generated Postgres project's migrations are forward-only by design; dropping
or resetting a database is a human's job (`database` skill).

## As built

Deviations from the plan text above (the original sections stay as planned, except the plain
factual errors corrected in place: the verification order is `check` first, H2 prints
`<service>`, and `migrate` takes `{ client?, directory?, logger? }`):

- The capability manifest has per-flag `onlyPaths` for overlay files (ruling R10).
- Provider env entries are `secret: true`: there is no Compose default for `DATABASE_URL`
  (R11, from the catalog's final fix wave). The full stack fails fast unless the production
  secrets and the database URL are exported.
- Env entries gained `testOverride`; capability kind names are reserved as flag names; env
  values are constrained to one line.
- Nothing runs migrations automatically. The docs give the command; a one-shot migrate
  service is a follow-up.
- The harness and the catalog say `docker compose up -d --wait <service>`.
- `testDb` refuses to pass with every store-backed suite skipped.
- Execution was regrouped into ten tasks plus two final reviews and fix waves, with the ledger
  in `.superpowers/sdd/008-2026-10-22-postgres-capability/progress.md` (git-ignored).
- Follow-ups: the `v1.0.0` tag and the `catalog.lock` bump (Eitan), a one-shot migrate
  service, hash pins on overlay-shadowed base files, optimistic concurrency for the user
  update, a partial index for the session purge, signal cleanup in test-generated, a
  real-catalog generate unit test.
- Closed 2026-10-23 (gate G0 of plan 009):
  - catalog `dev` merged into `main` as 1c6997a (PR #3);
  - `v1.0.0` tagged there;
  - `catalog.lock` bumped to it, with a fresh-cache bootstrap proof in the lock PR.

  The migrate service, the pins and the real-catalog generate test moved into plan 009. The other
  follow-ups stay open.
