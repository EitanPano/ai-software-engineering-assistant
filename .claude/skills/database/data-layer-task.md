# The data-layer task

Read this for the backlog line `add the <engine> data layer` or `add the data layer`: the bootstrap
wired no provider, so `.fullstack/catalog.yaml` has `providers: {}` and the server still runs on
the in-memory store.
The `database` skill's rules hold throughout; this file is what the task delivers.

The database seam is a file seam, not a type seam: it exports the active store, and its
type changes with the engine. One task, planned and reviewed like any other, delivers:

1. The engine's service in `docker-compose.yml` at the repository root, with the server
   under the `app` profile pointing at it and depending on it.
2. The URL variable in the package's env module (required in production, defaulting to the
   compose service elsewhere) and in its `.env.example`.
3. A live connection exported as a `Resource`: connected at boot, pinged by readiness,
   closed on shutdown, listed in the dependencies in place of the in-memory store.
4. The db seam rewritten to export the engine's client.
5. Every module's data-access file rewritten against it, and any shared file that keeps
   its own queries. Signatures stay; bodies change.
6. A migration script and its first migration (or the index definitions), and the
   `migrate` script, named in the package's `AGENTS.md › Adding the data layer`.
7. A test database and the `testDb` script (see Test database), named in the same section,
   plus one test proving the test database is the one in use.
   The Compose service is named `database`: `verify` starts it by that name.
   The backend report carries `Commands: testDb=<command>; migrate=<command>` and, with a
   frontend, `; e2eDb=<command>`; the driver writes them under `packages.<dir>.commands` in
   `.fullstack/catalog.yaml` before it dispatches the frontend stage and before the next
   `verify`, so the gate runs them.
   On a stack with a frontend, the task also wires the browser-test database, in two stages
   (the backlog line is full-stack for this reason). The frontend was generated without its
   `server:database` e2e files, so its e2e would start the API against the development
   database.
   - **Backend stage.** Adds `e2eDb`, which creates, migrates and truncates the e2e database
     (`app_e2e`), reads `E2E_DATABASE_URL` (the frontend's Playwright config passes it) and
     refuses a name not ending in `_e2e`. Follow the database overlay's reference script in
     the catalog: `server/bun-express/capabilities/database/postgres/overlay/src/infra/scripts/e2e-db.ts`
     (script `db:e2e`) or `server/python-fastapi/capabilities/database/postgres/overlay/src/app/infra/scripts/e2e_db.py`
     (`poe e2e-db`), with its test. The backend report names it:
     `Commands: testDb=…; migrate=…; e2eDb=…`.
   - **Frontend stage.** Wires the e2e start chain as the template's `server:database` variant
     does, `<e2eDb> && <start>` for the API. The **driver** reads three files, by exact path and
     without browsing, in the catalog release `catalog.lock` pins (cache root
     `FULLSTACK_TEMPLATES_CACHE`, default `~/.cache/fullstack-templates`, then the version
     folder; it is never listed or searched), under
     `frontend/<next|react>/base/` for the frontend's template: `scripts/e2e-database-url.ts`,
     `tests/unit/e2e-database-url.test.ts` and `playwright.config.ts`. It hands their content
     in the frontend dispatch, never in the plan, which only names the step. Resolve the
     markers in the config: keep `@server:database` lines and blocks, drop `@noserver:database`
     lines, strip the marker comments, and fill `__SERVER_E2E_DB_COMMAND__`,
     `__SERVER_START_COMMAND__` and `__SERVER_DIR__`/`__SERVER_PORT__` from
     `.fullstack/catalog.yaml` (the driver records the backend's `Commands:` there first), and
     `__SERVER_E2E_DATABASE_URL__` with the `e2e` value of the engine's `DATABASE_URL` in the
     catalog's `shared/providers/database/<id>/provider.yaml` (Postgres:
     `postgres://app:app@127.0.0.1:5432/app_e2e`). The frontend agent never reaches into the
     cache itself.
   - **Engines without an e2e chain.** The catalog ships one for Postgres only (MongoDB has no
     provider): the frontend stage is skipped and the plan's Risks note that e2e uses the
     development database.
   Without a frontend there is no e2e chain, and `e2eDb` is not added.
8. A `.doc/architecture.md` change-log line, the Data Model section started, and the `Local service`
   line and the components table's `Data store` row written.
