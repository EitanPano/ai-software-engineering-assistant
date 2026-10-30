# python-fastapi at parity with bun-express, the next-python-fastapi stack, catalog v1.1.0

Status: done
Status set by the session on Eitan's delegation; Eitan confirms.
Owner: Eitan
Last updated: 2026-10-24
Approval: approved 2026-10-23 ("go with the plan, do it python 3.14 if it's a better solution
than 3.15"). Scope was decided by question on 2026-10-22: full parity including Postgres, the
`next-python-fastapi` stack, one graded eval, the migrate service and hash pins.
Branch: `feat/python-fastapi` in both repositories, cut from `dev` on 2026-10-23 before G0
(see Assumptions)
Base: harness 5a65f41 (`dev`), catalog f2140db (`dev`; `v1.0.0` was tagged 2026-10-23 on its
`main` merge 1c6997a, the same tree)
Stages: harness and catalog only (no role agents; the interactive session drives Sonnet
implementers per task, a Sonnet review per task, one Opus final review per repository, and
the eval), ending in one pull request per repository into `dev`

## Goal

Milestone 4 adds a second server language to the catalog. After it:

- `bun tools/generate.ts --stack next-python-fastapi [--capability database=postgres]`
  writes a project whose `backend/` is FastAPI on Python 3.14, managed by uv.
- That backend has the same directories, request flow, error envelope, camelCase wire
  format, auth surface (accounts, sessions with rotation and grace, JWT, OTP, roles), jobs,
  bus, health and readiness, and Postgres capability as `bun-express`. Each of its
  `bun-express` tests has a pytest counterpart.
- The Next frontend regenerates its types from FastAPI's `openapi.json` and passes every gate
  unchanged.
- Both server templates gain a one-shot migrate service on the Compose `app` profile.
- Overlays pin the base files they shadow, so drift fails `validate`.
- CI proves every case, and for the first time builds and boots the images.
- The harness is safe for a Python backend: hooks see through Python runners, permissions
  are narrow, and rules are language-neutral. It bootstraps the new stack with every gate
  green.
- An unattended agent builds the "todo" product on it. That run is graded against a written
  rubric next to a Bun control run on the same harness commit.

The catalog ships as `v1.1.0` and the harness lock follows it.

## Scope

**In, catalog side** (`fullstack-templates`):

- ADR 0002, `docs/adr/0002-python-fastapi.md`. It holds decisions M4-1 to M4-18, the file
  mapping table, the behaviour table, and the `conventions.md` amendments where D4 was
  "TypeScript in disguise".
- Machinery:
  - the `pyproject` adapter and per-adapter lockfile checks;
  - one shared ignore set;
  - the post-generate drop and retrying removal;
  - the tools preflight;
  - the migrate service;
  - pins and `validate --pin`;
  - the headings check;
  - the `__SERVER_DEV_COMMAND__` placeholder;
  - `test-generated --with-app`;
  - a real-catalog generate test, left over from milestone 3.
- `server/python-fastapi` 1.0.0:
  - `base/`, with the `auth` flag;
  - the `capabilities/database/postgres/` overlay;
  - eight cases;
  - `AGENTS.md`, `README.md`, `CHANGELOG.md`.
- `stacks/next-python-fastapi/`.
- Shared files: `shared/gitignore/python.gitignore` and `[*.py] indent_size = 4` in
  `shared/editorconfig/.editorconfig`.
- `server/bun-express` 2.2.0: the migrate service command, pins, and the
  `stack-auth-off-postgres` case.
- `frontend/next` 1.1.0: `__SERVER_DEV_COMMAND__`.
- CI: setup-uv in `validate.yml`, `test-generated.yml` and `release.yml`, plus the compose
  smoke step.
- Docs: `README.md` (generated matrix), `CONTRIBUTING.md` (a non-npm template, refreshing
  `uv.lock`, pins, the migrate service), `docs/conventions.md`, `docs/capabilities.md`, and
  ADR 0001 (Delivery order and D2 pointers to 0002).

**In, harness side** (this repository):

- Hooks:
  - Python runners and value flags in `.claude/hooks/lib/guardrail.mjs`;
  - raw-token secret scanning, Python inline code and environment dumps, and Python secret
    file names in `block-secret-file-access.mjs`;
  - `py` and `python3.N` in `enforce-agent-boundaries.mjs`;
  - a committed `node --test` suite in `.claude/hooks/test/`.
- `.claude/settings.json`: narrow uv allow entries.
- Language-neutral text in:
  - `AGENTS.md` (prerequisites, migrate wording, DoD item 3);
  - `.claude/rules/naming.md`;
  - the `writing-tests`, `api-design`, `database`, `error-handling` and `code-review` skills;
  - the `qa` and `backend` agents;
  - the `bootstrap-project` skill (tools check, prerequisites);
  - `scripts/bootstrap.mjs` (`printNextSteps`);
  - `README.md`, `.doc/architecture.md` hints;
  - `.claude/rules/code-style.md` (its stale "TypeScript strict" line).
- This plan.
- After the tag: the `catalog.lock` bump to `v1.1.0`.

**In, eval:** a paired unattended run in `C:\Dev\Playground\AI\harness-eval\`, outside both
repositories. It uses the rubric written first.

**Out:**

- `frontend/react`, MongoDB, Redis, workers, messaging.
- Python versions other than 3.14.
- A dependency bot (ADR "left to the builder"; recorded as a follow-up).
- Harness CI.
- Updating existing projects to newer templates.
- Publishing to PyPI.
- Changing the `bun-express` behaviour beyond the migrate service and pins.

## Assumptions

- **G0 is done before the branch cut:**
  - catalog `dev` → `main` is merged;
  - `v1.0.0` is tagged on it by Eitan;
  - harness `dev` → `main` is merged;
  - the lock bump to `v1.0.0` is merged, with a fresh-cache V20;
  - plan 008 is `done`.

  If milestone 4 merged into `dev` first, `v1.0.0` could no longer be cut from `dev`.

  As run: G0 was still open at activation (no `v1.0.0` tag; `main` behind `dev` in both
  repositories). The branches were cut from `dev` anyway, whose content is what `v1.0.0`
  will tag; G0 now gates the two milestone 4 pull requests into `dev`, not the cut.
- ADR 0001 with all its amendments, and plan 008's rulings (As built), stand. This plan
  reopens none of them.
- Local machine: uv 0.12.23, Python 3.15.0 (system), Bun 1.4.0, Node 24.15, Docker 29.7.
  uv installs the pinned 3.14 itself. 3.14 is chosen over 3.15 because 3.15 is weeks old and
  compiled wheels lag: on 2026-10-23 the planned set resolved with binary wheels only for
  3.14 on Windows and Linux, and failed for 3.15 because `pyyaml` (pulled in by `poethepoet`
  and `uvicorn[standard]`) has no cp315 wheel.
- The `bun-express` tests are the executable specification. "Parity" means the behaviour
  each one asserts, not its syntax.
- The user's rules hold:
  - Sonnet for implementers and task reviewers, Opus for final reviews;
  - Conventional Commits;
  - no commit, push, PR, merge or tag without Eitan's explicit yes at execution time;
  - agents never rewrite history.

## Open Questions

1. Which Python version? **Recommended:** 3.14, pinned by `.python-version`,
   `requires-python = ">=3.14,<3.15"` and mypy `python_version`. Move to 3.15 in a template
   minor once the wheels exist. Decided 2026-10-23 by Eitan: 3.14 (evidence in Assumptions).
2. Which task runner gives a one-program `check` and a home for capability tasks?
   **Recommended:** poethepoet tasks in `pyproject.toml`, invoked as `uv run poe <task>`. If
   uv ships a stable native task runner by S1, ADR 0002 prefers it and records the switch.
3. Which Postgres driver? **Recommended:** psycopg 3 async with `psycopg_pool` (typed,
   SQLSTATE on errors, lazy pool), if S1 proves it on Windows across all four loop owners.
   Otherwise asyncpg with `asyncpg-stubs`.
4. Which HTTP port? **Recommended:** 8000. It is FastAPI's convention, and it proves that
   `__SERVER_PORT__` flows into the frontend.
5. What is the environment-mode variable? **Recommended:** `APP_ENV`
   (`development|test|production`), with the same semantics as `NODE_ENV` in `bun-express`.
6. Does the API accept snake_case request keys? **Recommended:** no. Validate by alias only,
   so the wire format is camelCase in both directions, as in `bun-express`.
7. Is the migrate service always generated with a database capability? **Recommended:** yes.
   The `app` profile otherwise boots against an unmigrated database. The manual `migrate`
   command stays for local development.
8. Where do the hook tests live? **Recommended:** `.claude/hooks/test/*.test.mjs`, run with
   `node --test ".claude/hooks/test/*.test.mjs"` (the quoted glob is expanded by Node; the
   directory form fails on Node 24). Name them in `README.md` (Recovery) and require them
   for any hook change.

## Steps

### Gates

- **G0 (Eitan):** close milestone 3 (see Assumptions). Then cut both branches.
- **G1 (Eitan):** approve ADR 0002 before any port task (P1 and later) starts.
- **S1 spike** (time-boxed, half a day; runs alongside the ADR draft). Scratch work only,
  findings go into ADR 0002. It proves on Windows and Linux:
  - the driver under all four loop owners: the uvicorn dev server with reload, httpx
    `ASGITransport` under pytest with anyio, the migrate script's `asyncio.run`, and pytest
    itself;
  - `python -m pytest -p tests.db.plugin` importing with `tests/` as a package;
  - the uv staging round trip: `uv sync` in staging, drop `.venv`, move, `uv run poe check`;
  - `uv lock --check` in a scratch copy of `base/`;
  - `.sql` files reaching the image (uv_build wheel or a non-editable install);
  - `docker compose up --wait` with a one-shot service that exits 0.

### Decisions (ADR 0002 records these; implementers do not reopen them)

As run: ADR 0002 (catalog `docs/adr/0002-python-fastapi.md`) is the binding text for M4-1 to
M4-19 and M4-23. Where the summaries below differ, the ADR wins. It was corrected by an
architecture review on 2026-10-23. The main differences:

- three model bases and pydantic's `MISSING` sentinel (M4-7);
- no pydantic-settings and no dotenv loading (M4-11);
- `pytest -p tests.db.plugin`, not `python -m pytest` (M4-12);
- M4-19, one selector event loop;
- M4-23, the entry, the image and Compose.

- **M4-1 Toolchain.**
  - uv, pinned by `[tool.uv] required-version` and the pinned setup-uv action version.
  - Python 3.14 (OQ1), build backend `uv_build`, src layout `src/app/`.
  - The distribution and import package are both `app`. `pyproject.toml` and `uv.lock`
    carry no placeholder, so `uv.lock` stays a byte copy. `__PROJECT_NAME__` appears only in
    `config/constants.py` and the OpenAPI title.
- **M4-2 Commands.** Every `template.yaml` command is `uv run poe <task>`, one program with no
  chaining.
  - `check` runs `lint` (`ruff check` + `lint-imports`), `format-check`
    (`ruff format --check`), `typecheck` (`mypy --strict` with the pydantic plugin) and
    `test` (`python -m pytest`).
  - `contract` writes `openapi.json` at the package root.
  - The image never uses poe, which is a dev dependency.
- **M4-3 Dependencies through markers.**
  - TOML has comments, so flag- and capability-bound dependency lines and poe tasks carry
    `# @auth` and `# @database:postgres` markers in base `pyproject.toml`.
  - The new adapter value is `pyproject`. The loader refuses `dependencies` or `scripts`
    declarations for it, with "use markers in pyproject.toml".
  - Base `uv.lock` is the superset lock. The post-generate `install` runs `uv sync`, which
    re-locks and prunes while keeping locked versions.
  - `validate --lockfiles` dispatches per adapter: `bun install --frozen-lockfile`, or
    `uv lock --check`.
  - `CONTRIBUTING.md`: edit `pyproject.toml` by hand, then run `uv lock`. `uv add` moves
    trailing markers.
- **M4-4 Tree hygiene.**
  - One ignore set serves both copying and listing (`tools/lib/files.ts`): `node_modules`,
    `.venv`, `__pycache__`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`,
    `.import_linter_cache`, `*.egg-info`, and the existing entries.
  - New manifest field `dropAfterPostGenerate` (python-fastapi: `.venv` and the tool
    caches). Those paths are removed with `rmSync` retries before the move.
  - post-generate runs with `PYTHONDONTWRITEBYTECODE=1`, so the same inputs give the same
    tree (D6).
- **M4-5 Tools preflight.** This runs only when post-generate runs.
  - Each planned template's `tools` entry is resolved through `resolveCommand`, with
    `--version` parsed against `min`.
  - A failure names the tool, the version found and the minimum.
- **M4-6 File mapping.** ADR 0002 holds the table; these entries are fixed:
  - `index.ts` → `main.py`. It composes the infra lifespan, serves uvicorn programmatically
    and handles the signals.
  - `server.ts` → `server.py`. `create_app()` attaches no infra lifespan, so tests never
    start infrastructure.
  - `openapi.ts` → `openapi.py`, run as `python -m app.openapi --write`.
  - `api/<m>/{routes,controller,schema,service}.py`; `routes.py` exports `router`.
  - The `middleware/` directory holds both ASGI middleware and the gate dependencies (auth,
    role, rate limit).
  - `express.d.ts` → `middleware/context.py`. There is no `validate.py`, because FastAPI and
    pydantic validate.
  - Names never shadow the stdlib (ruff A005): `enum.py` → `enums.py`, `utils/time.py` →
    `utils/clock.py`.
  - `tests/` is a package with `__init__.py` throughout, mirroring `src/` as
    `test_<name>.py`. Two `test_auth.py` files then cannot clash.
- **M4-7 Wire format.**
  - An `ApiModel` base with `alias_generator=to_camel`, validating by alias only (OQ6) and
    serializing by alias.
  - Attributes are snake_case.
  - `separate_input_output_schemas=False`.
  - Component names are identical to the `bun-express` set: ErrorBody, HealthResponse,
    Readiness, AuthSession and the rest.
- **M4-8 Behaviour table.** ADR 0002 holds it, and both templates test each row:
  - the envelope is `{error:{code,message,details?},requestId}`;
  - `RequestValidationError` → 400 `validation_failed`, details `[{path,message}]`;
  - malformed JSON → 400 "malformed JSON body";
  - a non-JSON body → 400 from validation, not 415;
  - more than 1 MB → 413;
  - a bad charset or encoding → 415;
  - an unknown path or a wrong method → 404 `not_found` "no route for METHOD path";
  - `redirect_slashes=False`;
  - request id rules;
  - helmet's default headers, listed explicitly;
  - no `server` header, and no docs or redoc routes;
  - `/openapi.json` is served;
  - proxies are trusted by hop count from `TRUST_PROXY` in ASGI middleware, with uvicorn
    `proxy_headers=False`;
  - 429 with `Retry-After`;
  - auth cookie attributes and `Cache-Control: no-store`.
- **M4-9 OpenAPI shaping.** A custom `openapi()`:
  - drops every 422 and `HTTPValidationError`;
  - registers ErrorBody;
  - adds per-route error responses from a helper;
  - sets `servers:[{url:'/'}]`, the title, and the version from package metadata.

  `tests/test_openapi.py` fails on a stale `openapi.json`.
- **M4-10 Layers.**
  - import-linter contracts mirror the ESLint zones of `bun-express` (`eslint.config.mjs`).
  - Module privacy (a module's `service` is imported only by its own module; another module
    reaches it only through `controller` and `schema`) is an import-linter custom contract
    type inside the package, so it fails `lint`, not `test`.
  - Everything else is a review rule in `AGENTS.md`.
- **M4-11 Libraries.** S1 verifies these; `uv.lock` pins the versions.
  - FastAPI, pydantic v2, pydantic-settings (`env_file=.env`), uvicorn.
  - argon2-cffi (argon2id, plus a dummy hash for unknown emails), PyJWT (HS256),
    cryptography (AES-256-GCM).
  - APScheduler 3.x `AsyncIOScheduler` with `max_instances=1` and `coalesce`, which matches
    croner's `protect`. 4.x is a prerelease.
  - stdlib logging, with the `bun-express` line format and redaction.
  - httpx `AsyncClient` with `ASGITransport` under anyio. Not TestClient, whose portal
    thread owns its own loop.
  - time-machine for the clock.
- **M4-12 Postgres overlay (Python).** The driver follows OQ3, and the semantics are those of
  plan 008's M3-13 to M3-16.
  - `infra/postgres.py` is a Resource with a lazy pool and no I/O at import.
  - `services/db.py` exports `get_db()` and `Executor`; queries take an optional last `db`
    keyword; `with_transaction` lives in the module's service.
  - `src/app/infra/migrations/NNNN-<topic>.sql`, with `schema_migration`, an advisory lock
    and one transaction per file. The files are packaged into the image.
  - `services/utils/postgres_error.py` uses the same codes.
  - Session rotation is a conditional update.
  - `tests/store.py` exposes a `store_backed` marker, live only when the `DATABASE_URL`
    database name ends in `_test`. `reset_store` refuses any other database.
  - `testDb` is `uv run poe test-db`, which runs `python -m pytest -p tests.db.plugin`. The
    plugin points `DATABASE_URL` at `TEST_DATABASE_URL` before the app is imported, migrates,
    and fails the session if every store-backed test was skipped.
- **M4-13 Migrate service** (both server templates).
  - The capability manifest declares `container.migrate` (python:
    `python -m app.infra.scripts.migrate`; bun: `bun run src/infra/scripts/migrate.ts`).
  - The generator derives `<dir>-migrate` from the package's assembled service:
    - the same `image:` name and `environment` (all production secrets, because the env
      module parses them at import);
    - the migrate command;
    - no ports, `restart: "no"`, profile `app`;
    - `depends_on` the provider, healthy.
  - The package service gains `depends_on` on `<dir>-migrate` with
    `service_completed_successfully`.
  - The clash check (`tools/lib/plan.ts`) and the rerun merge both know the derived name.
- **M4-14 Pins.**
  - The capability manifest holds `pins: {<base path>: <git blob id>}` for every base file
    its overlay replaces.
  - `validate` fails on a missing pin, a stale pin and a mismatch.
  - `validate --pin <template>/<kind>/<provider>` refreshes the pins and prints the base diff
    since the old pin.
- **M4-15 Frontend.** `__SERVER_DEV_COMMAND__` resolves to the server package's
  `commands.dev`. It replaces `bun run dev` in `frontend/next/base/playwright.config.ts`.
- **M4-16 Compose smoke.** `test-generated --with-app`:
  - generates throwaway production secrets;
  - runs `docker compose --profile app up --build --wait`;
  - checks `http.health` and `http.ready`;
  - always ends with `down -v`.

  CI runs it on `stack-postgres` for both servers.
- **M4-17 Headings check.** `validate` fails when a server template's agents file lacks a
  heading the harness cites: "Adding a module", "Adding the data layer", "Errors", "Tests".
- **M4-18 Versions.**
  - catalog `v1.1.0`: additive, `schemaVersion` stays 1, so the harness's
    `SUPPORTED_SCHEMA_VERSION = 1` holds;
  - python-fastapi 1.0.0;
  - bun-express 2.2.0;
  - frontend/next 1.1.0.
- **M4-20 Hooks.**
  - A runner table with per-runner value flags:
    - `uv run` and `uv tool run`, with `--directory`, `--project`, `--with`,
      `--with-requirements`, `--python`, `--group`, `--extra`, `--package`, `--env-file`,
      `--index`;
    - `uvx [--from X]`;
    - `poetry run`, `pipx run`, `pdm run`, `hatch run`.
  - `python -m <mod>` resolves to `<mod>`. `py`, `python3.N` and `pypy` count as inline
    runtimes in both hooks.
  - The secret hook scans the raw tokens, splitting `--flag=value`. It also scans
    inline-code arguments for secret file names. That closes `--env-file .env` and
    `--env-file=.env`, which pass today for `bun run`.
  - Python environment dumps are blocked: `os.environ` in any form, `dict(os.environ)`,
    `.items()`, `.copy()`, `.keys()`. So are `.pypirc` and `pip.conf`.
- **M4-21 Permissions.** The allow list gains only `Bash(uv run poe *)`, `Bash(uv sync*)` and
  `Bash(uv lock*)`. A broad `uv run *` would auto-approve `uv run python -c …` and
  `--with <any package>`.
- **M4-22 Language-neutral rules.**
  - A rule states the principle and points at the package's `AGENTS.md` for the language's
    list: file case, skip, focus, xfail and deselect forms, the env module, and the router's
    gates (middleware or dependencies).
  - Path notation becomes `/api/post/{id}`; "the compiler" becomes "the type checker".

### Execution protocol (AI prompt design, for every task)

Each implementer dispatch is a self-contained brief with these fields:

1. **Goal:** one sentence.
2. **Read first:** the `bun-express` source and tests for the slice, the ADR 0002 rows, and
   the parity-ledger rows.
3. **Decisions that bind:** the M4-n numbers.
4. **Paths you may touch.**
5. **Done when:** exact commands with the expected result.
6. **Report:** files changed, ledger rows ticked with pytest names, deviations, questions.

Standing rules in every brief:

- Port behaviour, not syntax: idiomatic async Python, full typing, no `Any`, and no
  `# type: ignore` without a reason on the line.
- Verify every third-party API against the installed package (`.venv` source) or its current
  docs before using it. Never write one from memory.
- Write the tests first, from the `bun-express` assertions.
- No skip, xfail or deselect outside the store seam.
- Do not edit outside the listed paths.
- If parity cannot be met idiomatically, stop and report. The session records a ruling
  (R-n) in the ledger, `.superpowers/sdd/009-2026-10-23-python-fastapi/progress.md`
  (git-ignored).

**Parity ledger:** every `it(...)` in `bun-express` `tests/**` and in the overlay's tests
gets a row: test name → pytest node id, or a ruling. The task reviewer checks the slice's
rows. V15 audits the whole ledger.

**`AGENTS.md` as a prompt:** the Python agents file keeps the `bun-express` headings in the
same order (M4-17). It carries the "where does X go" table with Python paths, the
language-specific lists that M4-22 moved out of the harness, and only rules that lint, a test
or review can check. The eval (E1) measures whether it works.

### Catalog tasks (paths relative to `fullstack-templates/`)

1. **A0, ADR 0002** (with S1).
   - `docs/adr/0002-python-fastapi.md`: M4-1 to M4-18, the mapping and behaviour tables, S1
     findings.
   - `docs/conventions.md`: the amendments.
   - `docs/adr/0001-catalog-architecture.md`: Delivery order (`next-python-fastapi` comes
     before react) and D2/D4 pointers.
   - Gate G1 follows.
2. **T1, machinery I** (~700 LOC).
   - `schemas/template.schema.json` (adapter enum, `dropAfterPostGenerate`);
     `schemas/capability.schema.json` (`container`, `pins`).
   - `tools/lib/catalog.ts` (types, pyproject refusal);
     `tools/lib/dependencies.ts` and `tools/lib/capabilities.ts` (adapter dispatch);
     `tools/lib/lockfiles.ts` (per adapter).
   - `tools/lib/files.ts` (shared ignore set, `removeTree` retries).
   - `tools/lib/generate.ts` (drop, `PYTHONDONTWRITEBYTECODE`, preflight with
     `tools/lib/commands.ts`).
   - Fixture: `tools/tests/fixtures/catalog/server/mini-py/` (a pyproject template).
   - Tests in `tools/tests/*.test.ts`.
3. **T2, machinery II** (~900 LOC).
   - `tools/lib/compose.ts`, `plan.ts`, `generate.ts` (M4-13).
   - `tools/lib/pins.ts` and `tools/validate.ts --pin` (M4-14).
   - `__SERVER_DEV_COMMAND__` in `packagePlaceholders` (M4-15).
   - The headings check (M4-17).
   - `tools/tests/real-catalog.test.ts`.
4. **T3, CI** (~300 LOC, parallel with T2).
   - `.github/workflows/validate.yml`, `test-generated.yml`, `release.yml`: pinned setup-uv
     with cache.
   - `tools/test-generated.ts` and `tools/lib/run-case.ts`: `--with-app` (M4-16).
5. **T4, shared and existing templates** (~300 LOC).
   - `shared/gitignore/python.gitignore`, `shared/editorconfig/.editorconfig`.
   - `server/bun-express`: `container.migrate`, pins, case `stack-auth-off-postgres`, 2.2.0,
     CHANGELOG, `AGENTS.md` (migrate service).
   - `frontend/next`: placeholder, 1.1.0, CHANGELOG.
6. **P1, Python skeleton and core** (~1.3k LOC; parallel with T4).
   - `server/python-fastapi/`: `template.yaml`, `compose.yaml`, `tests/cases.yaml`.
   - `base/`:
     - `pyproject.toml`, `uv.lock`, `.python-version`, `Dockerfile` (python:3.14-slim, uv
       copied in, `uv sync --locked --no-dev --no-editable`, non-root, port from env),
       `.dockerignore` (excludes `.venv`), `.env.example`;
     - `src/app/{main,server,openapi}.py`, `config/`;
     - the core middleware: request id, request log, security headers, body limit, proxy
       hops, error handler, not found;
     - `services/utils/{error,openapi,clock}.py`, `services/logger.py`;
     - `api/health/`, plus tests.
   - `stacks/next-python-fastapi/stack.yaml` and `index.yaml` entries.
7. **P2, data path and infra** (~1.4k LOC).
   - `api/module/` (the reference CRUD) and `models/module/`.
   - `infra/{dependency,memory,pubsub,scheduler}.py`, `services/{db,cache,event}.py`,
     `services/utils/pagination.py`.
   - `middleware/rate_limit.py`.
   - `tests/store.py` (base seam), the import-linter contracts and the custom contract type,
     plus tests.
8. **P3a, security and sessions** (~1.2k LOC).
   - `services/security/{crypto,jwt,cookies,otp}.py`, `services/session.py`.
   - `middleware/{auth,role}.py`.
   - `services/communicate/` with its templates, plus tests.
9. **P3b, auth surface** (~1.3k LOC).
   - `api/auth/`, `api/user/`, `models/{auth,session,user}/`.
   - `infra/jobs/session_cleanup.py`, `infra/subscribers/send_welcome.py`.
   - The `auth` flag's `onlyPaths` and markers.
   - Cases `default`, `auth-off`, `stack`, `stack-auth-off`. Tests.
10. **P4, agents file and docs** (~700 LOC, parallel with P5a).
    - `base/AGENTS.md` (M4-17 headings, Python lists, data-layer prose for both variants).
    - `README.md`, `CHANGELOG.md` 1.0.0.
11. **P5a, Postgres foundation** (~900 LOC).
    - Overlay `src/app/infra/postgres.py`, `src/app/services/db.py`,
      `src/app/infra/migrations/0001-init.sql`, `src/app/infra/scripts/migrate.py`,
      `src/app/services/utils/postgres_error.py`.
    - `tests/store.py`, `tests/db/plugin.py`.
    - Base `@database` markers in `config/env.py`, `infra/dependency.py`, the error handler
      and `pyproject.toml`.
12. **P5b, Postgres services** (~1.2k LOC).
    - Overlay `api/module/service.py`, `api/user/service.py`, `services/session.py` (with
      the concurrent rotation test).
    - `tests/db/*`.
    - `capability.yaml` (commands, `container.migrate`, `flags.auth.onlyPaths`, pins).
    - Cases `postgres`, `auth-off-postgres`, `stack-postgres`, `stack-auth-off-postgres`.
    - The Postgres `AGENTS.md` blocks.
13. **T5, release docs.**
    - `README.md` (`bun tools/validate.ts --readme`), `CONTRIBUTING.md`,
      `docs/capabilities.md`.
    - ADR 0002 "As built"; the CHANGELOGs; v1.1.0 notes drafted for the annotated tag.

### Harness tasks (paths relative to this repository)

14. **H1, hooks** (from the branch cut, parallel with A0 and the catalog work; it does not
    depend on ADR 0002).
    - `.claude/hooks/lib/guardrail.mjs`, `.claude/hooks/block-secret-file-access.mjs`,
      `.claude/hooks/enforce-agent-boundaries.mjs` (M4-20).
    - `.claude/hooks/test/` with:
      - a bypass corpus that must block: every case named in M4-20, `uv run rm -rf x`,
        `uv run --directory backend rm -r x`, `uvx rimraf`, `poetry run git reset --hard`,
        `uv run python -c` with an env dump, `python -c "import os;print(os.environ)"`,
        `py -c`, `python3.14 -c`, `uv tool run`, `--env-file .env`, `--env-file=.env`;
      - a pass corpus: `uv run poe check`, `uv sync`, `python -m pytest`, and the plan 006
        false positives;
      - a regression set for the existing behaviour.
15. **H2, text, settings and bootstrap** (after P4; as run: before P4, see As built).
    - `.claude/settings.json` (M4-21).
    - M4-22 text in `AGENTS.md`, `.claude/rules/{naming,code-style}.md`,
      `.claude/skills/{writing-tests,api-design,database,error-handling,code-review,bootstrap-project}/SKILL.md`
      and `.claude/agents/{qa,backend}.md`.
    - The bootstrap skill checks the chosen templates' `tools` before scaffolding.
    - `AGENTS.md` prerequisites (a package's own tools come from its `template.yaml`) and
      the migrate wording (the service on the `app` profile).
    - `scripts/bootstrap.mjs` `printNextSteps`.
    - `README.md` (stacks, hook tests), `.doc/architecture.md` hints.
16. **H3, proofs** (after P5b). Scratch roots under `.superpowers/s009/`, bootstrapped with
    `--templates` from the catalog branch: V33 to V35.
17. **H4, lock bump** (after Eitan tags `v1.1.0`). `catalog.lock`, with a fresh-cache
    bootstrap (V36). This is a separate one-line PR.

### Eval

18. **E0, rubric** (written before any run) in
    `C:\Dev\Playground\AI\harness-eval\m4-rubric.md`. Each criterion scores 0, 1 or 2:
    - R1: every file sits where `backend/AGENTS.md` says, and `lint` is green.
    - R2: tests come first, and each endpoint has validation, not-found and auth-failure
      tests.
    - R3: no skip, focus, xfail or deselect.
    - R4: both contract files are regenerated and committed.
    - R5: a migration ships and `testDb` is green.
    - R6: the error envelope is used everywhere, with no FastAPI default bodies.
    - R7: the wire format is camelCase.
    - R8: commands come from `.fullstack/catalog.yaml` and are never spelled out.
    - R9: guardrail blocks, total and false positives.
    - R10: stops that needed a human.
    - R11: the DoD is met.
19. **E1, paired runs** on the same harness commit (`feat/python-fastapi` head, after the
    final reviews):
    - Two fresh clones, `harness-eval/py-m4` and `harness-eval/bun-m4`, with the workspace
      pre-trusted. The earlier run logged ignored `permissions.allow` entries.
    - `FULLSTACK_TEMPLATES_DIR` points at the catalog branch.
    - `prompt.md`'s todo brief, with the backend line set to "Python FastAPI" in one and
      "Bun" in the other (Auth none, Postgres: the `stack-auth-off-postgres` path).
    - Transcripts go to `harness-eval/logs/`.
    - Graded by the session with an Opus reviewer. Findings go into one fix wave, or into
      follow-ups.

## Validation

**Catalog**

- **V01** The tools pass their own gates.
  Proof: `cd tools && bun run check`.
- **V02** The catalog validates, the README matrix is current, and the bun and uv lockfiles
  are in sync.
  Proof: `bun tools/validate.ts`; `bun tools/validate.ts --lockfiles`.
- **V03** A pyproject template declaring `dependencies` or `scripts` is refused, and the
  lockfile check dispatches per adapter.
  Proof: `tools/tests/catalog.test.ts`, `lockfiles.test.ts` (the mini-py fixture).
- **V04** A `base/.venv` or `__pycache__` is neither copied nor scanned by the dry-run.
  Proof: `tools/tests/files.test.ts`, `dry-run.test.ts`.
- **V05** `.venv` and the caches are dropped before the move, and removal retries. A
  generated Python package passes `uv run poe check` right after generation, on Windows and
  on Linux.
  Proof: `generate.test.ts`; V13 locally on Windows and in CI.
- **V06** The preflight fails before staging on a missing or too-old tool, naming tool,
  found and min. It is skipped when post-generate is skipped.
  Proof: `tools/tests/preflight.test.ts`.
- **V07** The migrate service is derived with a shared image, environment, `restart: "no"`
  and `depends_on` in both directions. A rerun keeps it, and the clash check knows it.
  Proof: `compose.test.ts`, `plan.test.ts`, `generate.test.ts`.
- **V08** A shadowed base file edited without a re-pin fails `validate`, as does a missing or
  stale pin. `--pin` refreshes and prints the diff.
  Proof: `tools/tests/pins.test.ts`.
- **V09** `__SERVER_DEV_COMMAND__` resolves in both stacks, and the lone frontend is
  unaffected.
  Proof: `plan.test.ts`; the e2e in the V12 and V13 stack cases.
- **V10** A server agents file missing a cited heading fails `validate`.
  Proof: `tools/tests/catalog.test.ts`.
- **V11** Generating from the real catalog works without post-generate.
  Proof: `tools/tests/real-catalog.test.ts`.
- **V12** Every `bun-express` and `next` case, including the new `stack-auth-off-postgres`,
  passes with services and e2e.
  Proof: `bun tools/test-generated.ts --case server/bun-express/<each> --case frontend/next/<each> --e2e --with-services`.
- **V13** Every python-fastapi case passes with services and e2e: `default`, `auth-off`,
  `stack`, `stack-auth-off`, `postgres`, `auth-off-postgres`, `stack-postgres`,
  `stack-auth-off-postgres`.
  Proof: `bun tools/test-generated.ts --case server/python-fastapi/<each> --e2e --with-services`.
- **V14** The images build, the migrate one-shot exits 0, and the app answers health and
  ready, for both servers' `stack-postgres`.
  Proof: `bun tools/test-generated.ts --case server/<each>/stack-postgres --with-app`.
- **V15** Every `bun-express` test maps to a pytest node id or a ledger ruling, with zero
  unmapped.
  Proof: the ledger audit (a scratch script that lists `it(` names against the ledger rows).
- **V16** Each behaviour-table row is asserted in both templates (405, trailing slash,
  malformed JSON, non-JSON body, 413, 415, request id, headers, no `server` header, no docs
  routes, proxy hops).
  Proof: `tests/test_server.py` / `tests/server.test.ts` and siblings, named in ADR 0002.
- **V17** The Python `openapi.json` has no 422 or `HTTPValidationError`; it has ErrorBody;
  its component names equal the `bun-express` set; `uptimeSeconds` and `version` are
  required. The frontend's `check` passes after the contract is regenerated.
  Proof: `tests/test_openapi.py`; the `stack` case.
- **V18** A seeded cross-module `service` import fails `lint` with the contract's name.
  Proof: a probe recorded in the ledger, plus a green `lint` in every case.
- **V19** On Windows, the Python `postgres` case passes with services (`migrate`, `testDb`,
  none skipped).
  Proof: `bun tools/test-generated.ts --case server/python-fastapi/postgres --with-services`
  on Eitan's machine.
- **V20** The catalog PR is green: `validate` and every case job, with services and the
  smoke step.
  Proof: the PR's checks.
- **V21** The Python template has no skip, xfail or deselect outside `tests/store.py`.
  Proof: grep `server/python-fastapi` for `mark.skip|skipif|xfail|pytest.skip|deselect|-k `.

**Harness**

- **V30** The bypass corpus blocks, the pass corpus passes, and the regression set is
  unchanged.
  Proof: `node --test ".claude/hooks/test/*.test.mjs"`.
- **V31** The allow list gains exactly the three uv entries.
  Proof: `git diff <Base> -- .claude/settings.json`.
- **V32** No root file names a framework, a language-only idiom or a package-manager
  command without justification.
  Proof: grep `AGENTS.md .claude/rules .claude/agents .claude/skills` for
  `\.skip|\.only|kebab-case|config/env.ts|body-parser|bun run|uv run|:id`, with every hit
  justified.
- **V33** Bootstrapping `next-python-fastapi` with Postgres from the local catalog passes:
  backend `check`; `docker compose up -d --wait database`; `migrate`; `testDb`; frontend
  `check` and `testE2e`; then, with secrets exported,
  `docker compose --profile app up --build --wait` is healthy; and `git status` shows no
  `.venv` or caches.
  Proof: the commands in `.superpowers/s009/py-pg`.
- **V34** Bootstrapping `next-python-fastapi` without a database passes every gate, and the
  data-layer backlog line is written.
  Proof: `.superpowers/s009/py-plain`.
- **V35** Bootstrapping `next-bun-express` with Postgres still passes (regression).
  Proof: `.superpowers/s009/bun-pg`.
- **V36** A fresh-cache bootstrap from `v1.1.0` works after the lock bump.
  Proof: H4's proof run.

**Eval**

- **V40** The Python run meets the DoD. Its rubric score is at least the Bun control's on
  R1 to R8 and R11, and its guardrail false positives are no more than the control's. Every
  finding is fixed or listed as a follow-up.
  Proof: `harness-eval/m4-report.md` with both transcripts.

## Risks

- **psycopg async on Windows needs a selector loop, and Python 3.14 deprecates the policy
  API.** Mitigation: S1 covers all four loop owners, asyncpg is the fallback (OQ3), and V19
  runs on Windows because CI is Linux.
- **Parity drift across a ~9–10k-line port.** Mitigation: the ledger with a reviewer check
  per task, the behaviour table tested in both templates, tasks of at most ~1.5k LOC, and V15.
- **Images that never build** (Dockerfile, `.sql` packaging, the one-shot service).
  Mitigation: S1, then V14 in CI on every PR.
- **Hook changes open a bypass or block legitimate work.** Mitigation: raw-token scanning, a
  committed corpus (V30), narrow allow entries.
- **The FastAPI defaults leak into the contract** (422s, `X-Input` schemas, snake_case keys,
  the `server` header, docs routes). Mitigation: M4-7 to M4-9, V16, V17.
- **The uv version rewrites `uv.lock`'s revision, and `--lockfiles` fails.** Mitigation:
  `required-version`, and the setup-uv version pinned.
- **The eval comparison proves nothing.** Mitigation: same-commit paired runs, the rubric
  written first, a pre-trusted workspace, an identical brief except the backend line.
- **Scope is large, roughly twice milestone 3.** Mitigation: every task ends green, with
  `validate` and the cases written so far passing. If time runs short, P5a and P5b can ship
  as `v1.2.0` without reworking anything, because the overlay and its cases are additive.

## Rollout Order

1. G0. Then cut `feat/python-fastapi` in both repositories.
2. A0 runs alongside S1 and H1. Then G1.
3. T1.
4. T2 alongside T3.
5. T4 alongside P1.
6. P2, P3a, P3b.
7. P4 alongside P5a. Then P5b.
8. T5.

Each task gets a Sonnet review against the ledger and ADR 0002.

- **Catalog:** one Opus final review and a fix wave; V12–V19 locally; V20 after the push.
- **Harness:** H2 after P4, H3 after P5b, then one Opus final review and a fix wave.
- **Eval:** E0 before E1. E1 runs on both branch heads, then an eval fix wave, re-running the
  affected V items.
- **Release:** the two PRs into `dev`, with Eitan's yes. Eitan merges, merges `dev` →
  `main` and tags `v1.1.0`. Then H4.

## Rollback

- Each repository's change is one branch merged into `dev`; revert the merge commit there.
- Until H4, the harness lock still pins `v1.0.0`, so every bootstrap is untouched.
- After the tag, revert H4's one-line lock change. A bad catalog tag is superseded by a patch
  tag, never moved.
- Generated projects are standalone; nothing migrates existing data. The Postgres
  migrations in generated projects are forward-only, and dropping a database is a human's
  job (the `database` skill).

## As built

How the run differed from the sections above, which stay as planned. The full record is the
ledger (`.superpowers/sdd/009-2026-10-23-python-fastapi/progress.md`, git-ignored); ADR 0002's
As built covers the catalog design.

### Gates and decisions

- **G0.** It was still open when the plan went active. The branches were cut from `dev` first.
  Eitan merged catalog `dev` → `main` (PR #3, 1c6997a); the session tagged `v1.0.0` and opened
  the lock-bump PR into harness `dev` (#4) with a fresh-cache bootstrap proof. The harness `dev` →
  `main` PR follows #4.
- **G1.** ADR 0002 went through an Opus design review (3 Critical, 15 Important, all folded in)
  and was accepted by Eitan. It is the binding text for M4-1 to M4-19 and M4-23.
- **Python 3.14.** Confirmed by evidence: 3.15 lacks a `pyyaml` wheel.

### Task shape and order

- **Order.** Catalog tasks ran strictly one at a time. One harness task could run beside them,
  because the two repositories share no files.
- **H2 before P4.** H2 ran before P4: the headings it points at are fixed by M4-17. P4 then
  completed the forbidden-forms lists both packages' `AGENTS.md › Tests` must carry.
- **P5a and P5b merged into one task, P5.** Listing the provider makes `validate` require both
  Postgres cases at once.
- **P3a declared the `auth` flag,** and the auth models moved into P3a.
- **T2 took bun-express's pins and `container.migrate`,** which its own checks needed.

### Proofs and reviews

- **Linux gates from P1 on.** Every Python task ran its gates on Linux (`python:3.14-slim`) as well
  as Windows, after P1's Windows-only proof missed a Linux-only test failure.
- **H3** (V33–V35) passed, run by the session from a script.
- **The catalog final review** was split into two Opus reviewers: machinery and docs, and the
  Python template.
- **Final reviews and fix waves.** Each repository got one fix wave and an Opus scoped re-review.
  - **The harness review** found two critical hook bypasses: a tokenizer regression on escaped
    quotes, and uv's own `-m` and `-` channels.
  - **The catalog reviews** found no critical issue. Their important findings included the uv 0.13
    window, first-cookie precedence, the hashing bound, the shutdown budget and smoke diagnostics.
  - **Targeted addenda followed in both repositories:** four bash-escape spellings found by a
    controller hunt in the harness; a shutdown-starvation regression and a `detach` warning in the
    catalog.
- **Rulings in the fix waves.**
  - uv 0.12.23 up to, not including, 0.14, with a bounded preflight.
  - The development and test database host is `127.0.0.1`.
  - One shutdown budget inside Compose's 10 s grace period.
- **E1 was not run.** Eitan chose to skip the eval. V40 stays open as a follow-up; E0's rubric and
  paired prompts are in `harness-eval/` for a later run.
- **Eitan's leftovers** (the hooks refuse volume removal): the Docker volumes
  `lockproof_database-data`, `pgdemo_database-data`, `lindemo_database-data`,
  `py-pg_database-data`, `bun-pg_database-data`, and the agent worktree directories under
  `.claude/worktrees/`.
- Closed 2026-10-24, on Eitan's instructions to merge, promote, tag and bump:
  - harness #4 and #5 merged into `dev` (babe267, 283e4ee), then `dev` into `main` (#6,
    a853c82). #5 merged before the promotion, so `main` took plans 008 and 009 together;
  - catalog #4 merged into `dev` (7950ddf), then `dev` into `main` (#5, bdadf31); `v1.1.0` was
    tagged there and published by `release.yml`;
  - `catalog.lock` bumped to it (H4), with a fresh-cache bootstrap proof (V36) in the lock PR.

  V40 stays open as a follow-up.

