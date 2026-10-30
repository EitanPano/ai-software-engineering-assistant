# Frontend foundation: layers, design system, one way to mutate, read, authenticate and test

Status: done
Owner: Eitan
Last updated: 2026-10-27
Approval: the design was approved by Eitan on 2026-10-26 ("approved"); this plan was approved
by him on 2026-10-26 ("approved"), which confirms OQ1–OQ4 as recommended.
Input:
- `.superpowers/specs/2026-10-26-lean-loop-and-frontend-foundation-design.md`, Part A and the
  Delivery section's Phase 2 (git-ignored);
- the catalog survey `.superpowers/sdd/013-frontend-foundation/catalog-facts.md` (git-ignored),
  which the Assumptions below cite.

Scope ruling (2026-10-26): only this repository and the catalog
(`C:/Dev/Playground/AI/fullstack-templates`). Nothing else is read, written or run.
Branches:
- catalog `feat/frontend-foundation`, cut from `dev` (f1f38e7, which is also `main` and v1.3.0);
- harness `feat/frontend-foundation`, cut from `dev` (f0072e7). It carries only this plan; the
  harness adopts the foundation in Phase 3.
Base: catalog f1f38e7 · harness f0072e7
Stages: catalog work. No role agent runs. The interactive session drives Sonnet implementers,
with a Sonnet review per task and one Opus final review of the catalog branch. The plan ends in
one catalog PR into `dev`, a release, and no harness change beyond this file.

## Goal

The frontend templates get what the backend already has. Every addition has one home, the
agents compose a design system instead of inventing markup, there is one way each to mutate,
read, authenticate, handle errors and test, and lint enforces the map. The v1 eval showed the
cost of not having this:

- the agent had one button and nothing else;
- form plumbing was pasted twice and validation limits copied by hand;
- every action carried its own try/catch and status switch;
- auth was checked inline on each page;
- dates were hand-rolled;
- e2e ran against the development database and a live rate limiter;
- the slug stood in for the brand.

After this plan, `frontend/next` 2.0.0 and `frontend/react` 2.0.0 ship:

- Feature-Sliced layers enforced by `eslint-plugin-boundaries`;
- shadcn/ui primitives and layout patterns on OKLCH tokens, built from brand inputs at
  generation;
- Hey API codegen (types, client and zod);
- next-safe-action with a `call` helper for mutations;
- React Hook Form field bindings;
- tagged Cache Components reads (TanStack Query in the SPA);
- the auth flows and a data access layer when the server has auth;
- date-fns with time zones;
- production-build e2e against an isolated `app_e2e` database.

The server templates gain e2e support only. The generator gains brand inputs and lets a frontend
see the server's flags.

## Scope

**In** (catalog):

- `docs/adr/0005-frontend-foundation.md` (new), `docs/conventions.md`, `CONTRIBUTING.md`,
  `docs/capabilities.md` (cross-package selections).
- `tools/`: the CLI options for brand inputs, `tools/lib/theme.ts` (new), cross-package
  selections and `onlyWhen`, the `e2eDb` command name, the placeholders, the provenance schema,
  and the template schema. All with tests.
- `frontend/next/` 2.0.0 and `frontend/react/` 2.0.0: `base/`, `template.yaml`, `compose.yaml`,
  `tests/cases.yaml`, `CHANGELOG.md`, `README.md`.
- `server/bun-express/` 2.4.0 and `server/python-fastapi/` 1.2.0:
  - rate-limit scale from the environment;
  - the `e2eDb` command;
  - quiet expected-error logs in tests;
  - the compose warning on infra-only commands.
- `shared/providers/database/postgres/` (the `e2e` database URL in the env contract).
- `index.yaml`, `README.md` (the matrix), `.github/workflows/` (a Next app case),
  `stacks/*` if needed.
- The release: catalog `v1.4.0` (OQ3), with notes.

**In** (harness): this plan and its ledger `.superpowers/sdd/013-frontend-foundation/`.

**Out:**

- Every harness change that adopts the foundation is Phase 3, with its own plan:
  - `AGENTS.md`'s frontend section;
  - `naming.md`'s widget, entity and feature naming;
  - `ui-and-styling.md`;
  - the `ui-design` skill;
  - the bootstrap's brand intake;
  - the frontend and QA agents;
  - the `catalog.lock` bump to `v1.4.0`.
- A route or script that creates an admin. Proposed backlog line:
  `- [ ] server: a script that sets a user's role (first staff account)`.
- A `reason` field in the server's error envelope. The backend stays as plan 005 shaped it; a
  product adds a discriminator in its own contract.
- Password reset, change password, OTP flows in the UI, and email verification UI. The server
  ships the routes, the template ships only sign-up, sign-in and sign-out.
- Storybook, visual-regression baselines, i18n, and a component library of our own beyond
  shadcn's copied source and our patterns.
- Proof P2 (Phase 4).

## Assumptions

- The catalog facts hold as surveyed at f1f38e7 (`catalog-facts.md`). In particular:
  - flags are boolean and per package (§1);
  - markers cannot live in `.css` or `.json` (§1.4);
  - `postGenerate` runs a closed set of command names without a shell (§5.3);
  - the error envelope is `{ error: { code, message, details? }, requestId }` with no `reason`
    (§2.2);
  - tokens travel as HttpOnly cookies and in the JSON body, and Bearer wins (§2.3);
  - rate limits are constants (§2.6);
  - there is no `app_e2e` database (§8);
  - CI is ubuntu only, with 30 minutes per case (§6.3).
- ESLint stays on 9 and TypeScript on 5.9 in the templates (`CONTRIBUTING.md:321-323`). React
  stays 19.3.0 and Next 16.4.2 unless a spike says otherwise. Every new library is pinned exactly
  after checking the registry, its peer ranges and its age (≥ 14 days).
- `docs/conventions.md` and the ADRs are the catalog's source of truth. ADR 0005 supersedes the
  parts of ADR 0004 named in D1, and changes nothing else.
- A schema field added as optional keeps `schemaVersion: 1`, as ADR 0004 did. `CONTRIBUTING.md`
  then makes this catalog release a minor (OQ3).
- The catalog's CI runs every case on its own runner. A Postgres case publishes host port 5432.
  A local run on Windows can collide with a running project's database: the session checks the
  port first and never stops another project's container.
- Eitan's rules hold:
  - Sonnet implementers and per-task reviews, an Opus final review;
  - Conventional Commits;
  - no commit, push, PR, merge or tag without his yes at the time;
  - only this repository and the catalog are in scope.

## Open Questions

Each comes with my recommendation. Flipping the status confirms them all.

1. **Frontend auth: does the template ship the auth flows?** Recommended: yes, when the server
   has auth.
   - The Next template ships sign-up, sign-in and sign-out, the session data access layer, the
     `(auth)` route group, token refresh in `proxy.ts`, and the `UserMenu`. The SPA ships the
     same flows with a refreshing client and route guards.
   - The generator learns cross-package selections (D5), so these files exist only when the
     server package's `auth` flag is on.
   - v1 spent 39 minutes of its first task rebuilding this, and every product with accounts
     needs it.
   - Alternative: a documented recipe. It is cheaper now, but every product rebuilds the flows.
2. **E2E database: `init.sql`, or created on demand?** Recommended: on demand.
   - A new server command, `e2eDb`, creates `app_e2e` if it is missing (the `app` role is the
     image's superuser), migrates it and truncates it.
   - It refuses any database whose name does not end in `_e2e`.
   - `init.sql` runs only on a fresh volume (`init.sql:1-2`), so adding `app_e2e` there would
     miss every existing developer volume.
3. **Release numbering.** Recommended: catalog `v1.4.0`, a minor. The template majors are
   `frontend/next` 2.0.0 and `frontend/react` 2.0.0; the server minors are `bun-express` 2.4.0 and
   `python-fastapi` 1.2.0. Every schema change is an optional field, so `schemaVersion` stays 1
   (the ADR 0004 precedent). The harness pins the tag in Phase 3.
4. **The Next server forwarding the browser's address.** Recommended: decided by spike S5.
   - Today every browser shares the Next server's per-IP rate-limit bucket (§2.6).
   - The fix forwards the address Next received on its socket, never a client-supplied
     `X-Forwarded-For`.
   - If S5 finds no unspoofable source, the template documents the collapse and keeps the
     per-email limits.

## Steps

### Gates

- **G0 (session):** harness branch cut (done). Catalog `feat/frontend-foundation` cut from `dev`
  after G1.
- **G1 (Eitan):** `Status: active` on this plan.
- **G2 (session):** the spikes S1–S5 pass, or their fallbacks are recorded in "Changes during the
  task" before wave 1 starts.
- **G3 (Eitan):** yes to the catalog commits and the PR into `dev`, after the final review and
  the local proofs.
- **G4 (Eitan):** yes to the release: `dev` → `main`, then the tag `v1.4.0` and its notes.

### Spikes (throwaway, in a scratch folder; each generates `next-bun-express` with the current generator)

| Spike | Passes when | Fallback |
| --- | --- | --- |
| S1 Hey API | `@hey-api/openapi-ts` (client-fetch, typescript and zod plugins) generates from both servers' `openapi.json`. A POST with a JSON body works from a Server Action and from `proxy.ts`, which is v1's "expected non-null body source" crash. A generated request schema works in `zodResolver` once extended for form strings. | `openapi-typescript` plus `openapi-fetch` stay, and Hey API's zod plugin is added alone. |
| S2 Cache Components | With `cacheComponents: true`: an authenticated shell with a Suspense'd `UserMenu` works; a public read uses `'use cache'` with `cacheTag`; `updateTag` from an action gives read-your-own-writes; `next build` passes. | No `cacheComponents`. Reads use `fetch` with `next: { tags }`, under the same `updateTag` discipline. |
| S3 next-safe-action v8 with the RHF adapter | On React 19.3 and Next 16.4: server field errors land on their fields; `executeAsync`'s toast fires after the row unmounts; middleware `ctx` reaches the action. | `useActionState` with our own Field bindings and the same `call` helper. |
| S4 `pointer-coarse` | Tailwind v4's `pointer-coarse:` variant matches Playwright's `Pixel 7` project (`hasTouch`) and not `Desktop Chrome`. | 44 px on every pointer (today's rule). |
| S5 client address | The Next server can read the browser's socket address (or a value Next itself set), and the API, with `TRUST_PROXY=1`, keys its limit on it. A client-sent `X-Forwarded-For` cannot move that key. | No forwarding. `deployment` and the Next `AGENTS.md` document the shared bucket and point to the per-email limits. |

The session records each result, with the versions tried, in the ledger.

### Decisions (implementers do not reopen them)

- **D1 ADR 0005 and the docs.**
  - `docs/adr/0005-frontend-foundation.md` records D2–D15 and their tradeoffs from spec Part A.
    Its worked example is spec A12.
  - It supersedes these parts of ADR 0004:
    - "no component library" (now shadcn);
    - "no runtime theme switching" (now next-themes);
    - U2's token set (now OKLCH and the shadcn set);
    - U3's 44 px on every pointer (now under `pointer-coarse`);
    - "`shared/ui/button` is the one place for a button" (now `shared/ui` primitives);
    - U5's "e2e uses the development database" (now `app_e2e`).
  - The rest of ADR 0004 stands: the shell landmarks, the 4 px spacing rule, the phone project
    and `by_ip`.
  - `docs/conventions.md`'s frontend and SPA sections are rewritten to the D2 layers.
    `CONTRIBUTING.md`'s SPA checklist and its "Refreshing `base`" sections name the new pieces.
- **D2 Layers** (both templates; spec A1):
  - The layers are `app/` (routing only, with route groups), `widget/<section>/`,
    `feature/<action>/`, `entity/<noun>/`, and `shared/` (`ui/`, `ui/form/`, `ui/pattern/`,
    `lib/`, `api/`, `auth/`, `config/env.ts`). `src/lib/api/` moves to `src/shared/api/`, and
    `src/env.ts` to `src/shared/config/env.ts`.
  - The data layer is `server/` in Next and `api/` in the SPA.
  - `eslint-plugin-boundaries` (exact pin, ESLint 9 compatible) replaces the hand-written zones.
    The rules are spec A1's list, and each message names the layer to use instead.
  - `no-restricted-syntax` forbids the `button`, `input`, `select` and `textarea` JSX elements
    outside `shared/ui`. `revalidatePath` and a bare `fetch(` are restricted outside
    `shared/api`.
  - The seeded-violation test is rewritten for the new rules: one violation and one allowed case
    per rule.
  - The template's example slices are product-neutral:
    - `entity/health/` (model, `server/` or `api/` loader, a `HealthBadge`);
    - `widget/system-status/`;
    - `feature/refresh-health/`;
    - and, when the server has auth, `feature/auth/` and `entity/user/`.
- **D3 Design system** (spec A2):
  - shadcn/ui on Radix. The CLI is pinned, and `components.json` maps `ui` to `@/shared/ui` and
    `utils` to `@/shared/lib/cn`. The template ships spec A2's primitive list and pattern list,
    adapted to the router: `Link` versus `NavLink`, and a Sheet on phones.
  - `AGENTS.md` names `bunx shadcn@<pin> add <name>` as the one scaffolder an agent may run;
    `shadcn init` stays forbidden.
  - The tokens are shadcn's semantic set in OKLCH, plus `success`, `warning` and `info`. Light
    values sit in `:root` and dark values in `.dark`, with `@custom-variant dark`.
  - `next-themes` (Next) and a small `ThemeProvider` (SPA) use `attribute="class"`, take the
    default from D4 and add a toggle in the `UserMenu`. The template's `UserMenu` is a theme menu
    when auth is off.
  - Sizing follows S4. Badges by meaning replace `StatusPill`'s palette literals. The toast rule
    is spec A2's: a toast fires from the handler after the await, never from an effect.
- **D4 Brand inputs** (generator; spec A3):
  - New CLI options, also accepted in the answers file under `answers.brand`:
    `--display-name`, `--brand-primary <hex>`, `--brand-neutral <hex>`, `--radius sm|md|lg`,
    `--font system|inter`, `--theme system|light|dark`, `--density comfortable|compact`. The
    defaults reproduce a neutral palette with today's blue as the primary.
  - `tools/lib/theme.ts` (pure, with unit tests):
    - builds OKLCH scales from the two seeds;
    - derives light and dark values for every D3 token;
    - checks WCAG contrast (text pairs ≥ 4.5:1; `input` and `ring` against the background
      ≥ 3:1) and moves lightness until each pair passes;
    - fails generation, naming the pair, when a seed cannot pass.
  - New generated placeholders:
    - `PROJECT_DISPLAY_NAME` feeds the metadata title template, the header and the footer;
    - `THEME_LIGHT` and `THEME_DARK` are the CSS declaration blocks placed into `globals.css`
      (placeholders work in `.css`);
    - `THEME_RADIUS` and `THEME_DEFAULT`.
  - `--font inter` uses `@fontsource-variable/inter` in both templates, with no network at build.
    `--density compact` sets the fine-pointer control heights; touch sizing is unaffected.
  - Provenance records `answers.brand`, with the schema extended by optional fields.
- **D5 Cross-package selections** (generator):
  - A frontend's selections gain `server:<name>` for each selection of the stack's server
    package: its flags and its capability kinds. Examples: `server:auth`, `server:database`.
    These names already pass the marker lexer (`markers.ts:52`).
  - A template may declare `onlyWhen: { "server:auth": [paths] }`. Those files are kept only
    when the selection is on.
  - `validate`'s dry run covers the combinations: a frontend case with an `auth=false` server,
    and an alone frontend, where every `server:*` selection is off.
  - The frontend has no flag of its own named `auth`, so `--flag auth=…` stays unambiguous.
  - `docs/capabilities.md` and the template schema document it.
- **D6 Contract codegen** (S1):
  - `contract` runs Hey API (exact pin) into `shared/api/generated/` (committed, never edited):
    types, a fetch client, and zod. The SPA also gets the react-query plugin.
  - `shared/api/client.ts` creates the client:
    - in Next, it runs on the server with `API_URL`, the `Authorization: Bearer` header from the
      session, and the S5 forwarding;
    - in the SPA, it uses the relative `/api` and same-origin cookies, plus D10's refresh.
  - A form schema extends the generated request schema. Limits are never copied.
- **D7 Mutations** (S3; spec A5):
  - `shared/lib/safe-action.ts` holds `action`, `accountAction` and `roleAction(role)`.
    `ActionError` carries copy we wrote, never the server's text. `handleServerError` logs and
    returns a generic message.
  - `shared/api/call.ts` maps a result to data or to an `ActionError`, using the feature's copy
    table keyed by the envelope's `code` (§2.2). A product whose contract adds a discriminator
    passes it as a second key.
  - `shared/lib/action.ts` (`ActionResult`) is retired. The SPA's mutations are TanStack Query
    `useMutation` with the same `call` and the same copy tables.
- **D8 Forms** (spec A6): React Hook Form (exact pin) with `zodResolver`, wired through
  `useHookFormAction` in Next and `useMutation` in the SPA.
  - `shared/ui/form/` holds `TextField`, `TextareaField`, `NumberField`, `SelectField`,
    `CheckboxField`, `PasswordField` and `DateTimeField` (zone-aware, D12).
  - A field error shows on its field, with `aria-invalid` and `aria-describedby`. The toast
    reports the outcome and never repeats a field error.
- **D9 Reads** (S2; spec A7):
  - **Next:**
    - `cacheComponents: true`;
    - public reads use `'use cache'` with `cacheTag('<entity>')` and a `cacheLife` profile;
    - per-user reads are dynamic, inside Suspense;
    - a cached loader throws on failure, and the widget renders `ErrorState`;
    - mutations call `updateTag` and never `revalidatePath`;
    - the session read is memoised with React `cache`.
  - **SPA:** TanStack Query with Hey API's query options. Route loaders call `ensureQueryData`,
    widgets call `useSuspenseQuery`, and mutations invalidate their entities' keys.
  - The `deployment` skill's replica paragraph is a Phase 3 harness item. The catalog's Next
    `AGENTS.md › Deployment` states the per-instance cache.
- **D10 Auth glue** (with `server:auth`; spec A8):
  - **Next:**
    - `shared/auth/session.ts` (server-only) provides `readSession` (React `cache`),
      `requireAccount()` (redirects to sign-in) and `requireRole(role)` (renders forbidden).
    - `feature/auth/server/action.ts` has `signUp`, `signIn` and `signOut`. They call the API and
      set `access_token` and `refresh_token` as HttpOnly, `SameSite=Lax`, Secure-in-production
      cookies on the Next origin, with the API's lifetimes.
    - `proxy.ts` refreshes an expired access token with the refresh token (body `refreshToken`,
      §2.3), rotates both cookies, and redirects on failure. It never checks permissions.
    - The route groups are `(auth)` (sign-in and sign-up; a signed-in account is sent away) and
      `(site)` (the shell).
    - `AGENTS.md` documents a `(site)/(staff)` group with `requireRole('admin')` in its layout,
      every page and every loader, and `roleAction` for its actions. The template ships no staff
      page: no admin can be created yet (Out).
  - **SPA:**
    - The client middleware turns a 401 into one `POST /api/auth/refresh` and a retry, and
      collapses concurrent refreshes into one.
    - Loaders guard routes with `requireAccount` and `requireRole`, and `RequireRole` hides
      controls.
    - The `(auth)` routes are the same as in Next.
  - The `UserMenu` (avatar, email, theme, sign out) is in the shell's account slot. The email is
    never shown as header text beside a primary button.
  - Unit tests cover:
    - the session helpers;
    - every action's success and failure paths (409 taken email, 401, 429);
    - refresh, including two concurrent 401s that cause one refresh;
    - the forbidden render.
  - E2E covers sign-up, sign-out, sign-in, a bad password, and the guarded redirect.
- **D11 Errors and loading** (spec A9):
  - `loading.tsx` and `error.tsx` exist per route group, not per segment.
  - Every widget has a skeleton that matches its layout.
  - Next gains `global-error.tsx`.
- **D12 Dates** (spec A10): `date-fns` v4 with `@date-fns/tz` in `shared/lib/date.ts`.
  - It converts a wall time to an instant and back in a named zone, computes day keys, and
    formats dates.
  - A time in a DST gap is refused, and an ambiguous time takes the earlier instant. Both are
    unit tested across a London transition.
- **D13 Tests and e2e** (spec A11):
  - **Unit:** Vitest with React Testing Library. The template tests its glue once: the field
    bindings, the shell nav, `call`, the action client, theme toggling, and the D10 helpers.
  - **E2E server:** Playwright's `webServer` runs the production build: `next build` then
    `next start` on 3000, or `vite build` then `vite preview` for the SPA.
  - **E2E backend:**
    - The backend starts fresh with `reuseExistingServer: false`, using the server's start
      command.
    - Its `env` sets `RATE_LIMIT_SCALE=100` and, with `server:database`, the provider's `e2e`
      URL (`app_e2e`).
    - `globalSetup` runs the server's `e2eDb` command when `server:database` is on.
    - The development database is never touched.
  - **Projects:**
    - `phone` (Pixel 7, touch) runs every journey with its axe scan.
    - `desktop` (Desktop Chrome) runs the shell spec and the screens spec.
    - `retries: 0`, and a trace is kept on failure.
  - **Screens spec:** `screens.spec.ts` captures every `nav.ts` route, plus sign-in and sign-up
    when auth is on, in phone and desktop, light and dark, to
    `test-results/screens/<route>-<viewport>-<theme>.png`.
  - **SPA:** `E2E_BASE_URL` keeps its container mode, and Next gains the same switch.
- **D14 Server templates** (`bun-express` 2.4.0, `python-fastapi` 1.2.0):
  - **Rate-limit scale:** `RATE_LIMIT_SCALE` (a number ≥ 1, default 1, read once in the env
    module, documented in `.env.example`) multiplies every limit in `RATE_LIMITS`. Production
    keeps the default. There is no bypass switch.
  - **`e2eDb`:** a new command name in the schema's `commands` enum.
    - It creates the database named by the provider's `e2e` URL if it is missing, migrates it,
      and truncates every table except the migrations table.
    - It refuses any database whose name does not end in `_e2e`.
    - It exists only with a database provider (overlay `commands`).
  - **The provider's env contract** gains `e2e: postgres://app:app@127.0.0.1:5432/app_e2e`.
  - **Test logs:** tests that raise errors on purpose capture or silence them (§8: "boom",
    pubsub, PostgresError). A green run prints no stack trace.
  - **The Compose fragment** stops warning about unset app secrets on infra-only commands
    (`docker compose up -d --wait database`).
- **D15 Versions, cases and CI:**
  - `index.yaml`, every template's `template.yaml` and `CHANGELOG.md` are bumped as OQ3 says.
  - `frontend/next/tests/cases.yaml` gains:
    - `stack-postgres` (`next-bun-express`, postgres, `withApp`);
    - `python` (`next-python-fastapi`);
    - `auth-off` (the server with `auth=false`).
  - These need cases to set the server's flags and capabilities from a frontend case, which is a
    `cases.schema.json` change.
  - A Next `withApp` case runs its production e2e against the image with `E2E_BASE_URL`.
  - CI keeps one runner per case. The 30-minute budget is checked against the slowest new case,
    and any increase is recorded.

### Tasks

They run in waves. Implementers use Sonnet and work on disjoint paths of one catalog checkout,
with a Sonnet review after each task.

0. **C0, spikes** (S1–S5), one implementer per spike or one for all of them. The scratch apps
   live under the session scratchpad. Output: the ledger rows and the versions to pin.
1. **Wave 1, in parallel:**
   - **C1, ADR and docs** (D1): ADR 0005, `docs/conventions.md`, `CONTRIBUTING.md`,
     `docs/capabilities.md`.
   - **C2, generator** (D4, D5, D14's command name, D15's case schema): `tools/` and
     `schemas/`, with their tests and the fixture catalog.
   - **C3, servers** (D14): `server/bun-express/`, `server/python-fastapi/`, and
     `shared/providers/database/postgres/`.
   - **C4, Next foundation** (D2, D3, D11): layers, lint, primitives, patterns, tokens with the
     D4 placeholders, theming, the shell, and the health slices.
2. **Wave 2:** **C5, Next data, auth and forms** (D6–D10, D12), on C2 and C4.
3. **Wave 3:** **C6, Next e2e** (D13), on C3 and C5.
4. **Wave 4:** **C7, the React SPA** (D2–D13 for the SPA, spec A13), on C4–C6's patterns.
5. **Wave 5:** **C8, release prep** (D15): `index.yaml`, the README matrix, CHANGELOGs,
   `cases.yaml`, workflows, `validate --readme`, and the release-notes draft.
6. **Final:** the Opus review of the catalog branch, then one fix wave and its re-review.

### Local proofs (the session drives; Windows; port 5432 checked first, other projects untouched)

1. `bun run check` in `tools/`, `bun tools/validate.ts` and `bun tools/validate.ts --lockfiles`.
2. `bun tools/test-generated.ts` with `--e2e --install-browsers --with-services --with-app`, for
   every case of the four templates. A case that cannot run locally is named, along with the
   reason; CI then runs it.
3. The screens from `frontend/next/stack-postgres` and `frontend/react/default`, in phone and
   desktop, light and dark, go to the ledger for Eitan's look (spec V6 is Phase 4's; this is an
   early read).

## Validation

- V01 — The generator's gates and `validate` pass, including the lockfiles and the dry run of
  every flag, capability and `server:*` combination. Proof: `bun run check` in `tools/`,
  `bun tools/validate.ts`, `bun tools/validate.ts --lockfiles`.
- V02 — `theme.ts`:
  - meets every contrast pair for the default seeds and for at least four other seeds;
  - names the pair when a seed cannot pass;
  - produces the same output for the same inputs.

  Proof: `tools/tests/theme.test.ts`.
- V03 — Cross-package selections:
  - an `auth=false` server leaves no `server:auth` file or line in the frontend, and that
    frontend's `check` passes;
  - an alone frontend gets every `server:*` selection off.

  Proof: generator tests, and the `frontend/next` `auth-off` case.
- V04 — Lint enforces the map. Each boundary rule, the raw-control rule and the
  `revalidatePath`/`fetch` rule has a seeded violation that fails and an allowed case that
  passes. Proof: each template's lint test.
- V05 — The production e2e passes on `phone` and `desktop`, including the auth journeys and the
  axe scans. It runs with `app_e2e`, and the development database's row counts are unchanged
  before and after. A repeat run in a row passes (no rate-limit carry-over). Proof:
  `test-generated --case frontend/next/stack-postgres --e2e --with-services` run twice, with a
  row count of the development database before and after.
- V06 — The same for the SPA. Proof: `frontend/react/default` and `split` with `--with-app`.
- V07 — The server templates:
  - `RATE_LIMIT_SCALE` multiplies every limit;
  - `e2eDb` refuses a name that does not end in `_e2e`, creates a missing database, and
    truncates;
  - a green test run prints no stack trace.

  Proof: the server cases, plus a log grep for `Error:` stack lines in the green runs.
- V08 — The goals' mechanical checks hold in both templates:
  - no raw form control outside `shared/ui` (lint);
  - no `revalidatePath` (lint);
  - no per-action status switch, since `call` is the only mapper (grep for `switch (` on
    `status` in `feature/`);
  - no copied limit, since every form schema extends a generated schema (grep).

  Proof: the commands, recorded in As built.
- V09 — Every spike S1–S5 is recorded as passed or fallen back, with the versions, and every
  fallback is reflected in the code and ADR 0005. Proof: the ledger and the ADR.
- V10 — ADR 0005, `docs/conventions.md`, `CONTRIBUTING.md` and both `AGENTS.md` files agree on
  the layers, the commands, the e2e rules and the scaffolder exception. Proof: the final review
  and a grep for the old paths (`src/lib/api`, `src/env.ts`, `ActionResult`, `chromium` project).
- V11 — CI on the PR is green for every case. Proof: the PR's checks.
- V12 — Each task had a Sonnet review, and the branch had an Opus final review, with no open P0
  or P1. Proof: the ledger.

## Risks

- **Many new libraries at once** (Hey API 0.x, next-safe-action, RHF, Radix, TanStack Query,
  date-fns tz, eslint-plugin-boundaries). Mitigation:
  - the spikes;
  - exact pins verified against the registry;
  - a worked example per library in the template;
  - Next's in-package docs read first.
- **Hey API's 0.x minors break.** Mitigation: an exact pin, upgrades only by plan, and the S1
  fallback.
- **Cache Components and auth interact badly** (a cached read capturing a user). Mitigation:
  public reads only are cached, and S2 tests the authenticated shell. A unit test asserts that
  no `'use cache'` function reads cookies or headers.
- **The token relay in Next is security-sensitive** (cookies, refresh, proxy). Mitigation:
  - HttpOnly, SameSite=Lax, Secure in production, and the API's lifetimes;
  - refresh only in `proxy.ts`, and permission checks only in the DAL;
  - unit tests for refresh races;
  - the Opus final review reads `shared/auth` and `proxy.ts` as security code.
- **The CI budget.** Production builds add one to two minutes per frontend case. Mitigation: one
  build per run, `phone` journeys only, and the budget checked in C8.
- **Port 5432 locally.** Another project's container can hold it. Mitigation: the session checks
  first and asks. It never stops a container it did not start.
- **Cross-package selections widen the generator's surface.** Mitigation: one mechanism
  (selections plus `onlyWhen`), covered by `validate`'s dry run and the fixture catalog's tests.
- **Phase 3 drift.** The harness still describes the v1.3.0 layout until the lock bump.
  Mitigation: the lock stays on v1.3.0 until Phase 3 lands its text in the same PR as the bump.

## Rollout Order

1. G1, then G0's catalog branch, then C0 and G2.
2. Wave 1 (C1 ∥ C2 ∥ C3 ∥ C4), then wave 2 (C5), wave 3 (C6), wave 4 (C7) and wave 5 (C8). A
   Sonnet review follows each task.
3. The Opus final review, then the fix wave and its re-review.
4. The local proofs, then G3: the catalog commits and the PR into `dev`, with CI green (V11).
5. G4: `dev` → `main` in the catalog, then the tag `v1.4.0` and the release.
6. Phase 3 (the harness) is planned after the tag. It bumps `catalog.lock` together with the
   harness text.

## Rollback

- The catalog PR into `dev` reverts as one merge commit. The tag is not moved: a fix is
  `v1.4.1`.
- Projects generated from v1.3.0 are untouched: templates are copied, not linked.
- The harness keeps pinning v1.3.0 until Phase 3, so nothing that consumes the harness changes in
  this plan.

## Changes during the task

<!-- the driver records rulings that change a decision above, with the date -->

- 2026-10-26, S4 passed: `pointer-coarse:` sizing as D3 says. Icon buttons use
  `pointer-coarse:size-11`.
- 2026-10-26, S5 failed, so the fallback applies (OQ4):
  - Next 16.4.2 fills `x-forwarded-for` from the socket only when the client sent none. A
    client-sent value, including its last entry, reaches app code unchanged.
  - D6's Next client therefore forwards no `X-Forwarded-For`.
  - The Next `AGENTS.md › Deployment` documents the single per-IP bucket and the per-email
    limits. Forwarding is safe only behind a deploy proxy that overwrites the header.
- 2026-10-26: C2 and C3 started before G2. Neither depends on a spike.
- 2026-10-26, S3 passed. Pins: next-safe-action 8.7.3,
  `@next-safe-action/adapter-react-hook-form` 2.1.0, react-hook-form 7.90.0 and
  `@hookform/resolvers` 5.9.1.
- 2026-10-26, S1 passed. Pin: `@hey-api/openapi-ts` 0.99.0, as a dev dependency. The fetch client
  is emitted into `generated/`, so there is no runtime package.
- 2026-10-26, S2 passed, with one change to D9. A `'use cache'` loader in the static shell runs
  at `next build`, and the image build has no API. So every data widget is a request-time hole:
  an async component inside Suspense that first awaits `connection()`, then calls its cached
  loader. The build never calls the API, the cache works at request time, and `updateTag` still
  gives read-your-own-writes. `/` stays a Partial Prerender shell.
- G2 met: S1–S4 passed and S5 uses its fallback.
- 2026-10-26, D4: the brand defaults are `--display-name` (the project name in title case),
  `--radius md`, `--font system`, `--theme system` and `--density comfortable`. Both templates
  always depend on `@fontsource-variable/inter`, and `THEME_FONT_STACK` carries the
  `font-family`. `RATE_LIMIT_SCALE` is capped at 1000.
- 2026-10-27, D10:
  - The generator accepts parentheses in `onlyWhen` paths, so the `(auth)` group stays.
  - `proxy.ts` clears the cookies on a refusal and continues. Access is decided only in the
    session data access layer.
  - `requireRole` redirects to a stable `/forbidden` page. No experimental Next API
    (`forbidden()`, `authInterrupts`).
  - Model files may value-import the generated zod schemas.
- 2026-10-27, D6, refining the S5 fallback: an optional `CLIENT_IP_HEADER` (unset by default).
  When it is set, Next forwards the rightmost entry of that header as `X-Forwarded-For`.
  - Without it, every visitor shares one per-IP bucket on the API. Registration is limited to
    10 per 15 minutes per IP, so the whole site could register ten users per 15 minutes.
  - A production deploy behind a platform or proxy that sets or appends the header must set
    it.
- 2026-10-27, Rollout: the catalog's work in progress merged into `dev` early (catalog #11,
  8ef25ee), at Eitan's request. The harness pins the v1.3.0 tag, so no consumer saw it. The
  final review and the local proofs stayed before G4. The rest went through catalog #12.
- 2026-10-27, D13:
  - Playwright 1.64.1 starts its web servers before `globalSetup`, so there is no
    `globalSetup`. The API's web server command is `e2eDb && start`.
  - The `_e2e` URL guard is `scripts/e2e-database-url.ts`, because the image build typechecks
    `playwright.config.ts` and `.dockerignore` drops `tests/`. It runs only without
    `E2E_BASE_URL`. A blank `E2E_DATABASE_URL` or `E2E_BASE_URL` counts as unset.
  - Generation fails closed on a server without `start`, and on `server:database` without
    `e2eDb` or a provider `e2e` URL.
  - The phone and desktop projects select tests by `@phone` and `@desktop` tags with
    `grepInvert`, so no test is skipped at run time.
  - The URL wait after a sign-up or sign-in submit is 15 s, because password hashing is
    CPU-bound. Retries stay 0.
  - Both templates name their lint test `tests/unit/eslint-boundaries.test.ts`.
- 2026-10-27, D7 and D8 (Next): one submit helper (`ignoreNavigation`) swallows only Next's
  navigation errors (the `NEXT_REDIRECT`, `NEXT_NOT_FOUND` and `NEXT_HTTP_ERROR_FALLBACK`
  digests) and rethrows the rest. A server field error that no form field shows becomes a
  toast. The email check is the generated one plus `z.email()`, with our own wording for both,
  because only Python's OpenAPI marks emails `format: email`.
- 2026-10-27, D9 (SPA): route loaders call `queryClient.query`, since query-core 5.104.2
  deprecates `ensureQueryData`. They get fetch semantics with a 30 s `staleTime`. The
  react-query plugin runs with `infiniteQueryOptions: false`, because no endpoint paginates
  yet.
- 2026-10-27, D10 (SPA):
  - The CSP is `script-src 'self'`, so the theme script is `public/theme-init.js`. zod runs with
    `jitless: true`, because its `new Function` probe broke the image's CSP.
  - A localStorage session hint (a flag, never a token) saves the per-IP refresh budget for
    anonymous visitors. A refresh answer of 400, 401 or 403 clears it.
  - `noindex` is client-side, an accepted SPA limitation. Splitting the 690 kB chunk is
    deferred.
- 2026-10-27, D6 (Next): compose passes `CLIENT_IP_HEADER`. Without it, a default Next deploy
  with auth tops out at about 30 active signed-in visitors per 15 min, the API's shared per-IP
  refresh budget. The Next `AGENTS.md › Deployment` states the cap and the production recipe.
- 2026-10-27, D14 and D15: compose fragments write a secret as `${NAME-}` and an optional
  setting as `${NAME:-}`. The case runner generates a value only for the first kind. Before
  this rule it filled every variable, so `CLIENT_IP_HEADER` got a random, invalid value.
  `CONTRIBUTING.md` states the rule.

## As built

2026-10-27. Catalog `feat/frontend-foundation`, from f1f38e7:

- Catalog #11 (work in progress) merged into `dev` as 8ef25ee.
- Catalog #12 merged into `dev` as 59df042. It carried five commits:
  - df46a12 `feat(react)`;
  - ae1b9a5 `fix(next)`;
  - 298f2d0 `fix(tools)`;
  - 65e9da5 `docs`;
  - 7f49b88 `chore(catalog)`.

  The tree of `dev` is d64cf3f, the tree the local proofs ran on.
- The templates: `frontend/next` 2.0.0, `frontend/react` 2.0.0, `server/bun-express` 2.4.0,
  `server/python-fastapi` 1.2.0. `schemaVersion` stays 1. The release notes draft is in the
  ledger (`v1.4.0-tag.txt`).
- Reviews:
  - each of C1–C8 had a Sonnet task review, with scoped re-reviews of its fix rounds (at most
    2);
  - the Opus final review found 3 P1s and 10 P2s, and its re-review of the fix wave found 1 more
    P1 (mojibake in the SPA's pending labels) and 3 more P2s;
  - all are fixed.
- Two defects that the reviews missed were caught by the proof runs. The case runner filled
  optional compose settings (the D14 and D15 change above). An e2e test clicked a Radix
  trigger before hydration, fixed by a `toPass` open helper.

| Item | Result |
| --- | --- |
| V01 | `bun run check` in `tools/` → 662 pass, 0 fail; `bun tools/validate.ts` and `--lockfiles` → ok |
| V02–V04 | `tools/tests/theme.test.ts`, the generator tests and the `auth-off` cases; each template's `tests/unit/eslint-boundaries.test.ts` |
| V05 | A generated `next-bun-express` with Postgres, on a tmpfs development database: 36/36 twice (30.3 s, 23.5 s). `app` held module 0, schema_migration 1, session 0, user 0 before and after both runs; `app_e2e` held user 5, session 7 after each |
| V06 | The same for `react-python-fastapi` with Postgres: 38/38 twice (13.2 s, 13.0 s), with the same counts |
| V07 | The 8 server-only cases pass. Unit tests pin `RATE_LIMIT_SCALE` (its cap) and `e2eDb` (its `_e2e` and `dbname` refusals); the e2e runs exercise the create, migrate and truncate. The C3 and C5 case logs hold no `at …` or `Traceback` line |
| V08 | `git grep` on catalog `dev`: no `switch (` on a status under `feature/`, `widget/` or `entity/`; no `.min(N)`, `.max(N)` or `.length(N)` in `src` outside `generated/` (the one hit is `Math.max` in `cookies.ts`); `revalidatePath(` only in the lint test's seeded violation; no raw control outside `shared/ui`; no `.skip(` or `.only(` |
| V09 | The ledger's Spikes section and ADR 0005 (S2's `connection()` hole, S5's fallback with `CLIENT_IP_HEADER`) |
| V10 | The final review's agreement check and the old-path grep: the old paths appear only as history in ADR 0003, ADR 0005 and the CHANGELOGs |
| V11 | Catalog #12: 28 of 28 checks green (26 cases plus `list` and `validate`) |
| V12 | The ledger: the task reviews, the Opus final review and its re-review, with no open P0 or P1 |

Local proof 2 ran all 26 cases with `--e2e --install-browsers --with-services --with-app` on a
quiet machine. The 18 frontend and stack cases ran on the final tree; the slowest was
`server/python-fastapi/stack-postgres` at 229 s. The 8 server-only cases come from the run
before, and their code has not changed since. `frontend/react/default` failed once on
`net::ERR_NO_BUFFER_SPACE` (Windows socket exhaustion) and passed on the re-run. Local proof 3
(screens for Eitan's look) was not collected. `screens.spec.ts` captures them on every e2e run,
and spec V6 judges them in Phase 4.

Release (G4, 2026-10-27, Eitan: "yes"):

- Catalog #13 (`dev` → `main`) had 56/56 checks green and merged into `main` as 5b04a32, tree
  d64cf3f.
- The annotated tag `v1.4.0` is on 5b04a32.
- The release workflow (run 40560420922, 29 jobs) re-ran `validate` and every case, then
  published the release.

Open:

- Phase 3 gets its own plan, in a new session. It bumps `catalog.lock` to v1.4.0 together with
  the harness text. Until then, harness `main` pins v1.3.0.
- Proposed backlog line: `- [ ] Servers key the refresh rate limit on the refresh token`, to
  remove the Next cap that applies when `CLIENT_IP_HEADER` is unset.
- Left for Eitan:
  - the Docker volume `c6bcounts_database-data` (the hook refuses `docker volume rm`);
  - the `%TEMP%` `fullstack-case-*` folders;
  - the session's scratchpad `v05v06/`.
