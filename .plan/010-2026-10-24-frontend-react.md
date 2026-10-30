# frontend/react (Vite SPA), the single and split deploy modes, the react stacks, catalog v1.2.0

Status: done
Owner: Eitan
Last updated: 2026-10-24
Approval: Eitan, 2026-10-24 ("initiate the new plan"), with the Open Questions' recommendations;
ADR 0003 is approved separately at G1.
G1 (2026-10-24): ADR 0003 accepted (catalog 8c04d08). It binds over this plan's decision summaries.
Its deltas: React Router 8.5.0 instead of 7; OQ4 is the `service:` context with a build-only
(`scale: 0`) frontend service, which needs Compose 2.35.0 or later, not 2.17; a new catalog task N1
fixes `next`'s ESLint zones (7 of 11 seeded violations missed) and audits `bun-express`'s.
Direction set in conversation on 2026-10-24:

- Milestone 5 follows ADR 0001 › Delivery order.
- A project with an SPA starts as one container and can move to another topology later, when
  scale or hosting calls for it.
- The SPA shape is defined once, for React now and for Vue and Angular later.

Branch: `feat/frontend-react` in both repositories, cut from `dev` after G0
Base: harness adebb89 (`main`), catalog 0b97243 (`main`). G0 fast-forwards `dev` to these.
Stages: harness and catalog only. No role agents run. The interactive session drives:

- a Sonnet implementer per task, with a Sonnet review per task;
- one Opus final review per repository.

It ends in one pull request per repository into `dev`.

## Goal

Milestone 5 adds the first single-page-app frontend and lets a project choose how it ships.
After it:

- **New stacks.**
  `bun tools/generate.ts --stack react-python-fastapi [--deploy single|split] [--capability database=postgres]`
  writes a project whose `frontend/` is React on Vite. Its typed client is generated from the
  server's `openapi.json`. The same works for `react-bun-express`.
- **`single`, the default for an SPA stack.** One image runs the API and serves the built SPA
  on one port. There is no CORS, no API URL in the bundle and no second container.
- **`split`.** The frontend gets its own small static-server image, which proxies `/api` to
  the server. Code is identical in both modes; only Dockerfiles and Compose differ. Next
  stacks are always `split`.
- **Both server templates** serve a built frontend when `STATIC_DIR` is set, under one tested
  behaviour table. Unset, they behave exactly as today.
- **The SPA contract is written once,** in `docs/conventions.md` and ADR 0003. Vue and Angular
  templates implement it later.
- **CI proves every mode.** It builds the images, smokes them, and runs the e2e suite with the
  axe scan against the running container.
- **The harness** asks for the deploy mode at the bootstrap and records it. A new `deployment`
  skill moves an existing project between `single`, `split` and a static host. Root files stop
  assuming a server-rendered frontend.

The catalog ships as `v1.2.0` and the harness lock follows it.

## Scope

**In, catalog side** (`fullstack-templates`):

- ADR 0003, `docs/adr/0003-spa-and-deploy-modes.md`, with decisions M5-1 to M5-10. Also:
  - `docs/conventions.md`: the SPA frontend contract and the deploy modes;
  - an ADR 0001 amendment for v1.2.0.
- Machinery:
  - the `static` manifest field;
  - the `--deploy` option and its answers and provenance fields;
  - the reserved `single` marker selection;
  - the `__FRONTEND_DIR__` placeholder;
  - per-mode Compose assembly;
  - the headings check extended to frontend templates and to `Deployment`;
  - per-mode `test-generated --with-app` with e2e against the container;
  - a `deploy` field on cases.
- `frontend/react` 1.0.0: `base/`, the Dockerfile with `dist` and `serve` targets, the static
  server config, the Compose fragment, the cases, `AGENTS.md`, `README.md`, `CHANGELOG.md`.
- `server/bun-express` 2.3.0 and `server/python-fastapi` 1.1.0:
  - static serving behind `STATIC_DIR`, with its tests;
  - `@single` lines in the Dockerfile and the Compose fragment;
  - `AGENTS.md › Deployment`.
- `frontend/next` 1.1.1: `AGENTS.md › Deployment` only.
- `stacks/react-python-fastapi/` and `stacks/react-bun-express/`, plus their `index.yaml`
  entries.
- Docs: `README.md` (generated matrix), `CONTRIBUTING.md` (adding an SPA template, refreshing
  the React base), the catalog's `CLAUDE.md` (the frontend shape and the deploy modes).

**In, harness side** (this repository):

- `scripts/bootstrap.mjs`: pass `--deploy` through and print next steps per mode.
- `bootstrap-project` skill: ask the deploy mode when the stack's frontend declares `static`,
  write the client model per frontend kind, and fill the Deployment line.
- The new `.claude/skills/deployment/SKILL.md` and its row in `AGENTS.md › Skills`.
- Neutral text for an SSR or SPA frontend in:
  - `AGENTS.md` (Stack, Architecture);
  - `.doc/architecture.md` (Primary Components, Data Flow, Auth client model, Deployment);
  - the `error-handling` and `writing-tests` skills;
  - `README.md`.
- This plan.
- After the tag: the `catalog.lock` bump to `v1.2.0`.

**Out:**

- `frontend/vue` and `frontend/angular`. This milestone only writes the contract they follow.
- A generated static-host (CDN) mode. The `deployment` skill documents it, because it changes
  the CORS and cookie security model per product (OQ10).
- Host-specific deploy files (Fly, Render, Railway, Cloud Run, Kubernetes manifests).
- An auth UI in the template. Like `next`, it ships only the `health` feature.
- Server-side rendering for React, and React Router framework mode.
- MongoDB, Redis, workers, messaging (milestones 6 to 8).
- Updating existing projects to newer templates (ADR 0001 non-goal). The deploy switch is a
  planned project change through the skill, not a regeneration.
- An unattended eval. Plan 009's V40 stays the open eval follow-up.
- The `migrate` env-reader follow-up from ADR 0002. It stays in the catalog backlog.

## Assumptions

- **G0 has not run.** In both repositories `dev` is behind `main`:
  - catalog `origin/dev` 7950ddf against `main` 0b97243;
  - harness `origin/dev` 884968e against `main` adebb89.

  `main` contains `dev` in both, so G0 is a fast-forward, not a rewrite.
- ADR 0001, ADR 0002, their amendments and the rulings of plans 008 and 009 stand. This plan
  reopens none of them.
- The ADR 0001 frontend contract (D4) already allows the SPA shape: "the data access
  (`server/` for a server-rendered framework, `api/` otherwise)".
- **Generator facts this plan builds on** (catalog `tools/lib/`):
  - markers already take a reserved `server` selection (`plan.ts` `SERVER_SELECTION`), applied
    to package files and Compose fragments alike;
  - cases already carry `withApp`;
  - the fixture catalog has `frontend/mini-ui`;
  - `dry-run.ts` varies `server` like a flag, then removes it and passes it as `hasServer`.
    `single` needs the same handling, restricted to combinations where `server` is true.
- **Overlay facts** (checked 2026-10-24). Neither Postgres overlay shadows a `Dockerfile`, a
  `compose.yaml`, the server's assembly file or its env module. So the `@single` lines and the
  static mount live in `base/` only, and S2 is expected to move no pin.
- **CSP facts.** python-fastapi's `middleware/security_headers.py` already sends helmet's
  default CSP string, so both servers send the same CSP on static responses.
- **Next headings.** `frontend/next/base/AGENTS.md` already has Adding a feature, Styling,
  Errors and Tests. Next 1.1.1 adds only Deployment.
- The auth model in `.doc/architecture.md` is unchanged. The server's cookies are already
  httpOnly, `SameSite=Lax` and `Secure` outside development (`services/security/cookies.ts`).
  In `single` and `split` the browser and the API share one origin, so CORS stays off.
- Local machine as recorded in plan 009: Bun 1.4.0, Node 24.15, uv 0.12.23, Docker 29.7.
  Compose `additional_contexts` needs Compose 2.17 or later.
- **Work in another repository.** Work in `C:\Dev\Playground\AI\fullstack-templates` starts
  only after Eitan approves this plan, which names that path.
- **The user's rules hold:**
  - Sonnet for implementers and task reviewers, Opus for final reviews;
  - Conventional Commits;
  - no commit, push, PR, merge or tag without Eitan's explicit yes at execution time;
  - agents never rewrite history;
  - hook changes, if any turn out to be needed, are made in a worktree only.

## Open Questions

1. **Which router and data library does the React template use?** React Router 7 in data mode
   gives per-route `loader`, `action`, `ErrorBoundary` and `HydrateFallback`. Those mirror
   Next's loaders, server actions, `error.tsx` and `loading.tsx`, so an agent finds the same
   shape in both frontends, and only one library is added. TanStack Query adds a cache the
   template does not need. Recommended: React Router 7 data mode, no TanStack Query; a product
   adds a cache library by plan.
2. **What is the option called, and what is its default?** Recommended: `--deploy single|split`.
   The default is `single` when the stack has a server and its frontend declares `static`, and
   `split` otherwise. `single` is refused for Next and for a lone frontend.
3. **Is the server's static serving gated at generation or at runtime?** Recommended: always
   shipped in both server templates and inert unless `STATIC_DIR` is set. Only Dockerfile and
   Compose lines carry `@single` markers. Moving between modes is then configuration, and no
   case multiplies.
4. **How does the single image get the SPA's build?** The preferred shape keeps the build in
   the frontend's Dockerfile (its `dist` target), and the server build reads it through a
   Compose additional context (`service:` reference). The fallback is a shared `@single` build
   stage reading the frontend directory as a local named context. S1 decides, and ADR 0003
   records the choice.
   - `service:` is chosen only if S1 proves it on both Windows and Linux. Windows is a
     first-class host (ADR 0001 › Constraints), so a Windows failure picks the fallback; it
     does not make `single` Linux-only. An inconclusive S1 also picks the fallback.
   - With the fallback, the frontend's Compose fragment is not assembled in `single`.
   - With `service:`, it is assembled as a build-only service (`build.target: dist`, no
     ports, never started by `--profile app up`). M5-4, V04 and the `deployment` skill's
     steps then follow that shape.

   Recommended: the `service:` reference if S1 proves it on both hosts, otherwise the
   local-context fallback.
5. **Which static server runs in the split frontend image?** Recommended:
   `nginxinc/nginx-unprivileged`. It is the industry default, non-root out of the box, and
   templates its port from the environment. Caddy is the alternative if S1 finds the SPA
   fallback and proxy config simpler there.
6. **Is `react-bun-express` added as well as `react-python-fastapi`?** Recommended: yes. It is
   one `stack.yaml`, and without it bun-express's static serving has no end-to-end or image
   proof.
7. **Where does the move between topologies live?** Recommended: a harness `deployment` skill
   for the stack-neutral procedure. Each template's `AGENTS.md › Deployment` holds its own
   files and lines, and the headings check enforces it.
8. **What is `TRUST_PROXY`'s default in `single`?** Recommended: `false` in the `single` Compose
   fragment, because the container is the edge locally and a default of 1 lets any caller pick
   its rate-limit key. The deployment skill and the Deployment line require the production
   hop count, which is 1 behind a PaaS edge. `split` keeps 1, because nginx counts.
9. **Which dev port does the React template use?** Recommended: 5173, Vite's convention. A
   port other than 3000 also proves the frontend port flows through the generator.
10. **Is a static-host (CDN) mode generated?** Recommended: no. A frontend on another origin
    needs `CORS_ORIGINS`, cross-site cookies (`SameSite=None`, a cookie domain) and a CSRF
    stance. That is a product security decision, so the `deployment` skill documents it as a
    planned change.

## Steps

No product API changes. The OpenAPI document is unchanged: static responses sit outside
`/api` and outside the contract. There is no Contract subsection.

### Gates

- **G0 (Eitan, or the session on his yes):** fast-forward `dev` to `main` in both
  repositories, then cut `feat/frontend-react` in both.
- **G1 (Eitan):** approve ADR 0003 before T1 and every later catalog task. H1 does not depend
  on the ADR and may start with A0.
- **S1 spike** (time-boxed to half a day, alongside the ADR draft). Scratch work only; findings
  go into ADR 0003. On Windows (Docker Desktop) and Linux, it proves:
  - **image assembly.** OQ4: a Compose `service:` additional context to a build-only service
    at a `dist` target, with that service never started by `--profile app up`. It also covers
    the fallback, a local-path named context. Record whether `.dockerignore` applies to a named
    context;
  - **static serving.** Express 5 static files and fallback, and the Starlette equivalent, with
    HEAD, traversal and dotfiles, against the rows in M5-5;
  - **CSP in the browser.** Helmet's default CSP, including `upgrade-insecure-requests`, lets
    the Vite production build load in Chromium over `http://localhost` from the container;
  - **the client in tests.** `openapi-fetch` with `baseUrl: window.location.origin` works
    under Vitest jsdom with a stubbed `fetch`;
  - **versions.** The React set resolves and locks under Bun 1.4: React 19, React Router 7,
    Vite, `@vitejs/plugin-react`, `@tailwindcss/vite`, Vitest 5, Playwright;
  - **the split image.** nginx-unprivileged with a templated port, the SPA fallback, the `/api`
    proxy and the security headers, running non-root.

### Decisions (ADR 0003 records these; implementers do not reopen them)

- **M5-1 The SPA frontend contract** (conventions.md › Frontend, single-page app).
  - **`src/app/` is routing only.**
    - `routes.tsx` is the route table.
    - The root has `layout.tsx` and `not-found.tsx`.
    - Each route segment has `page.tsx`, `loading.tsx` (the hydrate and pending fallback) and
      `error.tsx` (the route's error boundary).
    - `src/main.tsx` mounts the router and the toaster and nothing else.
  - **`feature/<name>/` holds `ui/`, `api/` and `model.ts`.**
    - `api/` holds the route loaders and actions.
    - Only `feature/*/api/` imports `lib/api/client` (lint).
    - Import direction is `app → feature → shared, lib`.
  - **The API is always reached at relative `/api/*`** on the page's own origin, in every deploy
    mode. In development, the dev server proxies `/api` to the server's port. No API URL is
    compiled into the bundle, and there is no CORS.
  - **`build` writes `dist/`,** with `index.html` at its root and hashed files under
    `dist/assets/`. The manifest declares `static: { out: dist }`.
  - **`src/env.ts` is the only reader of `import.meta.env`** (lint). It holds browser-visible
    values only and never a secret.
  - **E2E.** When `E2E_BASE_URL` is set, Playwright tests that URL and starts no web server;
    otherwise it starts the server's dev command and the dev server.
  - **The Dockerfile has two targets:** `dist` (the built files only, at `/dist`) and the
    default `serve` (the split-mode static server).
  - **The agents file has these headings:** layer map, Adding a feature, Styling, Errors,
    Tests, Deployment.
- **M5-2 The React template.**
  - **Libraries:** React 19 (the version `next` pins), React Router 7 data mode (OQ1), Vite with
    `@vitejs/plugin-react`, Tailwind 4 through `@tailwindcss/vite`, sonner, lucide-react,
    openapi-fetch with openapi-typescript, zod, Vitest with Testing Library and jsdom,
    Playwright with `@axe-core/playwright`, Prettier.
  - **Lint:** ESLint with typescript-eslint `strictTypeChecked`, react-hooks and jsx-a11y.
  - **Versions** are current stable at R1, verified against the registry, locked in `bun.lock`
    and listed in ADR 0003. They are never written from memory.
  - **Manifest:**
    - `http: { port: 5173, health: / }`;
    - `defaultStack: react-python-fastapi`;
    - the same command vocabulary as `next`, with `contract` running `bun run api:types`.
  - **Styling:** tokens are CSS variables in `src/app/globals.css`, exposed with `@theme
    inline`, as in `next`.
- **M5-3 The client.** `lib/api/client.ts` builds
  `createClient<paths>({ baseUrl: window.location.origin, fetch: (r) => globalThis.fetch(r) })`.
  - The origin is resolved explicitly, because undici's `Request` refuses a bare path.
  - Requests carry the session cookies by fetch's same-origin default.
  - The CSRF stance is recorded in ADR 0003: same origin, `SameSite=Lax` cookies, JSON-only
    bodies and CORS off mean a cross-site page cannot send an authenticated mutation.
- **M5-4 Deploy modes.**
  - **Inputs.** `--deploy single|split` on the CLI, `deploy` in the answers JSON, and `deploy` in
    `.fullstack/catalog.yaml` (an optional provenance field; `schemaVersion` stays 1).
  - **`single`** (OQ2 default):
    - the server's image holds the API and the SPA's `dist/`, and serves both on the server's
      port;
    - the frontend gets no runtime Compose service; whether its fragment exists as a
      build-only service follows OQ4;
    - every package's markers see the reserved selection `single` as true. It is never true
      in a plan without a server.
  - **`split`:** each package has its own image, as today.
  - **Refusals.** `--deploy single` with a frontend that lacks `static`, or with no server in
    the plan, fails and names the reason. An unknown value fails.
  - **`__FRONTEND_DIR__`** resolves to the frontend's directory, for the server's fragment.
  - **The mode is fixed at generation.** Changing it later is a project change through the
    `deployment` skill. Provenance stays the generation record and is not edited.
    - `.doc/architecture.md › Deployment` holds the current mode, and wins when it differs
      from provenance. Provenance says what was generated; the doc says what runs now.
  - **Ports.** The frontend's `http.port` is always its dev-server port, and in `split` also
    its container's port. In `single`, the deployed app and the app smoke use the server's
    port. `printNextSteps` names the frontend's dev URL in both modes.
  - **`static.out`.** The loader checks only that it is present. The app smoke proves that the
    `dist` target holds an `index.html` (M5-8).
- **M5-5 Static serving in both servers** (OQ3).
  - **Configuration.** The env module reads `STATIC_DIR` once. Unset, nothing is mounted. Set in
    production without an `index.html`, boot fails fast.
  - **Order.** It is mounted after the API routes and `/openapi.json` and before not-found, and
    never under `/api`.
  - **Behaviour table** (identical in both templates, each row tested in both):

    | Request | Response |
    | --- | --- |
    | GET or HEAD of an existing file | The file. `assets/*` gets `Cache-Control: public, max-age=31536000, immutable`; `index.html` gets `no-cache`. |
    | GET or HEAD of an extension-less path outside `/api` | `index.html`, `no-cache`. The SPA's router renders it, its own not-found included. |
    | A path with an extension and no file | The 404 envelope. |
    | `/api/*` with no route | The 404 envelope, unchanged. |
    | Another method on a non-API path | The 404 envelope, unchanged. |
    | A dotfile, an encoded traversal or a directory | The 404 envelope. Never a listing. |

    Every static response carries the security headers, CSP included.
  - **Files.**
    - bun-express: `src/middleware/static.ts`, the mount in `src/server.ts`, the `STATIC_DIR`
      parse in `src/config/env.ts` and `.env.example`, and the ESLint zone.
    - python-fastapi: `src/app/middleware/static_files.py`, the mount in `src/app/server.py`,
      `config/env.py`, `.env.example` and the import-linter contracts.
  - **No compression** in the server; the host's edge compresses. ADR 0003 lists it under "left
    to the deployment".
- **M5-6 The single image and its Compose service.**
  - **The SPA build stays in the frontend's Dockerfile** (`dist` target).
  - **The server's Dockerfile** gains `@single` lines that copy `/dist` from the `spa` context
    to `public/` beside the app and set `STATIC_DIR` to that path. The mechanism follows OQ4
    and S1.
  - **The server's Compose fragment** gains `@single` and `@nosingle` lines:
    - `build.additional_contexts.spa`;
    - `TRUST_PROXY: ${TRUST_PROXY:-false}` in `single`, where `split` keeps
      `${TRUST_PROXY:-1}` (OQ8);
    - **Ports.**
      - In `single`, `ports: ["__PORT__:__PORT__"]`. The server is now the public edge, as the
        frontend container is today, and with `TRUST_PROXY` false no caller can choose its own
        client IP.
      - In `split`, the loopback-only `127.0.0.1` publishing stays.
    - **Comments.** Each mode gets its own comments in place of the ones that say "the Next.js
      server counts" and that justify loopback by `TRUST_PROXY=1`.
  - **Unchanged:** the derived `<dir>-migrate` service, which shares the image name and keeps
    working.
- **M5-7 The split frontend image** (OQ5).
  - nginx-unprivileged, non-root, listening on `__PORT__`.
  - Hashed assets are immutable and `index.html` is `no-cache`. An extension-less path falls
    back to `index.html`.
  - `/api/` is proxied to `__SERVER_DIR__:__SERVER_PORT__` with `X-Forwarded-For`. The proxy
    lines carry `@server`, so a lone frontend has none.
  - Static responses carry the same security headers as the server's.
  - The backend keeps `TRUST_PROXY` 1 here, because nginx counts as the hop.
- **M5-8 Proof per mode** (`test-generated --with-app`).
  - **`single`:**
    - health and ready on the server's port;
    - `/` and a deep link return `index.html`;
    - `/api/nope` returns the JSON 404;
    - the image's `public/` holds only built files (no `src/`, `.env*` or `*.map`);
    - then the frontend's `testE2e` with `E2E_BASE_URL` pointed at the container.
  - **`split`:** the same through the frontend's port, plus `/api/health` through the proxy, and
    the frontend container running as a non-root user.
- **M5-9 The `deployment` skill and `AGENTS.md › Deployment`** (OQ7).
  - **Headings check.** The catalog's check extends to frontend templates (Adding a feature,
    Styling, Errors, Tests, Deployment) and adds Deployment to servers.
  - **The harness skill covers:**
    - choosing a mode;
    - single → split and split → single, as file-level steps that cite each package's
      `AGENTS.md › Deployment`, the root `docker-compose.yml` and `TRUST_PROXY`;
    - a static host (CDN) as a documented security change (OQ10);
    - what scaling actually needs: state out of process (the database, the cache task) and jobs
      on exactly one replica.
  - **Where the mode lives.** The current mode is recorded in `.doc/architecture.md ›
    Operational Concerns › Deployment`, with a change-log line when it moves.
- **M5-10 Versions.**
  - catalog `v1.2.0`: additive, so `schemaVersion` stays 1 and the harness's
    `SUPPORTED_SCHEMA_VERSION = 1` holds;
  - frontend/react 1.0.0;
  - bun-express 2.3.0;
  - python-fastapi 1.1.0;
  - next 1.1.1.

### Execution protocol

As in plan 009 › Execution protocol: a self-contained brief per dispatch (goal, read first,
binding M5 numbers, paths, done-when commands, report). The standing rules hold:

- verify every third-party API against the installed package or its current docs;
- tests first;
- no skip or focus;
- no edits outside the listed paths;
- stop and report when a decision cannot be met.

**Behaviour ledger.** Each M5-5 row maps to one test name per server, and V06 audits it. It
lives in `.superpowers/sdd/010-2026-10-24-frontend-react/progress.md` (git-ignored).

Template gates run in a generated case with `--keep`, never inside a raw `base/` (catalog
`CLAUDE.md`). Python tasks also run their gates on Linux, as the plan 009 As built requires.

### Catalog tasks (paths relative to `fullstack-templates/`)

1. **A0, ADR 0003** (with S1).
   - `docs/adr/0003-spa-and-deploy-modes.md`: M5-1 to M5-10, the static behaviour table, the S1
     findings and the versions.
   - `docs/conventions.md`: the SPA contract and the deploy modes.
   - `docs/adr/0001-catalog-architecture.md`: the v1.2.0 amendment.
   - Gate G1 follows.
2. **T1, machinery** (~800 LOC: the dry-run's reserved-selection handling is generalised from
   `server` to `server` and `single`).
   - Schemas:
     - `schemas/template.schema.json` gains `static` (frontend only);
     - `schemas/cases.schema.json` gains `deploy`;
     - `schemas/provenance.schema.json` gains an optional `deploy`.
   - `tools/lib/cli.ts` and `plan.ts`: `--deploy`, answers, the default and the refusals, and
     the reserved `single` selection in `selectionsFor`.
   - `tools/lib/generate.ts`: `FRONTEND_DIR` in `packagePlaceholders`, and skipping the
     frontend's fragment in `single`.
   - `tools/lib/dry-run.ts`: `single` varied like `server`, and skipped when `server` is false.
   - `tools/lib/provenance.ts`.
   - The headings check (M5-9) in `tools/lib/catalog.ts`.
   - Fixture: `tools/tests/fixtures/catalog/frontend/mini-spa/` (declares `static`), plus a
     stack using it.
   - Tests in `tools/tests/{plan,generate,compose,dry-run,catalog,provenance,generate-cli}.test.ts`.
3. **T2, the per-mode app smoke** (~300 LOC, parallel with S2).
   - `tools/lib/run-case.ts` and `tools/test-generated.ts`: the M5-8 checks and e2e against the
     container.
   - `tools/tests/run-case.test.ts`.
4. **S2, static serving in both servers** (~500 LOC with tests).
   - The M5-5 files in `server/bun-express/base/` and `server/python-fastapi/base/`.
   - Tests:
     - bun-express: `tests/middleware/static.test.ts`;
     - python-fastapi: `tests/middleware/test_static_files.py`.
   - The `@single` lines in both `Dockerfile`s and `compose.yaml`s (M5-6).
   - Pins: none expected (see Assumptions, overlay facts). If `validate` reports a moved pin,
     reconcile the overlay copy and re-pin with `validate --pin`, reading the diff.
   - `AGENTS.md › Deployment` in both.
   - Versions, CHANGELOGs and `index.yaml`.
5. **R1, the React base** (~1.2k LOC without the lockfile).
   - `frontend/react/template.yaml` and `tests/cases.yaml`.
   - `base/`:
     - `package.json`, `bun.lock`, `vite.config.ts` (the dev proxy from `__SERVER_PORT__`),
       `tsconfig*.json`, `eslint.config.mjs` (M5-1 zones, the `import.meta.env` rule),
       `.prettierrc`, `vitest.config.mts`, `playwright.config.ts` (the M5-1 E2E rule,
       `__SERVER_DEV_COMMAND__`), `index.html`, `.env.example`;
     - `src/main.tsx`, `src/env.ts`;
     - `src/app/{routes,layout,not-found}.tsx`, `src/app/globals.css`, and
       `src/app/home/{page,loading,error}.tsx`;
     - `src/feature/health/{model.ts,api/health.ts,ui/health-status.tsx,ui/refresh-button.tsx}`;
     - `src/lib/api/{client.ts,schema.d.ts}` (generated from python-fastapi, per D2's
       lone-frontend rule);
     - `src/shared/{lib,ui}/`;
     - `tests/unit/*`, `tests/e2e/smoke.spec.ts`.
6. **R2, packaging and stacks** (~300 LOC).
   - `frontend/react/base/Dockerfile` (`dist` and `serve` targets), `.dockerignore`, the nginx
     config, and `frontend/react/compose.yaml`.
   - `stacks/react-python-fastapi/stack.yaml`, `stacks/react-bun-express/stack.yaml`, and the
     `index.yaml` entries.
   - **Cases:**

     | Case | Stack | Deploy | Extras |
     | --- | --- | --- | --- |
     | `default` | react-python-fastapi | `single` | `withApp` |
     | `split` | react-python-fastapi | `split` | `withApp` |
     | `bun` | react-bun-express | `single` | `withApp` |
     | `postgres` | react-python-fastapi | `single` | Postgres, `withApp` |
     | `alone` | none | none | |

     There is no react `auth-off` case. The React template has no flags, and the server's
     `auth=false` cases already cover the server. Static serving touches no auth code, and the
     dry-run covers every `single` × `auth` marker combination.

   - `frontend/react/{AGENTS.md,README.md,CHANGELOG.md}`. `base/AGENTS.md` uses the M5-1
     headings.
7. **T3, release docs.**
   - `README.md` (`bun tools/validate.ts --readme`), `CONTRIBUTING.md`, the catalog `CLAUDE.md`.
   - `frontend/next` 1.1.1: `AGENTS.md › Deployment`, CHANGELOG.
   - ADR 0003 As built.
   - v1.2.0 notes, drafted for the annotated tag.

### Harness tasks (paths relative to this repository)

8. **H1, bootstrap passthrough** (alongside A0).
   - `scripts/bootstrap.mjs`: `--deploy` in the usage text, `parseArgs` and the generator
     argv.
   - `printNextSteps`:
     - in `single`, one app service and the frontend's dev URL;
     - in `split`, today's text.
9. **H2, text and skills** (after T1 fixes the option and R2 fixes the headings).
   - **`bootstrap-project` skill:**
     - in section 2, ask the deploy mode when the chosen frontend's `template.yaml` has
       `static`, with a two-line tradeoff, and map the answer to `--deploy`;
     - in section 1, the Auth none client model per frontend kind;
     - in section 4, the dev-server check wording;
     - in section 5, fill `Deployment` and the Stack row.
   - **`.claude/skills/deployment/SKILL.md`** (M5-9), plus its row in `AGENTS.md › Skills`.
   - **`AGENTS.md`:**
     - Stack: Docker Compose runs one image per deployable, per the deploy mode;
     - Architecture: two packages and one contract, where the deploy mode decides one image or
       two.
   - **`.doc/architecture.md`:**
     - Primary Components without SSR or port assumptions;
     - Data Flow steps 1 to 4 phrased through the feature's data layer;
     - the Auth client model as a FILL the bootstrap writes per frontend kind;
     - Deployment gains `Deploy mode: <!-- FILL -->` and the `TRUST_PROXY` hop count.
   - **`error-handling` and `writing-tests` skills:** "server action" becomes the package's
     action.
   - **`README.md`:** the stacks and modes.
10. **H3, proofs** (after R2). Scratch roots under `.superpowers/s010/`, bootstrapped with
    `--templates` from the catalog branch: V30 to V36.
11. **H4, lock bump** (after Eitan tags `v1.2.0`). `catalog.lock`, with a fresh-cache bootstrap
    (V37). A separate one-line PR.

## Validation

**Catalog**

- V01 — The tools pass their own gates — proof: `cd tools && bun run check`.
- V02 — The catalog validates: the README matrix is current, the lockfiles are frozen, and
  every marker combination, including `single` on and off, dry-runs — proof:
  `bun tools/validate.ts`; `bun tools/validate.ts --lockfiles`.
- V03 — `--deploy` behaves as M5-4: an SPA stack defaults to `single` and a Next stack to
  `split`; `single` is refused, with the reason, for Next and for a lone frontend; an unknown
  value is refused; answers and provenance carry the mode — proof: `tools/tests/plan.test.ts`,
  `generate-cli.test.ts`, `provenance.test.ts`.
- V04 — In `single`, the frontend has no runtime Compose service (and a build-only one only
  under OQ4's `service:` choice). The server's service has `spa`, `STATIC_DIR`, `TRUST_PROXY`
  false and the all-interface port. `__FRONTEND_DIR__` resolves. A Next stack's output
  differs from v1.1.0 only by the inert static-serving files and the Deployment sections — proof:
  `tools/tests/compose.test.ts`, `generate.test.ts`, `real-catalog.test.ts`, and a recursive
  diff of `next-python-fastapi` generated from `v1.1.0` and from the branch.
- V05 — A frontend agents file missing Adding a feature, Styling, Errors, Tests or Deployment
  fails `validate`, and so does a server agents file missing Deployment — proof:
  `tools/tests/catalog.test.ts`.
- V06 — Every M5-5 row is asserted in both servers, and every pre-existing server test passes
  with `STATIC_DIR` unset — proof: `tests/middleware/static.test.ts`,
  `tests/middleware/test_static_files.py`, and the behaviour ledger audit.
- V07 — With `STATIC_DIR` set in production and no `index.html`, both servers refuse to boot
  with a clear message — proof: the env tests in both templates.
- V08 — Lint fails on a seeded import of `lib/api/client` from `ui/`, on a cross-feature `ui/`
  import, and on `import.meta.env` outside `src/env.ts`, each with its message — proof: probes
  recorded in the ledger, and a green `lint` in every react case.
- V09 — Every react case passes `check` and `testE2e` with the axe scan, with services where
  the case has them: `default`, `split`, `bun`, `postgres`, `alone` — proof:
  `bun tools/test-generated.ts --case frontend/react/<each> --e2e --with-services`.
- V10 — In `single`, one container serves `/`, a deep link, `/api/health` and
  `/api/health/ready`, and `/api/nope` is the JSON 404. Its `public/` holds no `src/`, `.env*`
  or `*.map`. The e2e suite passes against it through `E2E_BASE_URL`. In `postgres`, the
  migrate one-shot exits 0 first — proof:
  `bun tools/test-generated.ts --case frontend/react/<default|bun|postgres> --e2e --with-services --with-app`.
- V11 — In `split`, the frontend container runs as a non-root user, serves the SPA with the
  security headers on `index.html`, and proxies `/api/health`; the e2e suite passes against it
  — proof: `bun tools/test-generated.ts --case frontend/react/split --e2e --with-app`.
- V12 — Every existing case still passes (regression) — proof:
  `bun tools/test-generated.ts --case server/<each>/<each> --case frontend/next/<each> --e2e --with-services --with-app`.
- V13 — On Windows (Docker Desktop), `single` builds and passes the app smoke. This blocks the
  release, because Windows is a first-class host — proof:
  `bun tools/test-generated.ts --case frontend/react/default --with-app` on Eitan's machine.
- V14 — The catalog PR is green: `validate` and every case job, with the smoke steps — proof:
  the PR's checks.
- V15 — The React template has no `.skip`, `.only`, `test.fixme` or `describe.skip` — proof:
  grep `frontend/react` for those forms.

**Harness**

- V30 — Bootstrapping `react-python-fastapi` with the default (`single`) passes every gate
  (`check` in both packages, `testE2e`). Then `docker compose --profile app up --build --wait`
  runs one app container that answers `/` and `/api/health` on one port — proof: the commands
  in `.superpowers/s010/py-single`.
- V31 — Bootstrapping `react-python-fastapi` with `--deploy split` passes every gate, and the
  app profile runs two containers — proof: `.superpowers/s010/py-split`.
- V32 — `react-python-fastapi`, `single`, with Postgres: `migrate`, `testDb` (none skipped),
  then the app profile with the migrate one-shot — proof: `.superpowers/s010/py-pg`.
- V33 — `react-bun-express` in `single` passes every gate and the app smoke — proof:
  `.superpowers/s010/bun-single`.
- V34 — `next-python-fastapi` still bootstraps green (regression), and `--deploy single` on it
  stops with the generator's reason — proof: `.superpowers/s010/next-py`.
- V35 — The migration drill: following the `deployment` skill alone, a Sonnet agent moves
  V30's project from `single` to `split`. Every gate, the app smoke and e2e against the
  frontend container are green, and `.doc/architecture.md` records the move — proof: the
  drill's transcript and commands in `.superpowers/s010/py-single`.
- V36 — No root file assumes a server-rendered frontend or one image per package without
  justification — proof: grep `AGENTS.md .doc .claude/rules .claude/agents .claude/skills` for
  `server action|server component|one image per package|NEXT_PUBLIC|port 3000|port 4000`, with
  every hit justified.
- V37 — A fresh-cache bootstrap from `v1.2.0` works after the lock bump — proof: H4's proof
  run.
- V38 — The hook suite is unchanged and green — proof:
  `node --test ".claude/hooks/test/*.test.mjs"`.

## Risks

- **Compose `service:` contexts may not build a service that is never started, or may behave
  differently on Windows.** Mitigation: S1 on both hosts, the local-path fallback (OQ4), and
  V13 on Windows, because CI is Linux.
- **The SPA fallback could swallow API 404s or answer a missing asset with HTML.** Mitigation:
  the M5-5 table, tested row by row in both servers (V06), plus the smoke checks (V10).
- **Helmet's CSP (`upgrade-insecure-requests`, `script-src 'self'`) could break the built SPA
  over plain HTTP.** Mitigation: S1 in Chromium, and e2e against the running container (V10,
  V11).
- **A secret could reach the browser bundle** through a `VITE_*` value or a `.env` file copied
  into the image. Mitigation: `env.ts` is the only reader (lint), `.dockerignore` excludes
  `.env*`, and V10 checks the image contents.
- **A spoofed client IP in `single`** (`TRUST_PROXY` 1 with no proxy in front). Mitigation: the
  default is `false` (OQ8), and the skill and the Deployment line require the production hop
  count.
- **Cookie and CSRF regressions when a product moves the frontend to another origin.**
  Mitigation: the move is not generated (OQ10); the skill lists the CORS, cookie and CSRF
  changes as a planned security change.
- **The two servers' static behaviour could drift.** Mitigation: one table, the ledger, and V06.
- **React Router, Vite or Tailwind majors churn.** Mitigation: versions locked in `bun.lock` and
  recorded in ADR 0003, and a refresh procedure in `CONTRIBUTING.md`.
- **Scope creep into host-specific deploy files.** Mitigation: Out of scope. The skill stays
  topology-level.

## Rollout Order

1. G0. Then cut `feat/frontend-react` in both repositories.
2. A0 alongside S1 and H1. Then G1.
3. T1, with N1 and R1 alongside in their own catalog worktrees.
4. T2 alongside S2 (S2 after N1).
5. R1, then R2.
6. T3.

Each task gets a Sonnet review against ADR 0003 and the ledger.

- **Catalog:** one Opus final review and a fix wave; V12 and V13 locally; V14 after the push.
- **Harness:** H2 after R2, H3 after H2, then one Opus final review and a fix wave.
- **Release:** the two PRs into `dev`, with Eitan's yes. Eitan merges, merges `dev` → `main` and
  tags `v1.2.0`. Then H4.

## Rollback

- Each repository's change is one branch merged into `dev`. Revert the merge commit there.
- Until H4, the harness lock still pins `v1.1.0`, so every bootstrap is untouched.
- After the tag, revert H4's one-line lock change. A bad catalog tag is superseded by a patch
  tag, never moved.
- The Next stacks' generated output changes only by the inert static code and the Deployment
  sections (V04). A
  generated project is standalone: switching its deploy mode back is the `deployment` skill
  run in reverse, and no data changes.

## As built

- Catalog v1.2.0 tagged on `main` f0e73b7 (PR #6 into `dev`, the parity-test fix #8, `dev` → `main` #7). What
  shipped differently from the decisions is in ADR 0003 › As built.
- Harness: PR #10 into `dev`, `dev` → `main` #11; this lock bump (H4) follows.
- Beyond the plan: task N1 (the `next` ESLint zones, G1); a final-review fix wave per repository; a docs fix after the
  V35 drill (each template's `AGENTS.md › Deployment` carries both modes' exact lines, guarded by a test) and a reverse
  drill (split → single). V35 ran both directions.
- Proof: catalog 22/22 cases locally and 24/24 CI checks on the PR; V30–V37 in the harness; hooks 1188/1188.
- Follow-ups: the final catalog review's Minors M6–M14; a static `withApp` case runs its e2e twice (dev flow and
  container); `down` also removes the database container (volume kept) is not stated in the skill.
