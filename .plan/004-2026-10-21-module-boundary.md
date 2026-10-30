# Module boundary: controllers are the public API

Status: done (executed with TDD in a scratch scaffold, validated V01–V08 in a fresh bootstrap, reviewed by a
fresh Opus reviewer and fixed in one wave plus one bounded follow-up on 2026-10-21; uncommitted,
awaiting Eitan's review. Flipped to active on Eitan's instruction, 2026-10-21: "go", with the rule
restated: the HTTP endpoints live in `api/<module>/route.ts`, a route imports its own module's
controller, a controller imports its own service and other modules' controllers; and, mid-execution:
"middlewares + request-body validations should be handled in the module's route.ts files before
calling the controller functions". Rulings, fixes and deferred minors:
`.superpowers/sdd/004-2026-10-21-module-boundary/progress.md`)
Owner: Eitan
Last updated: 2026-10-21
Branch: `feat/fullstack-capability`
Stages: harness only (no role agents; the interactive session executes it)
Supersedes: plan 002 C3 (controllers are Express handlers that validate and respond) and
the cross-module half of C7 (a module reaches another module through its `service`);
plan 003 C7 (the readiness controller factory `makeReady`). Every other decision stands.

Revision: `.plan/005-2026-10-21-backend-architecture.md` (2026-10-21) supersedes A2's
import lists (`lib/` → `services/`), C2 (the caller type is `models/auth/type.ts`,
`requireCaller` is in `middleware/auth.ts`) and C3 (`infra/lifecycle.ts` →
`infra/dependency.ts`).

## Goal

Eitan's instruction (2026-10-21): "api folder should have inside of it all modules
(health, user, auth …): /api/auth, /api/user, /api/health. Controllers can only
communicate with other modules' controllers": the auth controller calls the user
controller, which uses its own `user/service.ts`; the same for data aggregation. After
this plan a module's `controller.ts` is its public API (typed functions, no HTTP), its
`service.ts` and `repository.ts` are private to the module, the only cross-module import
is controller → controller, and `route.ts` is the HTTP adapter (validate, resolve the
caller, call the controller, send the status). ESLint enforces all of it.

## Scope

- In: `templates/backend` (`api/health` rewritten to the new shape, `eslint.config.mjs`
  zones and cross-module patterns, `tests/health.test.ts`), `AGENTS.md` (Architecture ›
  `backend/src/` bullets and import direction; "module" wording), the `api-design` skill
  (module skeleton, worked example, auth paragraph, a cross-module illustration), the
  `error-handling`, `database`, `code-review` and `writing-plans` (template) skills and
  the `backend` agent where they describe controllers, `.doc/architecture.md` (Data Flow,
  Auth), `README.md`, plan 002 and plan 003 pointers.
- Out: the frontend template, the hooks, the OpenAPI chain, `lib/validate.ts` (unchanged;
  it just moves to the route adapter's call site), the infra layer.

## Assumptions

- A1 — The module layout stays: one directory per module under `backend/src/api/`,
  singular name, mounted at `/api/<name>` with one `api.use` line in `server.ts`
  (plan 002 C2). A module is a resource (`user`, `post`) or a capability (`auth`).
- A2 — The layers and what each may import:
  - `schema.ts`: the contract. zod schemas, OpenAPI registration, types. Imports `lib/`
    and, for aggregated responses, another module's `schema.ts`.
  - `route.ts`: the HTTP adapter. An Express `Router`; per endpoint it mounts the
    middleware that endpoint needs (the auth resolver, an upload parser, a rate limit:
    endpoint-level middleware lives here, before the handler; only cross-cutting
    middleware stays in `server.ts`), validates the request parts it reads
    (`validate()`: body, params, query), resolves the caller (`requireCaller(res)` once
    `middleware/auth.ts` exists), calls one controller function, and sends the status
    and body. Imports its own `controller.ts`, `schema.ts`, `lib/` and `middleware/`.
    Nothing else; no business rules. (Eitan, 2026-10-21: "middlewares + request-body
    validations should be handled in the module's route.ts files before calling the
    controller functions".)
  - `controller.ts`: the module's public API. One exported function per operation with
    typed arguments and return values (the schema types), no `req`/`res`, no HTTP status.
    It calls its own `service.ts` and, to cross a module boundary, another module's
    `controller.ts`; an aggregating module composes several controllers here. No data
    access. Imports `./service`, `./schema`, `../<other>/controller`,
    `../<other>/schema` (types), `lib/`, `infra/logger.ts`, `infra/lifecycle.ts`.
  - `service.ts`: private. Business rules, record-to-response mapping, transactions.
    Imports `./repository`, `./model`, `./schema`, `lib/`, `infra/logger.ts`. Never
    another module, never `./controller` or `./route`.
  - `repository.ts`, `model.ts`: private data access (plan 003 rules unchanged).
- A3 — A cross-module flow is not atomic: each controller call is its own unit of work.
  A flow that must be atomic lives inside one module. Stated in the `api-design` skill.
- A4 — Controllers trust their arguments: validation is the adapter's job, authorization
  is the service's (from the caller the adapter passed in). A controller called by another
  controller receives already-typed values.

Calls made on the builder check (2026-10-21; reversible, listed for review):

- C1 — Controller signature: one positional argument when the operation takes one value
  (`getPost(id)`), otherwise one object with named parts (`createPost({ input, caller })`,
  `listPost({ query })`). The worked example and the auth illustration fix this convention.
- C2 — The caller is out of this plan, as in plan 002 C6: `lib/caller.ts` (`Caller`,
  `requireCaller(res)`) and `middleware/auth.ts` arrive with the first protected endpoint,
  per the `api-design` skill. Controllers and services import `Caller` from `lib/`, which
  every layer may import; the compiled example carries no caller, the auth illustration
  shows one.
- C3 — A route adapter may import types from `infra/lifecycle.ts` (the `Resource` type
  for `ready(list?)`); no zone forbids `infra/` for routes and the prose says so.
- C4 — A controller propagates a callee's `AppError` unchanged and may throw `AppError`
  for a composition rule (a `conflict` between two modules' answers). Neither a controller
  nor an adapter builds an error body: the error handler does. The `error-handling` skill
  says "the route adapter validates; nothing but the error handler builds an error
  response".

## Open Questions

1. `route.ts` becomes the HTTP adapter (validation, caller, status) instead of "paths
   only"? Recommended: yes. It is the only shape in which one controller can call another
   without passing `req` and `res` around; the adapter is three lines per endpoint and
   stays reviewable.
2. May `schema.ts` and `controller.ts` import another module's `schema.ts`? Recommended:
   yes, for contract types only (an aggregated response embeds `Post`); behaviour still
   crosses only through controllers.
3. Cycles between controllers (`auth → user → auth`)? Recommended: forbidden by
   convention, documented in the `api-design` skill (lift the shared operation into one
   module or a third). Not linted: cycle detection would cost a plugin rule for a case
   review catches.

## Steps

### Contract

No endpoint changes. `GET /api/health` and `GET /api/health/ready` keep their request,
response and status behaviour; only the files that implement them move.

### Backend template (`templates/backend/`)

1. `src/api/health/controller.ts`: `getHealth(): HealthResponse` and
   `getReadiness(list?: readonly Resource[]): Promise<Readiness>`, delegating to the
   service. No Express import.
2. `src/api/health/route.ts`: `healthRoute.get('/', (_req, res) => { res.json(getHealth()) })`
   and `healthRoute.get('/ready', ready())`, where `ready(list?)` is the exported adapter
   factory that maps `ok` to 200 and `degraded` to 503 (the test seam that replaces
   plan 003's `makeReady`; `route.ts` may export it because tests are outside the zones).
3. `src/api/health/service.ts`: unchanged.
4. `eslint.config.mjs`:
   - zone: `route.ts` never imports `service.ts`, `repository.ts` or `model.ts` (it may
     import `schema.ts` now; message: "a route adapts HTTP to its controller: it imports
     controller, schema and lib only");
   - zone: `controller.ts` never imports `route.ts`, `repository.ts`, `model.ts`
     (message updated: "a controller calls its service or another module's controller; it
     never touches the data layer or a route");
   - zone: `service.ts` never imports `route.ts` or `controller.ts` (unchanged);
   - cross-module (`no-restricted-imports`): for every file under `src/api/**`, refuse
     `../*/service`, `../*/route`, `../*/repository`, `../*/model`; for `route.ts`,
     `service.ts`, `repository.ts` and `model.ts` also refuse `../*/controller` and
     `../*/schema`; for `schema.ts` also refuse `../*/controller`. Only `controller.ts`
     may import `../*/controller`; `controller.ts` and `schema.ts` may import
     `../*/schema`.
5. `tests/health.test.ts`: the probe apps mount `ready([])` and `ready([down])` from
   `route.ts`; the `app` test is unchanged. `tests/openapi.test.ts` unchanged.

### Harness

6. `AGENTS.md` Architecture › `backend/src/`: "one directory per module (a resource or a
   capability: `health`, `user`, `auth`), singular name, mounted at `/api/<name>`"; the
   `route.ts`, `controller.ts`, `service.ts` bullets per A2; the import-direction paragraph:
   `route → controller → service → repository`, the only cross-module import is
   `controller → controller` (plus `schema` types), services and data layers are private.
7. `api-design` skill: module skeleton rewritten (route adapter, controller public API,
   private service); the worked `post` example updated so it still compiles (V04); a
   short illustration of `auth/controller.ts` calling `user/controller.ts`; the cross-module
   and no-cycle rules (A3, Q3); "Auth and the caller": the auth middleware mounted per
   protected endpoint in `route.ts` (ahead of the handler), `requireCaller(res)` in the
   handler, the caller passed to the controller, authorization in the service; a note
   that endpoint-level middleware (auth, uploads, rate limits) mounts in `route.ts`, and
   `server.ts` keeps only the cross-cutting middleware.
8. `error-handling` skill (Backend paragraph: the route adapter validates; a controller
   never builds an HTTP error), `database` skill ("a service that needs another module's
   data" → "a module reaches another module through its controller"; transactions
   sentence), `code-review` skill (logic in `route.ts` or `controller.ts` still a finding:
   adapters and composition are not business rules), `writing-plans/template.md` step 3,
   `backend` agent step 4 (order: schema → tests → repository → service → controller →
   route adapter → mount).
9. `.doc/architecture.md`: Data Flow step 3 (adapter validates, controller composes,
   service rules), Auth bullet (`requireCaller(res)` in the route adapter).
10. `README.md` backend bullet: "one module per resource or capability (`schema`,
    `route`, `controller`, `service`)".
11. Plan 002 and plan 003: `Revision:` lines pointing here.

## Validation

- V01 — The bootstrap scaffolds a project — proof: `node scripts/bootstrap.mjs --root <scratch> --name demo` exits 0.
- V02 — Every backend gate is green — proof: `bun run check` in the scaffolded `backend/` (tests unchanged in count: 39).
- V03 — The boundary is enforced — proof: probe files in the scaffold: `route.ts → ./service` refused, `route.ts → ./schema` allowed, `controller.ts → ../other/controller` allowed, `controller.ts → ../other/service` refused, `controller.ts → ../other/schema` allowed, `service.ts → ../other/controller` refused, `service.ts → ../other/service` refused, `route.ts → ../other/controller` refused, `repository.ts → ../other/controller` refused, `schema.ts → ../other/schema` allowed; plan 002/003 probes still fire; lint clean after removal.
- V04 — The `api-design` worked example compiles and lints in the new shape — proof: blocks extracted into `src/api/post/` with a stub repository, `tsc --noEmit` and `eslint src/api/post` exit 0.
- V05 — The e2e journey still reaches the API through the health route adapter — proof: `bun run test:e2e` in the scaffolded `frontend/` passes.
- V06 — No stale statement of the old rule remains — proof: repository grep for "calls that module's `service`", "send the response", "paths to controller functions", `makeReady` finds none outside plans 001–003.
- V07 — Templates match the scaffold's Prettier output — proof: `diff -r` differs only in `__PROJECT_NAME__` substitutions.
- V08 — Readiness still answers 200 and 503 — proof: `tests/health.test.ts` "answers ok with an empty resource map" and "reports degraded with 503 when a resource ping fails" through `ready()`.

## Risks

- Adapters in `route.ts` are a second place per endpoint where a reviewer looks for
  misplaced logic. Mitigation: the `code-review` skill names it; the adapter is validate,
  call, respond, and anything else is a finding.
- Controller cycles are not linted. Mitigation: the `api-design` skill forbids them and
  says how to break one; a module importing two or more other controllers is a review
  prompt.
- Cross-module calls are not atomic (A3). Mitigation: stated in the skill; a plan that
  needs atomicity across modules says so and keeps the flow in one module.
- The worked example and the backend agent's step order are what agents copy; a mismatch
  there propagates to every task. Mitigation: V04 compiles the example; the agent file
  is edited in the same change.

## Rollout Order

template `api/health` → lint zones → tests → `AGENTS.md` → `api-design` skill → other
skills and the agent → docs → plan pointers → validation in a scratch root.

## Rollback

Discard the uncommitted changes to the files in Scope (a human does). No data, no
generated artifacts and no scaffolded project are affected.
