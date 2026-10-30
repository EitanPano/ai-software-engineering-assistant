# Harness upgrade — full-stack project capability

Status: done (executed, reviewed and fixed 2026-10-20; uncommitted, awaiting Eitan's review)
Owner: Eitan
Last updated: 2026-10-20
Revision: on review (2026-10-20) Eitan rejected the database-specific backend (Drizzle, Postgres, pino, the `module/` layout); `.plan/002-2026-10-20-engine-neutral-backend.md` supersedes those parts of Tasks 3–5 and the matching Assumptions.
Approval: Eitan's instruction on 2026-10-20: "fix the required issues so that this project
would rank higher. the ability to create a well designed and architectured full-stack
project is what needs to rank higher." Executed unattended on that instruction; every
design call below is listed under Assumptions so it can be reversed on review.
Branch: `feat/fullstack-capability` (off `chore/harness-audit-fixes`)

> **For agentic workers:** execute task-by-task with `superpowers:executing-plans`
> (native, this session). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a developer clones this repository, opens Claude Code, and can go from an empty
`.doc/` to a running, tested, well-layered full-stack project and then deliver features
through the dev loop, with the harness deciding the architecture instead of the first
scaffold run.

**Architecture:** the harness ships the decisions (one stack rule, one architecture rule,
one definition of done, all inlined in `AGENTS.md`), the procedure (`bootstrap-project`
and `dev-loop` skills, five role agents), the enforcement (hooks keyed on `agent_type`,
write lanes per role), and the starting point (`templates/` plus `scripts/bootstrap.mjs`
that scaffold `frontend/` and `backend/` deterministically). The API contract is generated
from the backend's zod schemas and consumed by the frontend as generated types, so the two
halves cannot drift silently.

**Tech Stack:** Bun 1.4 (package manager, script runner, backend runtime), Node 24 (Next.js
runtime), Next.js 16 App Router + React 19 + TypeScript + Tailwind v4, Express 5, zod 4,
Drizzle ORM + Postgres 17, `@asteasolutions/zod-to-openapi`, `openapi-typescript` +
`openapi-fetch`, Vitest + React Testing Library + Playwright (frontend), `bun test` +
supertest (backend), ESLint 9 flat config + Prettier, Docker Compose.

**Spec:** the audit synthesis (`git show main:.orchestrate/audit/SUMMARY.md`, Phases 1–4),
the comparison in the 2026-10-20 session (main 3/10, Phase 0 branch 4.5/10), and Eitan's
recorded decisions restated under Assumptions.

## Goal

After this plan, on a fresh clone with Bun 1.4, Node 24 and Docker:

- `/bootstrap-project` walks the `.doc/` forms, runs `scripts/bootstrap.mjs`, and ends with
  `frontend/` and `backend/` both passing `bun run check`, a Postgres container running,
  the first migration applied, and the first backlog line written.
- `/dev-loop` takes one backlog task through plan → approval → backend → frontend →
  five parallel reviewers → QA → commit gate, with no reference to a driver script that does
  not exist and no mandatory third-party service.
- Every agent reads the stack, layering and definition-of-done from `AGENTS.md`; no agent or
  skill restates a version, a command or a directory layout.
- The guardrail hooks hold for the new layout, admit `general-purpose` implementers, and
  close the Bash write channel for role agents.

## Scope

In: `AGENTS.md` (rules inlined), `README.md`, `.doc/` forms, five agents, nine skills,
`templates/`, `scripts/bootstrap.mjs`, hooks and `settings.json`, `.gitignore`, backlog
grammar.

Out: a `SubagentStop` report validator, JSON stage reports, a plugin/template split,
CI workflow files for the harness itself, re-adding the hook test suite or a root
`package.json` (removed deliberately on 2026-10-20), the Figma-specific steps beyond a
conditional mention, i18n.

## Assumptions

Eitan's recorded decisions, applied as given:

- A1. Separate Express 5 service on Bun from day one; Bun is the runtime.
- A2. Rules are inlined into `AGENTS.md`; `.claude/rules/` goes away. (Reversed on
  2026-10-21 after the AGENTS.md split: the four rules live in `.claude/rules/` again,
  indexed by the Rules section of `AGENTS.md`; they load on their own, no `@` lines.)
- A3. Docker is the deployment target.
- A4. Linear is the default tracker.
- A5. Five parallel perspective reviewers form the review stage.
- A6. Singular routes. (The "Patefon module layout" is not on record; Task 3 uses
  `module/<name>/{route,schema,service,repository}.ts` and flags it.)
- A7. Unknown agent roles stay blocked; Windows-only case fold; force-push blocked with or
  without a lease.

Calls made in this plan (reversible, each has a one-line tradeoff in the file it lands in):

- C1. No root `package.json`: `frontend/` and `backend/` are independent packages, each
  with its own install, scripts and Dockerfile. Loses a single `bun install`; gains two
  self-contained deployables and respects the 2026-10-20 removal.
- C2. Backend tests run with `bun test` so they exercise the real runtime; frontend tests
  run with Vitest because React Testing Library and jsdom live there. Two runners, each
  native to its runtime.
- C3. Drizzle uses `drizzle-orm/bun-sql` (Bun's built-in Postgres driver). Migrations are
  generated by `drizzle-kit generate` and applied by a script using the Drizzle migrator,
  so no second driver package is needed.
- C4. The contract flows backend → frontend: zod schemas registered to OpenAPI →
  `backend/openapi.json` (committed) → `frontend/src/lib/api/schema.d.ts` (generated,
  committed). The hand-written `.orchestrate/api-contract.yaml` is removed.
- C5. `general-purpose` gets an unrestricted write lane so generic implementers (the
  superpowers default) work in a clone; unknown roles still block.
- C6. Role agents may not write through the shell (`>`, `tee`, `sed -i`, `cp`, `mv`,
  `Set-Content`…); they use Edit/Write, which the lane hook sees.
- C7. Models: orchestrator and reviewer on Opus, backend/frontend/qa on Sonnet.
- C8. Conventional Commits (`type(scope): summary`) replace the bare imperative rule.
- C9. Linear stays the default tracker but the loop falls back to local ticket files in
  `.orchestrate/ticket/` when the Linear tool is absent, and says so.
- C10. Stage reports stay Markdown with a fixed header (`Verdict: pass | fail`); the JSON
  schema and `SubagentStop` validator are deferred.
- C11. The committed `frontend/AGENTS.md` that create-next-app generates is kept: `next dev`
  re-creates it, and its content (read the bundled Next.js docs before using an API)
  does not contradict the harness rules.
- C12. Next.js Cache Components (`cacheComponents: true`, which create-next-app 16.4
  enables) stays off: pages render dynamically through feature loaders, the explicit model
  for agents. Turning it on is a deliberate task. The Tailwind-in-Turbopack rule from the
  generated config is kept verbatim.
- C13. Role agents may not run git commands that change the tree or history, deletions,
  or inline interpreters (`node -e`); unknown roles (Claude Code's Explore and Plan) may
  run read-only shell commands but cannot write. Added after the review found that the
  first version blocked Explore from `ls` and let a role `git stash` away another stage's
  work.
- C14. Tests always target the `app_test` database; database-backed tests live in
  `describeDb` blocks and run only under `bun run test:db`, so `bun run check` never needs
  Docker. Services are tested through HTTP against that database, not through repository
  fakes (the reviewer suggested fakes; `mock.module` leaks across files in `bun test`).

## Open Questions

1. **Is the `module/<name>/{route,schema,service,repository}` layout the "Patefon"
   layout?** Recommended: treat it as the default until Eitan supplies the reference; the
   layout is one section of `AGENTS.md` and nothing else depends on the names.
2. **Should `bun test` on the backend be replaced by Vitest for a single runner?**
   Recommended: no; tests on the production runtime outweigh one extra runner.
3. **Should the harness ship `Read(**/*.pem)`-style deny rules in `settings.json` in
   addition to the secret hook?** Recommended: yes (Task 7); the deny layer is evaluated
   even if a hook allows.

## Steps

### Global constraints

- No trailing semicolons; a syntax-required semicolon starts the line.
- Hooks import only `node:` builtins and `./lib/guardrail.mjs`.
- Strings that the live hooks refuse (destructive spellings, env-file names) never appear
  on a Bash command line in this session: content goes through the Write tool, hook
  candidates are tested in the scratchpad with the matrix runner and copied into place
  only after `node --check` passes.
- Versions, commands and directory layouts are stated once, in `AGENTS.md`; every other
  file references them.
- Always-on context (`AGENTS.md`) stays under roughly 320 lines.

### Review focus

1. A hook edit that throws at module load bricks every tool call (catch-all matcher,
   block-on-failure): every hook change is syntax-checked and matrix-tested in the
   scratchpad before it is copied in (Task 7).
2. `bun run check` must pass on a fresh scaffold with no manual edits, or the bootstrap
   promise is false: Task 8 runs the real bootstrap in a scratch root.
3. `openapi.json` and `schema.d.ts` must regenerate identically from the templates, or the
   contract pipeline is decorative: Task 8 diffs after a second generation.
4. The reviewer agent must not be able to write app code: frontmatter tools plus lane.
5. `AGENTS.md` must not import files that no longer exist: Task 1 deletes `.claude/rules/`
   and the four `@` lines in the same step.

---

### Task 1: Rules inlined into `AGENTS.md`

**Files:**
- Modify: `AGENTS.md`
- Delete: `.claude/rules/code-style.md`, `naming.md`, `ui-and-styling.md`, `git-workflow.md`
- Modify: `CLAUDE.md` (text only; keeps `@AGENTS.md`)

**Produces:** sections `Stack`, `Architecture`, `Code style`, `Naming`, `UI and styling`,
`Git workflow`, `Definition of done`, `Skills`, `Guardrails`, `Repository layout`,
`Product and domain`. Every later task references these section names.

- [x] Write the new `AGENTS.md` with the stack (versions, commands, directories) stated once.
- [x] Delete the four rule files and the `@` import lines.
- [x] Verify: `grep -c "^@" AGENTS.md` prints 0; `ls .claude/rules` fails.

### Task 2: `.doc/` fill-in forms

**Files:**
- Modify: `.doc/product-definition.md`, `.doc/architecture.md`, `.doc/glossary.md`

- [x] Rewrite each as a form with `<!-- FILL: … -->` markers and a "ready to plan" checklist.
- [x] Verify: `grep -c "FILL:" .doc/*.md` is non-zero for all three.

### Task 3: Templates and bootstrap script

**Files:**
- Create: `templates/root/docker-compose.yml`, `templates/root/.editorconfig`
- Create: `templates/backend/**` (package.json, tsconfig, eslint, prettier, Dockerfile,
  `.env.example`, `drizzle.config.ts`, `src/{index,app,env,openapi}.ts`, `src/lib/{error,log,http}.ts`,
  `src/db/{client,schema,migrate}.ts`, `src/module/health/{route,schema,service}.ts`,
  `tests/health.test.ts`)
- Create: `templates/frontend/**` (overlay: `package.partial.json`, `tsconfig.json`,
  `eslint.config.mjs`, `.prettierrc`, `vitest.config.mts`, `vitest.setup.ts`,
  `playwright.config.ts`, `Dockerfile`, `.env.example`, `src/env.ts`, `src/lib/api/client.ts`,
  `src/shared/`, `tests/unit/`, `tests/e2e/`)
- Create: `scripts/bootstrap.mjs`

**Produces:** `node scripts/bootstrap.mjs --root <dir> [--name <project>] [--skip-install]`.

- [x] Write the backend template so `bun run check` (typecheck + lint + format + test) and
  `bun run openapi` pass without a database for the health module.
- [x] Write the frontend overlay so `bun run check` passes on top of create-next-app 16.4.2.
- [x] Write `bootstrap.mjs`: prerequisite checks, pinned create-next-app, overlay, partial
  merge, backend copy, root copy, installs, contract generation, next steps.

### Task 4: Skills

**Files:**
- Create: `.claude/skills/bootstrap-project/SKILL.md`, `.claude/skills/dev-loop/SKILL.md`,
  `.claude/skills/api-design/SKILL.md`, `.claude/skills/code-review/SKILL.md`,
  `.claude/skills/writing-plans/template.md`
- Modify: `writing-plans`, `writing-tests`, `database-schema`, `error-handling` SKILL.md files

- [x] Write each skill; `dev-loop` carries the exact dispatch prompt per stage and the
  bounded fix loop (2 rounds).

### Task 5: Agents

**Files:**
- Modify: `.claude/agents/orchestrator.md`, `frontend.md`, `backend.md`, `qa.md`
- Create: `.claude/agents/reviewer.md`
- Delete: `.claude/agents/security-reviewer.md`

- [x] Rewrite with real descriptions, models per C7, tools per role, no driver references,
  reports under `.orchestrate/report/` and `.orchestrate/review/`.

### Task 6: README, backlog, gitignore, `.orchestrate/README.md`

- [x] README around the clone checklist; backlog grammar with `tracker:` header and
  `stack:frontend` marker; `.gitignore` additions; `.orchestrate/README.md` layout.

### Task 7: Hooks and settings

**Files:**
- Modify: `.claude/hooks/enforce-agent-boundaries.mjs`, `block-destructive-bash.mjs`,
  `block-secret-file-access.mjs`, `lib/guardrail.mjs`, `.claude/settings.json`

- [x] Develop each hook in the scratchpad, run the matrix runner, `node --check`, copy in.
- [x] Lanes: frontend `frontend/`, `.orchestrate/report/frontend.md`; backend `backend/`,
  `.orchestrate/report/backend.md`; qa `.orchestrate/report/qa.md`, `frontend/tests/`,
  `backend/tests/`; orchestrator `.plan/`, `.orchestrate/ticket/`; reviewer
  `.orchestrate/review/`; general-purpose `*`.
- [x] Boundary hook also on `Bash|PowerShell`: shell write channels blocked for role sessions.
- [x] Destructive: segment-split, flag-order-independent `rm`, PowerShell `Remove-Item`,
  `git clean -f`, `git branch -D`, `git stash drop|clear`, `drizzle-kit drop|push`,
  `prisma migrate reset`, `TRUNCATE`, `docker system prune`.
- [x] Secret: `.pem`, `.key`, `id_rsa`, `id_ed25519`, `credentials`, `secrets.*`, `.npmrc`,
  `.netrc`, `~/.aws`, `~/.ssh`; env dumps (`printenv`, bare `env`, `Get-ChildItem Env:`,
  `process.env` / `Bun.env` dumps); `paths[]` arrays inspected.
- [x] Settings: PowerShell deny twins, `Read(**/*.pem)`-style denies, no
  `enabledMcpjsonServers`, matcher `Bash|PowerShell` on the boundary hook too.

### Task 8: End-to-end validation in a scratch root

- [x] Copy `templates/` and `scripts/` to a scratch root, run `bootstrap.mjs`, then in each
  package `bun run check`; backend `bun test`; `docker compose up -d db` and
  `bun run db:migrate`; frontend `bun run api:types` and diff; Playwright smoke.
- [x] Fix templates until green; record results in the Validation section.

### Task 9: Whole-branch review

- [x] Dispatch one Opus reviewer over the branch diff with the six-priority checklist;
  fix P0/P1 findings; record the rest.

Outcome (2026-10-20): 3 P0, 9 P1, 2 P2 clusters; interim rank 6/10. Every P0 and P1 was
fixed and re-validated (V07, V10–V16):

- P0 review/QA read `git diff main...HEAD`, which ignores the working tree: all stages
  now read `git diff main` after the driver runs `git add --intent-to-add .`; QA checks
  contract freshness by regenerating and comparing.
- P0 `DATABASE_URL` required with no default, so `db:migrate` and `dev` failed on a fresh
  machine: defaults to the compose `db` outside production.
- P0 wrapper spellings bypassed the destructive guard (`bunx drizzle-kit push`, `bash -lc`,
  `powershell -NoProfile -Command`, `sudo -u`, `xargs -0`, `find -exec`, subshells, `&`,
  `docker-compose`): quote-aware segment scanner, package-runner unwrapping, flag
  stripping; 154-case matrix.
- P1 role agents could `git stash|checkout|commit|push`, `rm`, `node -e`: refused.
- P1 false positives (Explore/Plan blocked on every command, `grep truncate`,
  `grep process.env`, `grep secret`, `=>`, `set -x`): SQL rules gated on SQL clients,
  env-dump rule gated on inline runtimes, secret names require a file shape, unknown
  roles get read-only shell.
- P1 Docker: `drizzle/` and `public/` could be absent, apps hidden behind a profile without
  documentation, root user: `.gitkeep`, `robots.txt`, `USER`, documented commands, both
  images built.
- P1 tests always hit the dev database: `app_test`, `describeDb`, `bun run test:db`.
- P1 api-design example did not compile (`Date` vs string): mapper added; the example is
  compiled and linted inside the scaffold (V14).
- P1 missing lint zones (route → repository/db, cross-module repository, client outside
  `server/`): added and probed.
- P1 AGENTS.md disagreed with the code (`validate`/`asyncHandler`, PostCSS, `req.user`):
  corrected.
- P1 missing seams (pagination, transactions, auth slot, per-request client, server
  action example): `lib/pagination.ts`, `Executor`, `auth.ts` + `endpoint({ auth })`,
  `createApi`, `feature/health/server/action.ts` + `RefreshButton`.
- P1 e2e proved nothing about the API: Playwright starts both servers; the smoke asserts
  the API version.
- P2 fixed: `.env*` glob, `GetEnvironmentVariables`, README liveness check, bootstrap
  `.cmd` resolution and cleanup hint, `next typegen` in typecheck, `permissions.allow`,
  body-parser 413/415, loader no longer leaks the cause, prompt nits.
- Not done: coverage floors and a `SubagentStop` report validator (out of scope); a
  committed lockfile in `templates/` (versions float within caret ranges until the first
  project `bun.lock`).

## Validation

Executed 2026-10-20 in a scratch root (`--root` outside the repository), Bun 1.4.0,
Node 24.15.0, Docker 29.7.2.

- V01 — `AGENTS.md` has no `@` lines and `.claude/rules/` does not exist — proof:
  `grep -c "^@" AGENTS.md` → 0; `ls .claude/rules` fails. **PASS**
- V02 — Bootstrap into a scratch root completes with exit 0 — proof:
  `node scripts/bootstrap.mjs --root <scratch> --name demo` → `EXIT: 0`. **PASS**
- V03 — Backend `bun run check` passes on the scaffold — proof: typecheck, lint, format
  clean; `bun test` 8 pass, 0 fail across 3 files. **PASS**
- V04 — Frontend `bun run check` passes on the scaffold, with `.next/dev/types`
  present after a `next dev` run — proof: typecheck, lint, format clean; Vitest 5 pass
  in 2 files. **PASS** (found and fixed: `noUnusedLocals` tripped on Next's generated
  types; the flag moved out of the frontend tsconfig, typescript-eslint owns unused checks)
- V05 — Contract regeneration is stable — proof: `openapi.json` sha1 `7c17c626cb50`
  before and after a second `bun run openapi`; `schema.d.ts` sha1 `7b8d29895fb8` before
  and after a second `bun run api:types`. **PASS**
- V06 — Postgres accepts the migration script — proof: `docker compose up -d db`
  healthy in ~5 s; `bun run db:migrate` exit 0 ("database reachable; no migrations
  generated yet"). **PASS**
- V07 — Hook matrix — proof: 110/110 cases as expected against the installed
  `.claude/hooks/` (fail-closed, role lanes, shell write channels, PowerShell and
  flag-order-independent destructive spellings, secret names, env dumps, `echo "rm -rf"`
  allowed, `sh -c "rm -rf"` blocked). **PASS**
- V08 — Reviewer cannot write app code — proof: matrix case
  `boundary/reviewer-writes-src` → exit 2; `reviewer.md` tools list has no Edit. **PASS**
- V09 — No stale references — proof: grep for `dev-loop.js`, `api-contract.yaml`,
  `security-reviewer`, `npm run`, `.claude/rules`, `Node.js 20`, `STATUS: DONE`,
  `TICKETS_JSON`, `stack:full` returns nothing outside this plan. **PASS**
- V10 — Layering is enforced, not described — proof: three probe files importing
  service from repository, a module from lib/, and a route from lib/ produce four
  `import-x/no-restricted-paths` errors; three frontend probes produce three
  `no-restricted-imports` errors; lint is clean once the probes are removed. **PASS**
  (found and fixed: import-x needed `createNodeResolver` with `.ts` extensions, without
  which the zones silently never fired)
- V11 — E2E smoke with axe passes against the scaffold's dev servers (backend and
  frontend both started by Playwright) and asserts the API version is rendered — proof:
  `1 passed (4.6s)`. **PASS**
- V12 — Hook matrix after the review's bypass and false-positive cases — proof: 154/154
  against the installed `.claude/hooks/`. **PASS**
- V13 — Database-backed tests run against `app_test` — proof: `bun run test:db` 13 pass
  (the `describeDb` block runs); `bun run check` 12 pass, 2 skip without Docker. **PASS**
- V14 — The api-design skill's worked module compiles, lints and passes the layering
  zones inside the scaffold — proof: `bun run check` exit 0 with `module/post/` and the
  `post` table present, then removed. **PASS**
- V15 — Both Docker images build from the scaffold — proof:
  `docker compose --profile app build` exit 0; `demo-backend` 193 MB, `demo-frontend`
  327 MB (frontend rebuilt after the Tailwind fix). **PASS**
- V16 — Production build has no CSS warnings — proof: `next build` after restoring the
  Tailwind Turbopack rule: 0 occurrences of "Parsing CSS source code failed" (there was 1
  before). **PASS**
- V17 — Frontend typecheck runs `next typegen` first and passes with and without
  `.next/` present — proof: `bun run check` exit 0, 7 unit tests. **PASS**

## Risks

- A hook regression bricks the session: mitigated by scratchpad development and `node --check` before copy; recovery documented in README.
- Pinned versions age: `AGENTS.md` names the floor, `bootstrap.mjs` pins create-next-app; a quarterly bump is a one-file change each.
- Two test runners: documented tradeoff C2.
- Express 5 on Bun exposes a compatibility edge during validation: fall back to running the backend under Node is a one-line script change, recorded if needed.
- `frontend/AGENTS.md` from create-next-app contradicts harness rules: C11, decided in Task 8.

## Rollout Order

Tasks 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9. Hooks last among the edits so that the
session stays stable while the prose is written; validation after everything is in place.

## Rollback

Nothing is committed by this plan. `git checkout chore/harness-audit-fixes` and
`git branch -D feat/fullstack-capability` restore the previous state. Scratch roots live
under the session scratchpad and are not part of the repository.
