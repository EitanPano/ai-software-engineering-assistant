# Backend template: generic layered architecture with auth

Status: done (executed 2026-10-21 by the interactive session with parallel Sonnet implementers and
reviewers in a scratch scaffold, validated V01–V22 in a fresh bootstrap, final whole-change review on Opus
clean after one fix wave; uncommitted, awaiting Eitan's review. Ledger, rulings and parked minors:
`.superpowers/sdd/005-2026-10-21-backend-architecture/progress.md`, git-ignored. Design record:
`.superpowers/specs/2026-10-21-backend-template-architecture-design.md`, git-ignored; this plan
carries every decision it needs)
Owner: Eitan
Last updated: 2026-10-21
Branch: `feat/fullstack-capability`
Stages: harness only (no role agents; the interactive session executes it)
Supersedes: plan 002 C2 (`/api` mounted with one `api.use` line per module in `server.ts`:
now one line per module in `config/routes.ts`), C6 (no auth stub ships: auth ships), C12
(`lib/pagination.ts`: `lib/` is deleted); plan 003's file names `infra/lifecycle.ts`,
`infra/resources.ts`, `infra/logger.ts` (now `infra/dependency.ts` and `services/logger.ts`),
C7 (the seam is `list = dependencies`) and the `database` skill's `infra/db/` paths (now
`infra/<engine>.ts` and `infra/scripts/`); plan 004 A2's import lists (`lib/` → `services/`),
C2 (`lib/caller.ts`: the caller type is `models/auth/type.ts`, `requireCaller` is in
`middleware/auth.ts`) and C3 (`infra/lifecycle.ts` → `infra/dependency.ts`). Every other
decision of plans 001–004 stands, in particular: no engine in the template, the OpenAPI
chain, controllers as a module's public API, `route.ts` as the HTTP adapter.

> **For the executing session:** work in a scratch scaffold (`node scripts/bootstrap.mjs
> --root <scratch> --name demo`), test-first, then copy `backend/src`, `backend/tests`,
> `eslint.config.mjs`, `package.json` and `.env.example` back into `templates/backend/`
> with the `__PROJECT_NAME__` token restored, and validate in a second fresh bootstrap
> (V01–V22). Implementers on Sonnet; the final whole-change review on Opus (Eitan's
> rule). Record rulings and deferred minors in
> `.superpowers/sdd/005-2026-10-21-backend-architecture/progress.md`.

## Goal

Eitan's instruction (2026-10-21): upgrade the backend template to a generic, layered
folder and file architecture "so that when a user asks its AI to create a new project and
later add new services and dependencies it will know how and where to put it properly";
the stack and the specific vendors are not important. After this plan a scaffolded
backend has one home for every kind of addition (stated in `AGENTS.md` as a table,
enforced by ESLint zones, demonstrated by working code), ships authentication (register,
login, logout, refresh with rotation and replay detection, OTP by email and phone), role
guards, rate limiting, a communication abstraction with a console provider, a scheduler
with a real job, pub/sub with a real event, and a commented reference module to copy. It
still names no engine, no cache server and no vendor, and `bun run check` passes with no
Docker and no env file. The same map, phrased language-neutrally in `AGENTS.md`, is what
the later Python and .NET server templates mirror.

## Scope

- In: `templates/backend/` (every file under `src/`, `tests/`, `eslint.config.mjs`,
  `package.json`, `.env.example`), `templates/root/docker-compose.yml` (backend
  environment block), `AGENTS.md` (Stack, Architecture › `backend/src/`, Naming), the
  `api-design`, `database`, `error-handling`, `writing-tests`, `bootstrap-project`,
  `code-review` skills and the `writing-plans` template, the `backend` agent (and
  `reviewer`, `qa`, `dev-loop` only where they name a backend path), `README.md`,
  `.doc/architecture.md`, `.doc/glossary.md`, `Revision:` pointers in plans 002–004.
- Out: the frontend template (no auth UI; the sign-in journey and forwarding the client IP
  are a later backlog task), the hooks, `scripts/bootstrap.mjs` (unless the copy needs
  it), password-reset endpoints (the message template ships, the flow does not), any
  engine, Redis or vendor SDK, multi-tenancy, a logging library, the `models/` idea on the
  frontend.

## Assumptions

- A1 — The folder architecture of Eitan's spec is followed generically: `config/`, `api/`,
  `models/`, `middleware/`, `services/`, `infra/`; `lib/` is deleted and its contents move
  to `services/utils/` and `middleware/validate.ts`. The shared-capabilities folder is
  named `services/` (Eitan, 2026-10-21, over `shared/`).
- A2 — No engine, cache server or vendor in the template (plan 002 A1, Eitan's review).
  `infra/memory.ts` is the only store, a `Resource` that is both a record store and a
  key-value store; `services/db.ts` and `services/cache.ts` are **file seams, not type
  seams**: the data-layer task rewrites `db.ts` to export the chosen client (its type
  changes) and rewrites every `repository.ts` and `services/session.ts`; the cache task
  does the same for `cache.ts` with `infra/redis.ts` and gives `infra/pubsub.ts` its
  Redis adapter.
- A3 — The Next.js server is the backend's HTTP client (`AGENTS.md`: no browser fetch).
  The backend is therefore client-agnostic: token-issuing responses set the cookies **and**
  return the tokens in the body; CORS is off unless `CORS_ORIGINS` is set; IP-keyed rate
  limits are correct behind the Next.js server only when it forwards `X-Forwarded-For`
  and `TRUST_PROXY` trusts that hop (the frontend auth task's duty, recorded in `AGENTS.md`).
- A4 — Plan 004 A4 holds: the caller is forwarded through controllers and the service
  authorizes. `requireAuth` and `requireRole` in `route.ts` are declarative gates that
  fail fast; the service still checks the forwarded caller, so a cross-module call cannot
  bypass a route. Operations only other modules, jobs or scripts call take no caller and
  are named system operations.
- A5 — Packages added: `jose`, `croner`, `helmet`, `cors`, `cookie-parser` (+ `@types/cors`,
  `@types/cookie-parser`). Approved by Eitan ("ok go"). Hashing is `Bun.password`
  (argon2id); HMAC, AES-256-GCM and random tokens are `node:crypto`. Nothing else.
- A6 — One declaration, one validator: `models/<name>/` declares the TypeScript types;
  `api/<name>/schema.ts` declares the zod schemas, each `satisfies z.ZodType<T>` of the
  matching type and without a duplicate `z.infer` alias. Shapes that exist only for HTTP
  (params, query, credentials, an OTP request) live in `schema.ts` alone with their
  `z.infer` type. When an engine defines storage in code, `api/<name>/model.ts` satisfies
  `models/<name>/interface.ts`.
- A7 — The OpenAPI chain stays (plan 002 A2). Every endpoint, auth included, registers in
  its module's `schema.ts`; `config/routes.ts` lists `{ path, route, register }` per module
  and both `server.ts` (mount) and `openapi.ts` (register) read it. The templates hold no
  committed `openapi.json` (plan 003 C4); the bootstrap generates it.
- A8 — Tests run without Docker (plan 003 A3): supertest against `app`, expiry and grace
  windows through `setSystemTime` from `bun:test`, messages observed through a capturing
  provider registered with the public `registerProvider`, never a module mock.

Calls made during the design and the builder check (2026-10-21; approved with the design,
listed so each can be reversed on review):

- C1 — Tokens in the body as well as in cookies (A3). `AuthTokens = { accessToken,
  accessExpiresAt, refreshToken, refreshExpiresAt }`.
- C2 — Refresh lifetime is sliding: 30 days from each rotation, 90-day absolute cap, and a
  30-second grace window in which a replay of the previous token is a concurrent retry
  (rotate again), not an attack. Any other replay of a rotated token revokes every
  session of the user. Access tokens (15 min) stay valid until expiry: the stateless
  tradeoff, stated in `AGENTS.md`.
- C3 — OTP `login` does not create an account for an unknown target; the endpoint still
  answers 202. OTP `verify` requires a caller and only the caller's own email or phone
  (403 otherwise, on both OTP endpoints).
- C4 — The console provider prints the full message (OTP code included) in development
  only; test and production print channel, template name and target type, no body.
- C5 — Welcome mail goes through an event: `createUser` publishes `user.registered`;
  `infra/subscribers/send-welcome.ts` sends the `welcome` template. Pub/sub ships with one
  real use.
- C6 — `config/constants.ts` holds policy (durations, attempts, windows, cookie and header
  names); `models/<name>/constants.ts` holds limits of the data itself (field lengths,
  defaults). That is the one rule between them.
- C7 — `api/auth/` has no `service.ts` (the spec): it owns no data; its composition rules
  (OTP purpose and own-target gates, token issuance after the user module answered) live
  in `api/auth/controller.ts`. Rules about user data live in the user module
  (`verifyCredentials` and `getActiveUser` throw `forbidden` for a blocked account).
  `AGENTS.md` states the general rule: a module with its own data always has a
  `service.ts`; a capability module whose rules only compose other modules and services
  may have none.
- C8 — No admin bootstrap in the template; `user.setUserRole({ id, role })` is a system
  operation the data-layer task's seed script (`infra/scripts/seed.ts`) and the tests call.
- C9 — The reference module keeps the spec's name `module` (entity `module`, directories
  `api/module/` and `models/module/`). `example` would make copy-and-rename safer; the
  spec is explicit.
- C10 — Logout of all sessions is `POST /api/auth/logout` with `{ all: true }`. OTP
  verification is `POST /api/auth/otp/verification` (a noun sub-resource, `api-design`).
- C11 — `middleware/express.d.ts` declares `Express.Locals` (`requestId`, `caller?`,
  `input?`): middleware is what writes `res.locals`.
- C12 — The scheduler and pub/sub are `Resource`s in the dependency list
  `[memory, pubsub, scheduler]`; `infra/jobs/`, `infra/subscribers/` and `infra/scripts/`
  share one set of import rights (they may call controllers).
- C13 — `TRUST_PROXY` is added (IP-keyed limits are wrong behind a proxy without it);
  CORS is off unless `CORS_ORIGINS` is set.
- C14 — `services/session.ts` keeps its own queries (not a module, no `repository.ts`);
  the data-layer task lists it among the files to rewrite.
- C15 — `api/<name>/model.ts` keeps its name next to `models/`; one sentence in `AGENTS.md`
  separates them (`models/`: types; `model.ts`: the engine's storage mapping).
- C16 — `infra/dependency.ts` may be imported by anything except `models/`, `config/` and
  `services/utils/` (the health module reads `healthCheck` and `dependencies` as values).
- C17 — `config/routes.ts` is imported only by `server.ts`, `openapi.ts` and tests.
- C18 — `docker-compose.yml` passes the production secrets as plain `${VAR}`, not `${VAR:?}`,
  so `docker compose up -d <db>` for local work needs no secrets in the shell; `env.ts`
  fails fast at boot instead.

## Open Questions

1. Keep the reference module's name `module` (C9) or rename to `example`? Recommended:
   keep `module`; the spec names it and the README's rename step says `module → <name>`,
   `Module → <Name>`.
2. Does `healthCheck` keep `infraStatus`'s one-second result cache? Recommended: yes; drop
   it only if it makes a test non-deterministic.
3. How does `validate` type `res.locals.input`? Recommended: a generic over the
   `{ body?, query?, params? }` schemas object with `input` typed as the parsed record; a
   cast at the handler is acceptable if the generic fights Express's types.

## Steps

### Contract

Every endpoint is JSON; every error is the envelope from the `error-handling` skill. `T`
is ISO 8601 UTC. `PublicUser = { id, email, phone: string | null, role: 'user' | 'admin',
status: 'active' | 'blocked', emailVerifiedAt: T | null, phoneVerifiedAt: T | null,
createdAt: T, updatedAt: T }`. `AuthTokens` per C1. `Target = { type: 'email' | 'phone',
value: string }` (email lower-cased, phone E.164). `Module = { id, name, status: 'active' |
'archived', createdAt: T, updatedAt: T }`. Lists are `{ items: X[], nextCursor: string |
null }` with `?cursor&limit` (1–100, default 20).

| Endpoint | Guard | Request | Response | Errors |
| --- | --- | --- | --- | --- |
| `GET /api/health` | | | `200 HealthResponse` | 500 |
| `GET /api/health/ready` | | | `200 \| 503 Readiness` (per dependency: `memory`, `pubsub`, `scheduler`) | 500 |
| `POST /api/auth/register` | `rateLimit` 10 / 15 min per IP | `{ email (≤254), password (8–128) }` | `201 { user: PublicUser, tokens: AuthTokens }` + cookies | 400, 409, 429 |
| `POST /api/auth/login` | `rateLimit` 10 / 15 min per IP, 5 / 15 min per email | `{ email, password }` | `200 { user, tokens }` + cookies | 400, 401 (one message for unknown email and wrong password), 403 (blocked), 429 |
| `POST /api/auth/refresh` | `rateLimit` 30 / 15 min per IP | cookie `refresh_token` or `{ refreshToken }` | `200 { user, tokens }` + rotated cookies | 400 (neither present), 401 (invalid, expired, revoked, replayed), 403 (blocked), 429 |
| `POST /api/auth/logout` | `requireAuth` | `{ all?: boolean }` | `204` + cleared cookies | 401 |
| `POST /api/auth/otp` | `authenticate`, `rateLimit` 10 / h per IP, 5 / h per target | `{ target: Target, purpose: 'login' \| 'verify' }` | `202 {}` | 400, 401 (verify without caller), 403 (verify for another's target), 429 |
| `POST /api/auth/otp/verification` | `authenticate`, `rateLimit` 20 / 15 min per IP | `{ target, purpose, code: /^\d{6}$/ }` | `200 { user, tokens? }` (`tokens` on `login` only) + cookies on `login` | 400, 401 (wrong, expired, exhausted, no caller for verify), 403, 429 |
| `GET /api/user/me` | `requireAuth` | | `200 PublicUser` | 401 |
| `PATCH /api/user/me` | `requireAuth` | `{ phone?: string \| null }` | `200 PublicUser` | 400, 401, 409 (phone taken) |
| `GET /api/user` | `requireRole('admin')` | `?cursor&limit` | `200 { items: PublicUser[], nextCursor }` | 400, 401, 403 |
| `GET /api/user/:id` | `requireRole('admin')` | `params.id` | `200 PublicUser` | 401, 403, 404 |
| `GET /api/module` | | `?cursor&limit` | `200 { items: Module[], nextCursor }` | 400 |
| `GET /api/module/:id` | | `params.id` | `200 Module` | 404 |
| `POST /api/module` | `requireAuth` | `{ name (1–100) }` | `201 Module` | 400, 401 |
| `PATCH /api/module/:id` | `requireAuth` | `{ name?, status? }` | `200 Module` | 400, 401, 404 |
| `DELETE /api/module/:id` | `requireRole('admin')` | `params.id` | `204` | 401, 403, 404 |

Cookies: `access_token` (path `/`) and `refresh_token` (path `/api/auth`), `httpOnly`,
`sameSite: lax`, `secure` outside development, `maxAge` from the TTLs, `domain` from
`COOKIE_DOMAIN` when set. `Authorization: Bearer <access>` is accepted everywhere the
cookie is and wins when both are present. 429 responses carry `Retry-After`.

Controller operations (the module's public API). User, caller-taking: `getMe({ caller })`,
`updateMe({ caller, input })`, `listUser({ query, caller })`, `getUser({ id, caller })`.
User, system: `createUser({ input })`, `verifyCredentials({ input })` (dummy-hash compare
for an unknown email; `forbidden` when blocked), `findUserByTarget({ target })`,
`getActiveUser(id)`, `markVerified({ id, type })`, `setUserRole({ id, role })`. Auth:
`register({ input })`, `login({ input })`, `refresh({ refreshToken })`, `logout({ caller,
all })`, `requestOtp({ input, caller? })`, `verifyOtp({ input, caller? })`. Module:
`listModule({ query })`, `getModule(id)`, `createModule({ input, caller })`,
`updateModule({ id, input, caller })`, `deleteModule({ id, caller })`.

### Backend template (`templates/backend/`)

Order is dependency order; each step writes its tests first (`writing-tests` skill).

1. **Packages and config.** `package.json`: add A5's packages; scripts unchanged.
   `src/config/env.ts` (moved from `src/env.ts`): `NODE_ENV`, `PORT`, `TRUST_PROXY`
   (`false`), `CORS_ORIGINS` (optional, comma list), `JWT_ACCESS_SECRET`,
   `JWT_REFRESH_SECRET`, `OTP_SECRET` (≥ 32 chars), `ENCRYPTION_KEY` (32-byte base64),
   `COOKIE_DOMAIN` (optional), `MAIL_PROVIDER`, `SMS_PROVIDER`, `WHATSAPP_PROVIDER`
   (`console`), `MAIL_FROM`, `JOBS_ENABLED` (`true`); each secret required when
   `NODE_ENV=production`, a fixed development default otherwise, and `loadEnv` returns the
   list of defaulted secrets for `index.ts` to warn about. `src/config/constants.ts`:
   `ACCESS_TOKEN_TTL '15m'`, `REFRESH_TOKEN_TTL '30d'`, `SESSION_ABSOLUTE_TTL '90d'`,
   `REFRESH_REUSE_GRACE '30s'`, `OTP_LENGTH 6`, `OTP_TTL '10m'`, `OTP_MAX_ATTEMPTS 5`, the
   rate-limit table, `COOKIE_NAMES`, `BEARER_PREFIX`. `src/config/cors.ts`: `corsOptions`
   from `env.CORS_ORIGINS` with `credentials: true`, or `undefined` when unset.
   `.env.example`: every variable, a placeholder, one comment line each.
2. **Pure helpers.** Move `lib/{error,zod,openapi,pagination}.ts` to `src/services/utils/`
   unchanged in behaviour; add `src/services/utils/time.ts` (`parseDuration('15m') → ms`,
   `addDuration(date, text)`, `isExpired(date, now?)`, `toIso`). Move `infra/logger.ts` to
   `src/services/logger.ts` and add redaction of fields whose key matches
   `/password|token|secret|otp|code|cookie|authorization/i` → `[redacted]`.
3. **Infra core and the template stores.** `src/infra/dependency.ts` = `lifecycle.ts` +
   `resources.ts` renamed: `Resource`, `withRetry`, `connectAll` (was `startInfra`),
   `disconnectAll` (was `stopInfra`), `healthCheck` (was `infraStatus`), `createShutdown`,
   and `export const dependencies: readonly Resource[] = [memory, pubsub, scheduler]`.
   `src/infra/memory.ts`: `RecordStore` (`collection<T>(name)` → `get`, `put`, `delete`,
   `find(predicate)`), `KeyValueStore` (`get`, `set(key, value, ttlMs?)`, `delete`,
   `increment(key, ttlMs)`), expiry checked on read against `Date.now()`, `connect` logs
   `store=memory` (and `warn`s in production that data does not survive a restart), `ping`
   resolves, `close` clears. `src/services/db.ts`: `getDb(): RecordStore` bound to
   `memory`, store types re-exported, the seam comment. `src/services/cache.ts`: `get<T>`,
   `set<T>`, `del`, `incr` JSON-encoding over the key-value store.
4. **Middleware.** `src/middleware/validate.ts`: `validate({ body?, query?, params? })`
   parses each given part, throws `validation_failed` naming the part, stores the typed
   result on `res.locals.input`. `src/middleware/rate-limit.ts`: `rateLimit({ name, limit,
   window, key })` fixed window over `cache.incr` with key `rl:<name>:<subject>`, 429
   `rate_limited` + `Retry-After`. `src/middleware/express.d.ts` (moved from `lib/`):
   `requestId`, `caller?: Caller`, `input?`. `error-handler.ts`, `not-found.ts`,
   `request-id.ts`, `request-log.ts`: imports only.
5. **Models.** `src/models/user/`: `interface.ts` `UserRecord`; `type.ts` `PublicUser`,
   `CreateUserInput`, `UpdateUserInput`, `ContactTarget`; `enum.ts` `UserRole`, `UserStatus`,
   `ContactType` as `as const` objects + union types; `constants.ts` `USER_LIMITS`
   (password 8–128, email ≤ 254). `src/models/session/`: `interface.ts` `SessionRecord`
   (`id, userId, tokenHash, previousTokenHash?, rotatedAt?, createdAt, lastUsedAt,
   expiresAt, absoluteExpiresAt, revokedAt?`), `type.ts` `NewSession`. `src/models/auth/`:
   `type.ts` `Caller { id, role, sessionId }`, `AuthTokens`; `enum.ts` `OtpPurpose`.
   `src/models/module/`: the four files for `ModuleRecord`, `PublicModule`,
   `CreateModuleInput`, `UpdateModuleInput`, `ModuleStatus`, `MODULE_LIMITS`, each opening
   with the comment that says what belongs in it.
6. **Security and sessions.** `src/services/security/crypto.ts` (`hashPassword`,
   `verifyPassword`, `DUMMY_HASH` computed once, `hmac`, `encrypt`/`decrypt` AES-256-GCM
   with `ENCRYPTION_KEY`, `randomToken`, `sha256`), `jwt.ts` (`signAccess`, `signRefresh`,
   `verifyAccess`, `verifyRefresh` over `jose`, HS256, separate secrets, claims per C1/C2),
   `cookies.ts` (`setAuthCookies`, `readAccessToken` header-then-cookie, `readRefreshToken`
   cookie-or-body, `clearAuthCookies`), `otp.ts` (`issueOtp({ purpose, target, userId })`
   → code, `verifyOtp({ purpose, target, code })` → `userId | null`, cache key
   `otp:<purpose>:<type>:<value>`, HMAC with `OTP_SECRET`, attempts, single use).
   `src/services/session.ts`: `createSession(userId)`, `rotateSession({ sessionId,
   presentedHash })` implementing C2 (match → rotate; previous within grace → rotate;
   otherwise → `revokeAllSessions(userId)` and `unauthenticated`), `revokeSession`,
   `revokeAllSessions`, `purgeExpired()`, records in `getDb().collection('session')`.
7. **Communication.** `src/services/communicate/index.ts` (`send(message)`,
   `registerProvider(channel, provider)`), `mail.ts`, `sms.ts`, `whatsapp.ts` (each:
   `Provider` type, console provider per C4, `resolveProvider(name)` with the `console`
   case and a comment showing where a vendor case goes), `templates/otp.ts`,
   `templates/welcome.ts`, `templates/password-reset.ts` (pure → `{ subject?, text }`).
8. **Events and jobs.** `src/infra/pubsub.ts` (`Resource`; `EventEmitter` bus; `publish`,
   `subscribe`; a throwing handler is logged; `connect` registers the subscriber list),
   `src/services/event.ts` (`Events` map with `'user.registered': { userId }`, typed
   `publish`, `subscribe`), `src/infra/subscribers/send-welcome.ts` (`{ topic, handle }`:
   `user.getActiveUser` then `communicate.send` with the `welcome` template; failures
   logged), `src/infra/scheduler.ts` (`Resource`; explicit job list; `croner` with
   `protect`; starts when `JOBS_ENABLED`; logs name and duration; a throwing run does not
   stop the schedule), `src/infra/jobs/session-cleanup.ts` (hourly, `session.purgeExpired`).
9. **Auth middleware.** `src/middleware/auth.ts`: `authenticate` (never rejects; sets
   `res.locals.caller`), `requireAuth` (401), `requireCaller(res)`. `src/middleware/role.ts`:
   `requireRole(...roles)` (401 without caller, 403 on mismatch).
10. **Modules.** `src/api/user/{schema,repository,service,controller,route}.ts` per the
    Contract (repository over `getDb().collection('user')`, lower-cased email, phone
    uniqueness, cursor on `(createdAt, id)`; service `assertRole` for the admin operations;
    `createUser` publishes `user.registered`). `src/api/auth/{schema,controller,route}.ts`
    (controller composes `user`, `session`, `security/*`, `communicate`; route sets and
    clears cookies, mounts guards and limits). `src/api/module/{schema,repository,service,
    controller,route}.ts` fully commented. `src/api/health/*`: imports to
    `infra/dependency.ts` and `services/utils/`; readiness lists the three dependencies.
11. **Assembly.** `src/config/routes.ts`: `modules = [{ path: '/health', route: healthRoute,
    register: registerHealth }, auth, user, module]`, `mountRoutes(api)`. `src/server.ts`:
    `helmet()`, `cors(corsOptions)` when defined, `app.set('trust proxy', env.TRUST_PROXY)`,
    `requestId`, `requestLog`, `express.json({ limit: '1mb' })`, `cookieParser()`,
    `/api` router from `mountRoutes`, `/openapi.json`, `notFound`, `errorHandler`.
    `src/openapi.ts`: registers through `modules`. `src/index.ts`: `connectAll`,
    `disconnectAll`, one `warn` per defaulted secret, otherwise as today.
12. **Lint zones.** `eslint.config.mjs` rewritten to the import table of the design (also
    in `AGENTS.md` after step 15): the leaves (`models/`, `config/constants.ts`,
    `config/env.ts`, `services/utils/`), C16, C17, the store rule (`infra/memory.ts` only
    from `services/db.ts`, `services/cache.ts`, `infra/**`; `infra/pubsub.ts` only from
    `services/event.ts`, `infra/**`), the deny zone for `services/db.ts` and
    `services/cache.ts` in `route.ts`, `controller.ts`, `service.ts`, `schema.ts`
    (`rate-limit.ts` may import `cache.ts`), the module layering (route → controller →
    service → repository, `schema.ts` leaf, no `express` in controllers), the
    `jobs/subscribers/scripts` rights (`api/**/controller.ts`, `api/**/schema.ts` types,
    `services/**`; scripts also `api/**/model.ts`), `middleware/` and `services/` never
    import `api/`, `infra/` never imports `middleware/`, `server.ts`, `index.ts`, nothing
    imports `index.ts`, only `index.ts` imports `server.ts`, only `config/routes.ts` imports
    a `route.ts`; the plan 004 cross-module regex blocks unchanged. Every zone keeps a
    one-sentence message that says the rule.
13. **Tests** (`tests/`, all without Docker): `auth.test.ts`, `user.test.ts`,
    `module.test.ts`, `middleware/validate.test.ts`, `middleware/rate-limit.test.ts`,
    `middleware/role.test.ts`, `middleware/auth.test.ts`, `services/jwt.test.ts`,
    `services/crypto.test.ts`, `services/otp.test.ts`, `services/session.test.ts`,
    `services/cache.test.ts`, `services/event.test.ts`, `services/time.test.ts`,
    `services/logger.test.ts` (moved + redaction), `services/communicate.test.ts`,
    `infra/dependency.test.ts` (moved from `lifecycle.test.ts`), `infra/memory.test.ts`,
    `infra/scheduler.test.ts`, `infra/pubsub.test.ts`, `openapi.test.ts` (fresh file and
    every `modules` entry registers a path), and the existing `entry`, `error-handler`,
    `health`, `request-log`, `pagination` tests updated. The cases are listed in the
    Validation section; no existing test is deleted, only moved.
14. **Compose.** `templates/root/docker-compose.yml` backend `environment`: the production
    secrets and `CORS_ORIGINS`, `TRUST_PROXY`, `JOBS_ENABLED` as plain `${VAR}` (C18).

### Harness

15. `AGENTS.md`: Stack (packages, `Bun.password`, "no logging library" unchanged);
    Architecture › `backend/src/` rewritten: the structure, one paragraph per directory,
    the "where does X go" table, the import table and named rules, the request flow, the
    auth model (A3, C2, C7, A4 wording), the engine seam (A2); Naming: `models/` vs
    `model.ts` (C15), "service" resolved (`service.ts` is a module's private rules,
    `services/` the shared-capability folder); layer map phrased language-neutrally so
    the Python and .NET templates mirror it.
16. `api-design` skill: paths; `validate` as middleware with `res.locals.input`; the
    module skeleton and worked `post` example updated (must still compile, V17); Auth
    section rewritten: the template ships auth, declaring a protected endpoint, `Caller`
    from `models/auth/type.ts`, declarative gates plus service authority, system
    operations, `auth → user` as the shipped composition.
17. `database` skill: store files `infra/<engine>.ts` (`infra/redis.ts` for the cache),
    scripts `infra/scripts/{migrate,seed}.ts`, the two seams and the list of files the
    data-layer task rewrites (`services/db.ts`, every `repository.ts`,
    `services/session.ts`, the dependency list), the cache task (`services/cache.ts`,
    `infra/redis.ts`, the pubsub adapter), `model.ts` satisfies `models/<name>/interface.ts`,
    cache-aside stays in `repository.ts`, test database paths.
18. `error-handling` (paths: `services/utils/error.ts`, `middleware/validate.ts`,
    `services/logger.ts`, `infra/dependency.ts`), `writing-tests` (paths, `setSystemTime`,
    `registerProvider`, the new suite files), `bootstrap-project` (what a fresh project
    has: auth, the reference module, the memory store; the production secrets),
    `writing-plans/template.md` (step wording: models, schema, repository, service,
    controller, route, one line in `config/routes.ts`), `code-review` (a checklist item:
    "is this in the home the table names?"), `dev-loop` only where it names a path.
19. Agents: `backend.md` workflow (schemas and models first; files in order; mount in
    `config/routes.ts`; `config/env.ts`); `reviewer.md`, `qa.md` where they name a path.
20. `README.md`: the backend paragraph, the repository map, "Adding a module" (copy
    `api/module/` and `models/module/`, rename `module → <name>` and `Module → <Name>`,
    one line in `config/routes.ts`, `tests/<name>.test.ts`, `bun run openapi`,
    `bun run check`; delete both directories and the line to drop it).
21. `.doc/architecture.md`: Data Flow (events, jobs), Auth (the shipped model as the
    default a product starts from; the frontend's duty to forward the client IP),
    Operational Concerns (paths, the three dependencies), External Dependencies (none;
    where a vendor goes), change-log line. `.doc/glossary.md`: `session`, `caller`, `OTP`,
    `target`, `module (reference)`.
22. Plans 002, 003, 004: `Revision:` lines pointing here. `.github/copilot-instructions.md`
    and `.cursor/rules/index.mdc`: only if a grep finds a backend path.

## Validation

- V01 — The bootstrap scaffolds a project — proof: `node scripts/bootstrap.mjs --root <scratch> --name demo` exits 0.
- V02 — Every backend gate is green with no Docker and no env file — proof: `bun run check` in the scaffolded `backend/` exits 0; test count ≥ 39 + the new files, none skipped.
- V03 — The frontend still reaches the API — proof: `bun run check` and `bun run test:e2e` in the scaffolded `frontend/` pass; the health pill reads the backend.
- V04 — Register issues tokens and cookies without the hash — proof: `tests/auth.test.ts` "register answers 201 with tokens, two httpOnly cookies and no passwordHash".
- V05 — Login failures do not reveal accounts — proof: `tests/auth.test.ts` "unknown email and wrong password answer the same 401" and "blocked account answers 403".
- V06 — Refresh rotates and a replayed token revokes every session — proof: `tests/auth.test.ts` "refresh rotates the refresh token", "replaying a rotated token after the grace window revokes all sessions" (a second device's refresh then answers 401).
- V07 — A concurrent retry inside the grace window is not an attack — proof: `tests/services/session.test.ts` "a previous token within 30 s rotates again without revocation" (`setSystemTime`).
- V08 — Sliding lifetime with an absolute cap — proof: `tests/services/session.test.ts` "rotation extends expiresAt by 30 d" and "expiresAt never passes absoluteExpiresAt".
- V09 — Logout — proof: `tests/auth.test.ts` "logout answers 204, clears cookies and the refresh token no longer works" and "logout all revokes a second device".
- V10 — Bearer header accepted and wins — proof: `tests/user.test.ts` "me answers 200 with a bearer token" and `tests/middleware/auth.test.ts` "the header wins over the cookie".
- V11 — OTP request is enumeration-safe and the code is delivered, not logged — proof: `tests/auth.test.ts` "otp answers 202 for an unknown target", "the code is in the captured message and absent from the log sink".
- V12 — OTP verification — proof: `tests/auth.test.ts` "otp login answers 200 with tokens", "a wrong code answers 401", "the fifth wrong attempt deletes the code", "an expired code answers 401", "verify sets emailVerifiedAt and returns no tokens", "verify without a caller answers 401", "verify for another user's email answers 403 on both endpoints".
- V13 — Rate limits — proof: `tests/middleware/rate-limit.test.ts` "answers 429 with Retry-After past the limit and resets after the window"; `tests/auth.test.ts` "login is limited per email".
- V14 — Role gates at both layers — proof: `tests/user.test.ts` "list answers 403 for a user and 200 for an admin" and "listUser with a user caller throws forbidden from the controller".
- V15 — Readiness reports the three dependencies — proof: `tests/health.test.ts` "ready lists memory, pubsub and scheduler".
- V16 — Jobs and events work and fail safely — proof: `tests/infra/scheduler.test.ts` "runs a job and survives a throwing job", "does nothing when JOBS_ENABLED is false"; `tests/services/event.test.ts` "a throwing subscriber does not block another"; `tests/auth.test.ts` "register delivers the welcome template through user.registered".
- V17 — The `api-design` worked example compiles and lints in the new layout — proof: blocks extracted into `src/api/post/` with a stub repository, `tsc --noEmit` and `eslint src/api/post` exit 0.
- V18 — The lint zones enforce every named rule — proof: probe files in the scaffold, one per rule in step 12 (`controller.ts → ../../services/db`, `service.ts → ../other/service`, `services/utils/x → ../logger`, `middleware/x → ../api/user/controller`, `infra/scheduler → ../middleware/auth`, `api/user/schema → ../../infra/memory`, `services/session → ../infra/memory`, `services/x → ../config/routes`, `infra/jobs/x → ../../api/user/service`, `models/user/x → ../../config/env`, `server.ts → ./api/user/route`), each refused with its message; lint clean after removal.
- V19 — No stale path remains — proof: `grep -rn "lib/\|lifecycle\|resources\.ts\|src/env\.ts\|infra/logger\|infra/db/" templates AGENTS.md .claude README.md .doc` finds nothing outside plans 001–004.
- V20 — Templates match the scaffold's Prettier output — proof: `diff -r` between `templates/backend` and the scaffolded `backend/` differs only in `__PROJECT_NAME__` substitutions and `openapi.json`.
- V21 — Production fails fast without secrets, development warns — proof: `NODE_ENV=production bun run src/index.ts` exits 1 naming the missing variable; `bun run dev` logs one `warn` per defaulted secret.
- V22 — The flows work by hand — proof: curl smoke in the scaffold: register → login → `GET /api/user/me` with the body token and with the cookie → refresh → replay the old token after 30 s → 401 and the current token dead → logout; `POST /api/auth/otp` prints the code in the development console and completes an OTP login.

## Risks

- Scope: this is the largest template change so far (≈ 60 new or moved files). Mitigation:
  dependency-ordered steps, each with its tests, in a scratch scaffold; copy back only
  when V02 is green; the fresh bootstrap (V01, V20) is the gate.
- The import table is intricate and a wrong zone silently allows a bad import.
  Mitigation: V18 probes one file per named rule; every zone carries its message.
- Replay detection with a grace window is a security-sensitive rule. Mitigation: V06–V08
  pin it with `setSystemTime`; the `api-design` skill states the policy in one paragraph.
- Development printing of OTP codes could leak into production. Mitigation: gated on
  `NODE_ENV === 'development'` in one place, tested (V11 in test mode shows no body).
- `services/` holding both pure and stateful code blurs over time. Mitigation: the
  `services/utils/` zone (no `infra/`, no other `services/`) and the table row.
- The data-layer task now rewrites more files (`db.ts`, repositories, `session.ts`).
  Mitigation: the `database` skill lists them; the first real data-layer run is the next
  validation worth doing (memory note).
- Copy-and-rename of `module` can collide with the word "module" in comments (C9).
  Mitigation: the README names the two tokens to rename; identifiers use `Module`/`module`
  as whole words.

## Rollout Order

packages and config → utils and logger → dependency, memory, db, cache → middleware →
models → security and session → communicate → events, jobs, scheduler → auth middleware →
user, auth, module, health → routes, server, openapi, index → lint zones → tests green
(V02) → copy to `templates/backend` → compose → `AGENTS.md` → skills → agents → README →
`.doc` → plan pointers → fresh bootstrap and V01–V22.

## Rollback

Discard the uncommitted changes to the files in Scope (a human does; nothing is
committed). No data, no generated artifacts and no scaffolded project are affected; a
scratch scaffold is deleted by hand.
