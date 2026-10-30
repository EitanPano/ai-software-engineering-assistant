# The harness consumes the template catalog

Status: done (executed 2026-10-22 by the interactive session: Sonnet implementers per task
group, Sonnet task reviews, one Opus final review with one fix wave per repository; both
branches committed and pushed on Eitan's approval; the catalog was released as `v0.1.1`
(Eitan's choice over Open Question 4's `v0.2.0`) and the lock pins it, per ledger R19)
Owner: Eitan
Last updated: 2026-10-22
Approval: Eitan's instruction on 2026-10-22, "continue with the plan", given after the plan was
drafted on his "milestone 2 starts in the harness repo with its own plan" and after the catalog's
bun-express 2.0.0 refactor (`f4450c1`, CI green) landed on `main`. Open questions are resolved by
their recommended answers unless a ledger ruling says otherwise
(`.superpowers/sdd/007-2026-10-22-catalog-consumption/progress.md`, R1–R7).
Branch: `feat/catalog-consumption`
Base: `7ca23af` (HEAD of `feat/fullstack-capability`); re-record if the branch is cut from
`main` after PR #1 merges (Open Question 1)
Stages: harness only (no role agents; the interactive session executes it with Sonnet
implementers per step group and one Opus final review), plus one patch release of the catalog

## Goal

Milestone 2 of ADR 0001 (`fullstack-templates/docs/adr/0001-catalog-architecture.md`, D8 and
D9). After this plan the harness owns no templates: `node scripts/bootstrap.mjs --stack
next-bun-express --name <name>` reads `catalog.lock`, fetches that exact catalog version into
a cache outside the working tree (or uses a local checkout named by `--templates`), runs the
catalog's generator, and verifies the provenance file `.fullstack/catalog.yaml` it writes. The
bootstrap skill asks which stack and which flags the chosen templates declare. The root
`AGENTS.md`, the rules, the five role agents and the skills name no framework, package manager
command or file that belongs to one stack; they say "the package's `check` command" and point at
the package's own `AGENTS.md`, which the template ships. Proven by bootstrapping a scratch
project from the cache and from a local override and running every gate and the e2e suite in
both packages. Nothing a user can do today is lost: `--auth none` becomes `--flag auth=false`.

## Scope

- In, catalog side (`fullstack-templates`, one branch, released as `v0.1.1`):
  - `server/bun-express/base/AGENTS.md` and `frontend/next/base/AGENTS.md` gain the short
    sections the harness skills refer to by name: `Adding a module`, `Adding the data layer`,
    `Errors`, `Tests` (server) and `Adding a feature`, `Styling`, `Errors`, `Tests`
    (frontend). The stack-specific text leaving the harness lands here, condensed.
  - The harness-only remarks left in the two base trees (ledger item deferred to M2):
    `.env.example` "the guardrail hook refuses it" in both bases, `src/api/module/route.ts:11`
    "the harness's", `src/app/globals.css:3` pointing at `.claude/rules/ui-and-styling.md`,
    `src/app/page.tsx:12` "from the backlog", and the `.doc/architecture.md` and skill names in
    the server `AGENTS.md`.
  - `.github/workflows/release.yml`: `gh release create --notes-from-tag`, so an annotated
    tag's message becomes the release body (`--generate-notes` lists only pull requests; the
    v0.1.0 body had to be set by hand).
  - Template versions `1.0.1`, their `CHANGELOG.md` entries, `index.yaml`, the README matrix.
- In, harness side:
  - `catalog.lock` at the root: `repository`, `version`, `commit`.
  - `scripts/bootstrap.mjs` as the thin driver of D8: lock, cache or override, tools install,
    schema-version check, the generator, provenance check, next steps. `--fetch` mode for the
    skill's stack step. `templates/` deleted.
  - `.claude/skills/bootstrap-project/SKILL.md`: the stack step, flags and capabilities as
    questions, verification through the provenance file's commands, the backlog rule for a
    chosen database provider.
  - D9 applied: `AGENTS.md`, `.claude/rules/code-style.md`, `.claude/rules/ui-and-styling.md`,
    `.claude/rules/naming.md`, the five agents, `dev-loop`, `writing-plans/template.md`,
    `code-review`, `api-design`, `database`, `error-handling`, `writing-tests`,
    `.doc/architecture.md`, `.doc/product-definition.md` (AC01), `README.md`.
- Out:
  - Milestone 3: the `database/postgres` provider and overlay, the harness data-layer branch,
    catalog `v1.0.0`.
  - Updating an already generated project to a newer template version (ADR non-goal).
  - A `worker/` lane in the hooks (arrives with the first worker template).
  - Re-running the todo-app evaluation against the new bootstrap (offered separately, as after
    plan 006).
  - A CI workflow for the harness repository (it has none today).
  - The parked plan 005 minors (`createPostPerIp`, `graceToken`, the `module/route.ts:7`
    pointer): they now live in the catalog's base and are catalog work.

## Assumptions

- ADR 0001 is accepted with its v0.1.0 amendments; this plan implements D8, D9 and the
  "Harness consumes the catalog" milestone as written and reopens none of its decisions.
- Catalog `main` moved after the tag: `f4450c1` (bun-express 2.0.0, breaking) renamed
  `route.ts` to `routes.ts` (a default-exported Router: middleware constants and one line per
  endpoint), moved the rules into `controller.ts` (handlers named after their operation plus
  the exported rules that are the module's only public API), renamed `repository.ts` to
  `service.ts` (private queries, only when the module has data), made `config/routes.ts` a
  mount table and moved the OpenAPI registration list to `openapi.ts`; the ADR (D4),
  `docs/conventions.md`, the template's `AGENTS.md` and its ESLint zones followed, and CI is
  green on it. Every file this plan writes describes that shape (ledger R1); where a step
  below still says `route.ts`, `repository.ts` or "one line in `config/routes.ts`", read the
  current shape.
- Catalog `v0.1.0` is commit `e9d709c7ba5e7117b100c6eafccc1829e6f429b4`, tagged 2026-10-22;
  its `validate` and `test-generated` workflows passed on that commit. `v0.1.1` (commit
  `304a78a4bb74eed980740bc1e51ddd24a5648b68`) is this plan's own catalog release and the
  version the lock pins at the end.
- The write lanes stay keyed on `backend/` and `frontend/` (ADR Constraints; `.plan/006`);
  generated packages keep those directory names. Role-agent shell posture is unchanged.
  `.fullstack/catalog.yaml` is in no lane, so only the interactive session (the bootstrap)
  writes it. No hook changes.
- `backend/AGENTS.md` is loaded on demand when an agent works in `backend/` and read
  explicitly by the orchestrator and reviewers (`AGENTS.md` Repository layout;
  harness-upgrade notes). The same now holds for `frontend/AGENTS.md`, which the `next`
  template ships with its layer map and Next.js appends its own block to.
- The harness bootstrap stays dependency-free Node (no YAML parser). It reads one scalar from
  `index.yaml` by a line regex and otherwise delegates every catalog read to the catalog's
  tools; the model reads `index.yaml`, the chosen `stack.yaml` and its `template.yaml` files,
  and nothing else from the cache (ADR Goal 4 and Anti-goals).
- The generator writes into the project root only what D1 lists: packages, a merged
  `docker-compose.yml`, a merged `.gitignore`, `.editorconfig` when absent,
  `.fullstack/catalog.yaml`. The harness root's own files (`.claude/`, `.doc/`, `.plan/`,
  `AGENTS.md`, `README.md`, `catalog.lock`) are never touched by it.
- Windows is a first-class host: `bun` is spawned through its `.cmd` shim as today, paths come
  from `node:path` and `os.homedir()`, CRLF checkouts are fine.
- The user's rules hold: implementers run on Sonnet; the final review on Opus; no commit,
  push or tag without Eitan's yes; Conventional Commits.

## Open Questions

1. Branch base. PR #1 (`feat/fullstack-capability` → `main`) is still open. Cut
   `feat/catalog-consumption` from `main` after PR #1 merges, or stack it on the feature
   branch now? Recommended: merge PR #1 first and cut from `main`, so this plan's `Base:` is a
   `main` commit and `git diff <Base>` shows only milestone 2. If the catalog release is slow,
   start the harness steps on a branch off `7ca23af` and rebase once; `Base:` is re-recorded.
2. Lock format. `catalog.lock` holds JSON (`{ "repository", "version", "commit" }`), YAML, or
   `key=value` lines? Recommended: JSON. Node parses it without a dependency, the same way
   `bun.lock` is JSON with a `.lock` name, and a reviewer reads a three-field object.
3. Flags and capabilities. The bootstrap forwards `--flag k=v` and `--capability k=v` to the
   generator unchanged (the generator routes a shorthand to the one package that declares it
   and fails when two do), and also forwards `--answers <file>` for the package-qualified form
   D2 describes. Or the bootstrap always builds the JSON answers file? Recommended: forward
   both forms; the skill uses the shorthands for a stack with one server. Building JSON in the
   harness duplicates the generator's routing for no gain in v0.1.x.
4. Catalog version for the skill-facing sections and base cleanups. Release `v0.2.0` now
   (bun-express `2.0.0` is already on `main` unreleased; `next` goes `1.0.1`), or fold them
   into milestone 3's `v1.0.0`? Recommended: `v0.2.0`. The harness skills point at sections by
   name, so the sections must exist in the version the lock pins; a breaking template change
   on `main` deserves its own `0.x` minor (ledger R2). Decided: `v0.1.1` (Eitan, 2026-10-22);
   its release notes carry a Breaking section for bun-express `2.0.0`.
5. Where the engine specifics of the `database` skill go. Its Postgres, MongoDB and cache-store
   sections name Bun SQL, the `mongodb` driver and TypeScript file names. Move them, condensed,
   into `server/bun-express/base/AGENTS.md › Adding the data layer` now, or keep them in the
   skill until milestone 3's overlay replaces the Postgres part? Recommended: move them now;
   the skill keeps what holds for every engine (one data-model source, a repository per module,
   a `Resource` connected at boot, a separate test database, a migration or index shipped with
   the change, `testDb` as the gate) and says the engine procedure is the package's. Milestone 3
   then shortens the Postgres paragraph to "select the provider".
6. The `api-design` worked module (300 lines of TypeScript in the skill). Move the code into
   the template's `AGENTS.md`, or point at the shipped reference module `api/module/` and keep
   only the file order and the rules in `AGENTS.md › Adding a module`? Recommended: the latter.
   The reference module is the worked example and is already in every scaffold; a 300-line
   growth of a file that loads on every backend task is the wrong cost.
7. `code-style.md` and `ui-and-styling.md`. Both name a stack (Prettier, TypeScript, Tailwind,
   `sonner`, `lucide-react`). Recommended: `ui-and-styling.md` becomes the D4 frontend contract
   (tokens as CSS variables, one toast library and one icon set per package, semantic HTML,
   labelled and keyboard-reachable controls, a loading and an error state per route segment)
   and the Tailwind, `sonner` and `lucide-react` lines move to `frontend/next/base/AGENTS.md ›
   Styling`. `code-style.md` is scoped to the harness's own JavaScript (`scripts/`,
   `.claude/hooks/`) and says a generated package follows its own `AGENTS.md` and `format`
   command; the semicolon and Prettier settings stay for the harness files, which keep them
   today by hand (the harness has no formatter script).
8. Does the bootstrap verify that the provenance file names the stack's packages? That needs
   `stack.yaml` and `catalog.yaml` parsed in Node. Recommended: no. The generator exits
   non-zero on any failure and moves the staged tree into place only when every step
   succeeded; the bootstrap checks that `.fullstack/catalog.yaml` exists and is not empty, and
   the skill's verification step runs every package's `check` from that file.

## Steps

### Catalog (`fullstack-templates`, branch `fix/skill-facing-sections`, released as `v0.1.1`)

1. `server/bun-express/base/AGENTS.md`. Intro (lines 3–7): "What holds for the whole repository
   is in the root `AGENTS.md`; nothing here repeats it. This file ships with the package; an
   agent working in this directory loads it." No skill names, no `.claude/rules/`. The two
   `.doc/architecture.md` mentions in the Authentication blocks become "the project's
   architecture record". Append, after The engine seam, four sections:
   - `## Adding a module`: the file order (types in `models/<name>/`, then `schema.ts` with its
     `<operation>Request` objects and `register<Name>`, then the test, then `service.ts` (the
     queries, only when the module has data), `controller.ts` (one handler per endpoint named
     after its operation, plus the exported rules), `routes.ts` (the router), then one line in
     `config/routes.ts` and one in `openapi.ts`), the copy-and-rename recipe for `api/module/`
     and `models/module/` (`module` → `<name>`, `Module` → `<Name>`, `MODULE` → `<NAME>`),
     `validate()` and `readInput`, `requireAuth`/`requireRole` in the router and
     `requireCaller` in the handler (auth variant), the pagination helper, exported controller
     rules as the only cross-module path and a module's `service.ts` never imported from
     outside it, `bun run openapi` then `bun run check`, and the sentence "`api/module/` is the
     worked example". Taken from the harness `api-design`
     skill (Module skeleton, Crossing a module boundary, Auth and the caller) and the README's
     Adding a module; prose and file names, no code blocks beyond ten lines.
   - `## Adding the data layer`: `infra/<engine>.ts` as a `Resource` replacing `memory` in
     `dependencies`, the `services/db.ts` rewrite, one `repository.ts` per module,
     `infra/scripts/migrate.ts` and the `db:migrate` script, the test database and
     `describeDb`, the `test:db` script, the env variables; then the Postgres (Bun SQL) and
     MongoDB (`mongodb` driver) specifics from the harness `database` skill, condensed to what
     differs per engine. The cache store (Redis or Valkey) paragraph the same way.
   - `## Errors`: `AppError` in `services/utils/error.ts`, the envelope fields and where it is
     built (`middleware/error-handler.ts`), the status codes the template uses, what is logged
     (one line per request, every unexpected error with its stack, secrets redacted) and the
     required failure-path tests. From the harness `error-handling` skill › Backend and
     Logging.
   - `## Tests`: `bun test` with supertest, `tests/<name>.test.ts`, `setSystemTime`, message
     capture through `registerProvider`, `describeDb`, fixtures, "`check` never needs Docker".
     From the harness `writing-tests` skill › Backend.
2. `frontend/next/base/AGENTS.md`. Before Next's block, append `## Adding a feature`
   (`model.ts`, `server/` as the only importer of `@/lib/api/client`, `ui/`, the page that
   composes it, `loading.tsx` and `error.tsx`, `bun run api:types` after a contract change,
   `src/feature/health/` as the worked example), `## Styling` (Tailwind utilities only, tokens
   in `globals.css` through `@theme inline`, no new `.css` files, no inline styles, `sonner`,
   `lucide-react`, the same icon for the same concept), `## Errors` (`error.tsx` per segment, a
   loader returns a value for an expected failure, a server action returns `ActionResult` and
   the client leaf shows it with `sonner`), `## Tests` (Vitest with React Testing Library in
   `tests/unit/`, Playwright with axe in `tests/e2e/`, `bun run test`, `bun run test:e2e` and
   the browser install `bun x playwright install chromium`, `--with-deps` on Linux).
3. Base cleanups (Scope): `.env.example` line 2 in both bases → "never create a real env file
   in the working tree"; `src/api/module/route.ts:11` → "the shipped auth middleware";
   `src/app/globals.css:3` → "see `AGENTS.md › Styling`"; `src/app/page.tsx:12` → "Replace this
   page with the first feature." `tests/infra/dependency.test.ts`'s `harness()` helper is a
   test helper name, not a reference; it stays.
4. `.github/workflows/release.yml` publish step: `gh release create "$TAG" --verify-tag
   --notes-from-tag`.
5. Versions: `frontend/next/template.yaml` `version: 1.0.1`, `index.yaml` to match, a
   `## 1.0.1 — <date>` entry in its `CHANGELOG.md` ("agent-facing sections; harness-only
   remarks removed"); `server/bun-express` stays `2.0.0` (on `main`, unreleased) and its
   `## 2.0.0` entry gains the same line. Then `bun tools/validate.ts --readme`, `bun tools/validate.ts`,
   `bun tools/validate.ts --lockfiles`, `cd tools && bun run check`, `bun tools/test-generated.ts
   --e2e --install-browsers` (5 of 5). Pull request, both workflows green, Eitan's yes, then
   the annotated tag `v0.1.1` whose message is the release notes.

### Harness: lock and bootstrap (Sonnet implementer)

1. `catalog.lock` (JSON, Open Question 2):
   `{ "repository": "https://github.com/EitanPano/fullstack-templates", "version": "v0.1.1",
   "commit": "<the v0.1.1 commit>" }`. If the harness steps start before the catalog tag, pin
   `v0.1.0` / `e9d709c7ba5e7117b100c6eafccc1829e6f429b4` and bump in the same branch.
2. `scripts/bootstrap.mjs`, rewritten as the D8 driver. Interface:
   `node scripts/bootstrap.mjs --fetch [--templates <path>]` and
   `node scripts/bootstrap.mjs --stack <id> --name <name> [--flag k=v]… [--capability k=v]…
   [--answers <file>] [--templates <path>] [--root <dir>] [--skip-install]`.
   `--auth` dies with "use --flag auth=false". Steps, in order, each a `==>` line:
   - Prerequisites: Node ≥ 24, Bun ≥ 1.4 (through `resolveCommand`, kept), `git` on `PATH`
     (new), Docker warned when absent.
   - Lock: read and validate the three fields.
   - Catalog: `--templates <path>` or `FULLSTACK_TEMPLATES_DIR` names a local checkout (a
     warning says the lock is bypassed); otherwise the cache directory is
     `${FULLSTACK_TEMPLATES_CACHE ?? path.join(os.homedir(), '.cache', 'fullstack-templates')}/<version>`.
     When absent: `git clone --depth 1 --branch <version> --quiet <repository> <dir>`. Always:
     `git -C <dir> rev-parse HEAD` must equal the lock's `commit`, otherwise fail naming both
     and telling the user to delete that cache directory by hand (recursive deletion is refused
     to agents) and run again.
   - Tools: `bun install --frozen-lockfile` in `<catalog>/tools` (cheap when already done).
   - Schema version: the first line of `<catalog>/index.yaml` matching
     `^schemaVersion:\s*(\d+)\s*$` must be ≤ `SUPPORTED_SCHEMA_VERSION` (1); otherwise fail
     with "bump the harness".
   - `--fetch` stops here and prints the catalog path on one line and the full `index.yaml`
     after it, so the skill lists the stacks from the output without browsing the cache.
   - Second-run guard: `<root>/.fullstack/catalog.yaml` already exists → fail.
   - Generate: `bun tools/generate.ts --stack <id> --out <absolute root> --name <name>
     [--flag …] [--capability …] [--answers <absolute file>] [--catalog-version <version>,
     only when the catalog came from the cache] [--skip-post-generate when --skip-install]`,
     cwd `<catalog>`, stdio inherited (the generator's `==>` lines and its `Done. Next:` per
     package `check` lines reach the user).
   - Provenance: `<root>/.fullstack/catalog.yaml` exists and is not empty.
   - Next steps printed by the harness: read `.fullstack/catalog.yaml` for each package's
     commands, run every `check` and the `testE2e` the frontend declares, fill `.doc/`, add the
     first backlog line, then the commit gate on `chore/bootstrap`.
   Dropped from today's script: `create-next-app`, the overlay copy, `templates/root`,
   `__PROJECT_NAME__` replacement, the auth marker pass, `AUTH_ONLY_PATHS`, dependency pruning,
   `toProjectName` (the generator names the project). Kept: `resolveCommand`, `run`, `step`,
   `die`, `fail`, the argument parser's shape. `--root` stays for scratch validation;
   `--skip-install` maps to the generator's `--skip-post-generate`.
3. `git rm -r templates`. Nothing replaces it; the catalog is the source.
4. `.claude/settings.json`: no change; `Bash(node scripts/bootstrap.mjs*)` already covers the
   driver, and the clone and install happen inside that process.

### Harness: bootstrap skill (same implementer)

5. `.claude/skills/bootstrap-project/SKILL.md`:
   - §1 keeps the product forms. The Auth answer maps `none` to `--flag auth=false` (the
     replacement text for `.doc/architecture.md` Auth stays). The Data store answer changes:
     when the chosen server template's `capabilities.database.providers` lists providers, ask
     which and pass `--capability database=<id>`; otherwise the answer is "decide later" and
     the data-layer backlog line is written (v0.1.x lists none, so the skill says so).
   - New §2 "Choose the stack": run `node scripts/bootstrap.mjs --fetch`; present the stacks
     from the printed `index.yaml`; for the chosen stack, Read `<catalog>/stacks/<id>/stack.yaml`
     and each listed package's `template.yaml`; ask each flag (its `summary`, its `default`) and
     each capability with providers. These are the only files the skill reads under the cache;
     no Glob, Grep or Explore agent there.
   - §3 scaffold: the new command; what it creates (the packages the stack lists, a merged
     `docker-compose.yml` and `.gitignore`, `.editorconfig` when absent, `.fullstack/catalog.yaml`).
   - §4 verify: for each package in `.fullstack/catalog.yaml`, its `check`; for a package with
     `testE2e`, the browser install its `AGENTS.md › Tests` names, then `testE2e`; start each
     `dev` and open the frontend's `http.health` path; it must reach the server (for
     `frontend/next`, the API version pill). A failing gate on a fresh scaffold is a catalog
     bug: say so and name the template and version from the provenance file.
   - §5 backlog lines: the data-layer line only when no database provider was chosen.
   - §6 commit gate: `chore(bootstrap): scaffold <name>` includes `.fullstack/catalog.yaml`.
   - "Never does": browse the cache; edit `scripts/`, `.claude/`, `catalog.lock`.

### Harness: stack-agnostic files, D9 (second Sonnet implementer; two groups)

6. `AGENTS.md`:
   - Repository layout: drop both `templates/` rows; add `catalog.lock` ("the pinned catalog
     version; bumping it is a reviewed change") and `.fullstack/catalog.yaml` ("written by the
     bootstrap: templates, versions, flags, commands and ports per package; committed"); the
     `frontend/` and `backend/` rows become "generated packages, one per stack entry; each
     carries its own `AGENTS.md`".
   - Stack: "Runtime and tooling" keeps Bun 1.4+, Node 24+, Docker Compose and adds git, with
     the reason (the catalog's tools run on Bun; the bootstrap clones the catalog). The two
     framework blocks are replaced by one paragraph: the stack is chosen at the bootstrap from
     the catalog `catalog.lock` pins; each package's layer map, packages and conventions are in
     its `AGENTS.md`; its commands and ports are in `.fullstack/catalog.yaml`. The Commands
     table becomes the command vocabulary (`install`, `dev`, `check`, `typecheck`, `lint`,
     `format`, `test`, `testDb`, `testE2e`, `contract`, `migrate`) with one line each on what
     the harness expects (`check`: every gate, no Docker, exit 0 means done; `contract`:
     produce on a server, consume on a frontend), resolved per package from the provenance
     file. The compose line stays. "Never run `create-next-app`, `bun init`" becomes "never
     run a scaffolder inside an existing package".
   - Architecture: the two-packages-and-a-contract framing stays; the `frontend/src/` and
     `backend/src/` bullets become D4's short forms (server: the two entry files, the
     directories, the request flow, controllers as the only cross-module path; frontend: a
     routing-only app directory, `feature/<name>/` with `ui/`, a data layer and `model`,
     product-agnostic `shared/`, the generated client in `lib/api/`, import direction
     `app → feature → shared, lib`), each ending with "the file names are in the package's
     `AGENTS.md`". Authentication: "a server template ships authentication behind its `auth`
     flag; `--flag auth=false` scaffolds without it (Auth: none); where its rules live is in
     the package's `AGENTS.md`". Contract and data: the zod sentence becomes "the server's
     request schemas are the single source of truth: they validate requests, type responses
     and produce the OpenAPI document; the frontend regenerates its types with its `contract`
     command in the same task and never hand-writes an API type"; configuration "read once in
     each package's env module".
   - Rules index: the `ui-and-styling.md` line per Open Question 7.
   - Definition of done: 1 "the `check` command of every package the task touched exits 0";
     5 "a schema or endpoint change ran the server's and the frontend's `contract` commands and
     committed both results; a data-model change ships what the `database` skill requires and
     passes `testDb`"; 6 "UI changes meet the frontend package's `AGENTS.md › Styling` and its
     accessibility scan passes".
   - Skills table: `bootstrap-project` "a fresh clone has no `.fullstack/catalog.yaml` yet".
7. `.claude/rules/code-style.md`, `.claude/rules/ui-and-styling.md` per Open Question 7;
   `.claude/rules/naming.md:14` "an entity's types".
8. Agents. `backend.md`: description names the server package, not the framework; steps 2–6
   point at `backend/AGENTS.md › Adding a module`, `› Errors`, `› Tests`, the package's
   `contract`, `check`, `testDb` (when present) and `migrate` commands; report lines `Tests:
   <N passed, 0 failed> (test) · (testDb) or n/a`, `Contract: regenerated <yes|no>`.
   `frontend.md`: description names the frontend package; step 2 "the package's `contract`
   command when the backend stage ran"; step 4 points at `frontend/AGENTS.md › Adding a
   feature`; the Rules block's Tailwind, `sonner`, `lucide-react` line becomes "per
   `frontend/AGENTS.md › Styling`"; "Never run a scaffolder: the app exists". `qa.md`: the gates
   block lists the commands by vocabulary, read from `.fullstack/catalog.yaml` (`check` per
   package, `testDb` and `testE2e` where present); contract freshness runs both `contract`
   commands and confirms the committed contract files each `AGENTS.md` names did not change.
   `reviewer.md`: read-only commands by vocabulary (`typecheck`, `lint`, `test`; never
   `format`); reads `frontend/AGENTS.md` when the diff touches `frontend/`. `orchestrator.md`:
   reads both package `AGENTS.md` files; "a plan that puts logic in the routing layer, a fetch
   in a UI component or a query in a route adapter is wrong".
9. Skills. `dev-loop`: preconditions read "`.fullstack/catalog.yaml` exists"; every command by
   vocabulary; deletions re-run that package's `check`. `writing-plans/template.md`: the
   Backend and Frontend step lists keep the layer names and drop the commands and `zod`, each
   ending "per the package's `AGENTS.md`"; `contract` commands. `code-review`: its two
   `bun run` lines. `api-design`: keeps Conventions, the neutral parts of Crossing a module
   boundary and Auth and the caller, and Contract flow; Module skeleton becomes a pointer per
   Open Question 6. `database`: per Open Question 5; Choosing (bootstrap) describes the
   provider question. `error-handling`: Backend names "the package's error type and envelope
   builder (`AGENTS.md › Errors`)" and keeps the envelope, the status table, logging and retry;
   Frontend "the route error boundary, the action result type and the toast library the
   package's `AGENTS.md` names". `writing-tests`: Suites in this repository becomes "per package
   `AGENTS.md › Tests`"; the rest is already neutral.
10. `.doc/architecture.md`: lines 3–4, 21, 25, 47, 58–59, 78, 95, 132 lose Next.js, Express,
    zod, `bun run` and file names; a `Stack` line is added to the components table for the
    bootstrap skill to fill from `.fullstack/catalog.yaml` (stack id, template and version per
    package). `.doc/product-definition.md:50` AC01: "every package's `check` command is green".
11. `README.md`: what you get (a stack from the catalog; `v0.1.x` ships `next-bun-express`,
    described in two lines with the catalog named as the source); Prerequisites add git and the
    cache location; Clone checklist step 3 mentions the stack question; Repository map (drop the
    `templates/` rows; add `catalog.lock` and `.fullstack/catalog.yaml`); Adding a module → one
    line to `backend/AGENTS.md › Adding a module`; Updating the harness → the lock bump
    procedure, `--templates` and `FULLSTACK_TEMPLATES_DIR`, `FULLSTACK_TEMPLATES_CACHE`; the
    `@auth` markers paragraph goes.

### Final review (Opus) and close

12. One Opus review of `git diff <Base>` against this plan, ADR D8 and D9 and the anti-goal
    "no root file names a framework or a package manager command"; one fix wave at most; then
    the Validation list is run again where a fix touched it. The plan is set to `Status: done`
    with the evidence, and the catalog memory and harness notes are updated.

## Validation

- V01 — a fresh cache bootstrap works end to end — proof: with no
  `~/.cache/fullstack-templates/`, `node scripts/bootstrap.mjs --stack next-bun-express --name
  demo --root <scratch>` exits 0, the cache holds `<version>/` at the lock's commit,
  `<scratch>/.fullstack/catalog.yaml` exists, and in `<scratch>` every package's `check` and the
  frontend's `testE2e` exit 0
- V02 — a local override bypasses the lock with a warning — proof: the same command with
  `--templates C:/Dev/Playground/AI/fullstack-templates` into a second scratch root prints the
  bypass warning, exits 0, and both `check` commands exit 0; `.fullstack/catalog.yaml` records
  the checkout's identity
- V03 — `--flag auth=false` scaffolds without authentication — proof: a third scratch root
  passes both `check` commands; `ls backend/src/api` has no `auth` or `user`;
  `grep -ri -E 'jwt|requireAuth|requireRole|session|cookie-parser' backend/src` is empty (the
  logger's redaction pattern legitimately names `otp` and `cookie`, so those words are not
  the test; ledger R15)
- V04 — a moved tag is refused — proof: edit the `commit` in a scratch copy of `catalog.lock`
  (or point `FULLSTACK_TEMPLATES_CACHE` at a cache whose `HEAD` differs) and run: exit 1, the
  message names both commits and the cache directory, nothing is generated
- V05 — a newer catalog schema is refused — proof: a scratch copy of the catalog whose
  `index.yaml` says `schemaVersion: 2`, passed with `--templates`: exit 1 before generation
- V06 — the bootstrap refuses to run twice — proof: run V01's command again in the same root:
  exit 1 naming `.fullstack/catalog.yaml`; `git status --short` in the scratch root is unchanged
- V07 — `--fetch` lists the stacks without browsing — proof: `node scripts/bootstrap.mjs
  --fetch` prints the catalog path and `index.yaml`, exits 0, generates nothing
- V08 — `--auth` is gone — proof: `node scripts/bootstrap.mjs --auth none --stack x --name y`
  exits 1 with the `--flag auth=false` hint
- V09 — no harness root file names a stack — proof: `grep -rni -E 'express|next\.js|zod|tailwind|
  vitest|playwright|supertest|sonner|lucide|openapi\.json|schema\.d\.ts|bun run|bun test|
  create-next-app|templates/' AGENTS.md .claude/rules .claude/agents .claude/skills .doc` returns
  only the `cutting-a-release` and `bootstrap-project` lines that name Bun as a prerequisite
  and the README's two-line description of the shipped stack
- V10 — `templates/` is gone and nothing references it — proof: `test ! -d templates`;
  `git grep -n 'templates/' -- ':!.plan'` is empty
- V11 — hooks and lanes are untouched — proof: `git diff <Base> --stat -- .claude/hooks
  .claude/settings.json` is empty
- V12 — the catalog release holds the sections the skills point at — proof: on the `v0.1.1`
  commit, `grep -n '^## ' server/bun-express/base/AGENTS.md frontend/next/base/AGENTS.md` lists
  `Adding a module`, `Adding the data layer`, `Errors`, `Tests` and `Adding a feature`,
  `Styling`, `Errors`, `Tests`; the harness-only grep of Scope returns nothing in either base;
  the `validate`, `test-generated` and `release` workflows are green on the tag
- V13 — the lock pins the released commit — proof: `catalog.lock` `commit` equals
  `git rev-parse v0.1.1^{}` in the catalog, and V01's cache directory `HEAD` equals it
- V14 — the generator left the harness root's own files alone — proof: in V01's scratch root
  (a copy of the harness root files), `git status --short` shows only the generated packages,
  `docker-compose.yml`, `.gitignore` (appended under the marker header), `.editorconfig` and
  `.fullstack/`

Results (2026-10-22): V01 PASS at `v0.1.0` (the cache path; both `check` commands and e2e
green); V02 PASS against the local checkout on `fix/skill-facing-sections` (2.0.0 module files,
the eight sections present, checks and e2e green); V03 PASS with the amended proof (R15);
V04–V08 PASS; V09–V11 PASS (controller greps, hooks untouched); V12 PASS (sections and greps
locally; `validate` and `test-generated` green on catalog PR #1, `release` green on the
`v0.1.1` tag); V13 PASS for `v0.1.0`; V14 PASS as written (R21). After the bump to `v0.1.1`,
V01 and V13 PASS again from an empty cache: the cache `HEAD`, the lock and `v0.1.1^{}` are all
`304a78a`; backend `check` 353 tests, frontend `check` 7 tests, `testE2e` 1 test with the
accessibility scan.
Evidence: `.superpowers/sdd/007-2026-10-22-catalog-consumption/` (`task-H1-report.md`,
`task-H6-report.md`, `H-final-fix-report.md`, `progress.md`).

## Risks

- The template `AGENTS.md` files grow with the skill-facing sections and load on every task in
  that package — the sections are prose with file names, the worked code stays in the shipped
  reference module (Open Question 6); the four server sections take at most 130 lines together
  and the final review checks the server file stays under 480 lines (ledger R6).
- Two repositories to keep in step: the harness skills name sections that only `v0.1.1` has —
  the lock pins `v0.1.1`; a bootstrap from `v0.1.0` is refused by the commit check, not by a
  missing heading.
- The generator appends to the harness root's `.gitignore` and creates `docker-compose.yml`
  there — expected per D1 and D5; V14 shows exactly which root files change.
- A shallow clone of a tag, a `.cmd` shim for `bun`, a home directory with spaces, a CRLF
  checkout — V01 and V02 run on Windows (the author's host); the clone uses `--branch <tag>`,
  paths come from `node:path` and `os.homedir()`.
- The frozen install in the cache's `tools/` needs the network once — the failure message says
  so; a local override (`--templates`) works offline.
- `frontend/AGENTS.md` is also written to by `next dev` — the template commits Next's block, so
  a `dev` run changes nothing (catalog Task 15 verified); the frontend agent's instruction to
  read it stays true.
- The `database` skill loses its engine procedures from the harness — they live in the server
  template's `AGENTS.md` until milestone 3 replaces the Postgres part with the overlay; a
  product that chooses MongoDB still finds the procedure in `backend/AGENTS.md`.
- A project scaffolded before this plan has no `.fullstack/catalog.yaml` and a
  `backend/AGENTS.md` without the sections the new agents point at, so the new harness files do
  not fit it — such a project stays on the pre-catalog harness (the last commit before this
  change); README › Updating the harness says so, and a lock bump changes only what the next
  bootstrap generates (final review, Important 5).

## Rollout Order

catalog branch (sections, cleanups, release workflow, versions) → catalog PR and CI → tag
`v0.1.1` (Eitan) → harness lock and bootstrap → `templates/` removed → bootstrap skill → D9
files (AGENTS.md and rules, then agents and skills, then `.doc/` and README) → V01–V14 in scratch
roots → Opus review and fix wave → Eitan's review, then PR to `main`

## Rollback

Every harness change is on `feat/catalog-consumption`; reverting the branch restores
`templates/` and today's bootstrap, since both stay in git history. `main` keeps bootstrapping
from its own templates until the PR merges. A project scaffolded before this plan keeps its
packages and its own `backend/AGENTS.md` either way and stays on the pre-catalog harness. The
catalog release cannot be un-tagged; a wrong `v0.1.1` is followed by `v0.1.2` and a lock bump.
No data, migration or product code is involved.
