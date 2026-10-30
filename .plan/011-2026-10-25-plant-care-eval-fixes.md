# Harness fixes from the plant-care eval, the UI baseline, catalog v1.3.0

Status: done
Status set by the session on Eitan's delegation ("do your recommendations, GO", 2026-10-25).
Owner: Eitan
Last updated: 2026-10-25
Approval: Eitan, 2026-10-25, "do your recommendations, GO". OQ1–OQ5 were answered by him the same
day, each with the recommended option; OQ6–OQ9 take their recommended answers under the same
instruction. G1 (ADR 0004) is covered by it, since the ADR records decisions D6 and D7 as
approved here. Rulings made while executing are in the ledger
(`.superpowers/sdd/011-2026-10-25-plant-care-eval-fixes/progress.md`, git-ignored).
Input: `.superpowers/eval/2026-10-25-plant-care-handoff.md` (findings F1–F9, checked against the
transcripts; the eval folder is evidence and is not edited).
Branch: harness `fix/plant-care-eval`, catalog `feat/ui-baseline`, both cut from `dev` after G0.
Hook changes are made in a git worktree of the harness branch (`.claude/worktrees/hooks`,
git-ignored), never in the live `.claude/hooks/`.
Base: harness f634669 (`main`), catalog f0e73b7 (`main`, = `v1.2.0`). `dev` is behind `main` in
both (harness 7ac1a90, catalog 73bc671) and `main` contains `dev`, so G0 is a fast-forward.
Stages: harness and catalog only. No role agents run. The interactive session drives Sonnet
implementers per task with a Sonnet review per task, one Opus final review per repository, and
the two proofs (P1, P2). It ends in one pull request per repository into `dev`; the
`catalog.lock` bump is its own PR after Eitan tags `v1.3.0`.

## Goal

The first dev-loop run on the catalog-era stack (plant-care, 2026-10-25) built a working feature
but showed the harness handing a product its own history, a 522-line plan for one backlog line,
an unverified "tests first", reviewers re-running gates, three hook false positives, a
bootstrap verify that clashes on the database port, and a frontend with no visual baseline.
After this plan: a product bootstrapped from the harness starts with an empty plan history, an
auth-correct glossary, a filled design brief and a generated app shell with token scales and a
phone-viewport e2e project; a product plan is sized for one backlog line and the loop checks the
size; the red run is evidence in the stage report and QA checks it; reviewers read reports
instead of re-running gates; the three false positives pass and the write channels still block;
the bootstrap verify needs no hand intervention; and the templates say what e2e needs. Two runs
prove it: a second loop on the eval app and a fresh bootstrap after the lock bump.

## Scope

**In, harness side** (this repository):

- `scripts/bootstrap.mjs` and a new `scripts/history.mjs` with `scripts/history.test.mjs`:
  clear the harness's own history after a successful generation (F3, OQ1) and resolve the
  `auth` markers in `.doc/`.
- `.doc/architecture.md` (stale Change Log entries removed; `auth` markers on the Auth body),
  `.doc/glossary.md` (`auth` markers on the four auth rows), `.doc/product-definition.md`
  (a `Design` section; the "Ready to plan" owner).
- `.claude/skills/writing-plans/SKILL.md` and `template.md`, `.claude/agents/orchestrator.md`,
  `.claude/skills/dev-loop/SKILL.md`: the sizing rule and the driver's size check (F1, OQ4).
- `.claude/agents/backend.md`, `frontend.md`, `qa.md`, `.claude/skills/writing-tests/SKILL.md`,
  `AGENTS.md › Definition of done`: the `Tests first:` evidence (F2, OQ2).
- `.claude/agents/reviewer.md`, `.claude/skills/code-review/SKILL.md`, `dev-loop` section 4:
  reports are the gate evidence (F7).
- `.claude/hooks/enforce-agent-boundaries.mjs`, `.claude/hooks/lib/guardrail.mjs` and the test
  suite: heredoc bodies leave the redirect scan, `git hash-object` reads (F5a, F5b). F5(c) stays.
- `.claude/rules/ui-and-styling.md`, `frontend.md`, `qa.md`, `bootstrap-project` section 1,
  `writing-plans/template.md`: the UX rules, the design brief and QA's UX pass (F6, OQ3).
- `.claude/skills/bootstrap-project/SKILL.md` sections 1, 4, 5 and 6: the brief, the database
  stop before the app check, the dev-server stop recipe, the checklist owner, the Change Log
  position, what the scaffold removes (F4, F9b, F9c).
- `.gitattributes` (new), `README.md` (headless note, clone checklist), `AGENTS.md` (Repository
  layout row for `.plan/`, Definition of done). (F9a, F9d)
- This plan. Rulings and deferred minors go to
  `.superpowers/sdd/011-2026-10-25-plant-care-eval-fixes/progress.md` (git-ignored).

**In, catalog side** (`C:/Dev/Playground/AI/fullstack-templates`, named here; work there starts
only after this plan is approved):

- ADR 0004 `docs/adr/0004-ui-baseline.md` and `docs/conventions.md`: the shell, the token
  scales, the phone-viewport project and the e2e data rule, written once for every frontend.
- `frontend/react` 1.1.0 and `frontend/next` 1.2.0: `shared/ui/app-shell.tsx` composed by
  `app/layout.tsx`, `shared/ui/button.tsx`, the scales in `globals.css`, a `phone` Playwright
  project with screenshots, `tests/e2e/shell.spec.ts`, `tests/unit/app-shell.test.tsx`,
  `AGENTS.md › Styling` and `› Tests` (e2e needs the database; the data rule) (F6, F8).
- `server/python-fastapi` 1.1.1: `middleware/rate_limit.py` keys IPv6 by its /64 and its test;
  `AGENTS.md › Packages and conventions` gains the Windows stop note for the reload child (F4b,
  the eval's security P2).
- `server/bun-express` 2.3.1: the same `by_ip` rule in `middleware/rate-limit.ts` and its test.
- `index.yaml`, the README matrix, the four `CHANGELOG.md` files; CI unchanged (the phone
  project runs inside the existing e2e cases).
- After the tag: the harness `catalog.lock` bump to `v1.3.0` (H5).

**Out:**

- A component library, theming beyond tokens, dark mode beyond what the templates ship.
- A sixth (UX) reviewer; QA's UX pass covers it (OQ3).
- A separate e2e database (`app_e2e`); see Open Question 6.
- The eval app's product P2s (client control-character rule, dead-end cursor page, index
  condition); they are the eval app's, not the harness's.
- The headless `-p` background limit and the untrusted-workspace permission fallback: Claude
  Code behaviour, not harness behaviour. The README names the variable the driver used (F9d).
- The frontend agent's hook probe (`sed -i` on `/dev/null`): observation only.
- Vue and Angular templates, MongoDB, cache, workers (ADR 0001 delivery order).

## Assumptions

- The handoff's findings hold as checked against the transcripts; F7 uses its correction
  (3 of 7 reviewer runs re-ran gates, not all).
- The generator never writes `.plan/` or `.doc/` (plan 007 Assumptions), so F3 is harness
  work in `scripts/` and the catalog's generator is unchanged.
- The write lanes are unchanged (plan 006). Phone screenshots are written by Playwright, code
  the frontend agent runs, into `frontend/test-results/` (git-ignored), so no lane changes.
- Hook suite baseline on `main` f634669: 1188 passed, 0 failed (run 2026-10-25). The redirect
  false positive comes from `shellWriteChannel` scanning `withoutQuotes(line)` over the whole
  command, heredoc bodies included; `hash-object` is simply absent from `GIT_READ`.
- This checkout is CRLF in the working tree (`core.autocrlf=true`) with an LF index; the eval
  clone was the same, which is F9(a).
- Catalog facts (read-only, 2026-10-25): templates react 1.0.0, next 1.1.1, bun-express 2.3.0,
  python-fastapi 1.1.0; ADRs 0001–0003; the react base has `src/app/{layout,routes,error,
  not-found}.tsx`, `globals.css`, `tests/e2e/smoke.spec.ts`; the rate-limit middleware files
  are `rate-limit.ts` and `rate_limit.py`.
- The SPA contract of ADR 0003 (M5-1) stands: `app/` is routing only, so the shell is a
  `shared/ui` component that `app/layout.tsx` composes; `feature/` never imports it.
- The eval clone `C:/Dev/Playground/AI/test-plant-care-eval` is evidence: P1 adds commits on a
  new branch there and edits nothing under its `.orchestrate/` from the first run.
- The user's rules hold: Sonnet implementers and task reviews, Opus final reviews; Conventional
  Commits; no commit, push, PR, merge or tag without Eitan's yes at execution time; hook changes
  only in a worktree, with the suite run before and after.

## Open Questions

1. **OQ1 (F3).** How does a product stop inheriting the harness's plans, change-log entries and
   auth glossary rows? Answered 2026-10-25 with the recommendation. Recommended:
   `bootstrap.mjs` clears it after a successful generation (D1).
2. **OQ2 (F2).** Enforce "tests first" through evidence, or drop the claim? Answered 2026-10-25
   with the recommendation. Recommended: a `Tests first:` line in the stage report, checked by
   QA against the diff (D3).
3. **OQ3 (F6).** How far does UX go? Answered 2026-10-25 with the recommendation, the full
   option. Recommended: harness rules and a design brief, plus the catalog minor v1.3.0 with
   the shell, the scales and the phone project, bundling F4(b), F8 and the IPv6 key (D6, D7).
4. **OQ4 (F1).** The sizing rule? Answered 2026-10-25 with the recommendation. Recommended: one
   template with a scope rule and caps, checked by the driver (D2).
5. **OQ5.** The proof? Answered 2026-10-25 with the recommendation. Recommended: a second loop
   on the eval app (`stack:frontend`, a branch carrying an earlier task) plus a fresh
   bootstrap-only run after the lock bump (P1, P2).
6. **Does e2e get its own database?** Today the e2e server uses the development database and
   its rows stay. Recommended: not in this plan. `AGENTS.md › Tests` states the dependency and
   the data rule (unique names per run; delete through the API once the product has a delete
   endpoint; never the development database's contents as a precondition). An `app_e2e`
   database is a catalog follow-up if the rule proves insufficient in P1.
7. **A new ADR or an amendment to 0003?** Recommended: ADR 0004, because the UI baseline is a
   decision set of its own that Vue and Angular will implement; 0003 and `conventions.md` get a
   pointer.
8. **Touch-target size?** WCAG 2.2 AA (2.5.8) asks 24 px; AAA (2.5.5), Apple and Material ask
   44 px. Recommended: 44 px for buttons, links in the nav and form controls, asserted by the
   shell spec on the phone project; a product lowers it by plan.
9. **How does QA see a route on a phone?** Recommended: the `phone` Playwright project runs with
   `screenshot: 'on'`, so every e2e test leaves `test-results/<test>-phone/test-finished-1.png`
   at no agent cost; QA reads the images for the task's routes against the Design section. No
   lane change: Playwright writes them, not the agent's tools.

## Steps

No product API changes; there is no Contract subsection.

### Gates

- **G0 (Eitan, or the session on his yes):** fast-forward `dev` to `main` in both repositories;
  cut `fix/plant-care-eval` (harness) and `feat/ui-baseline` (catalog); add the hooks worktree
  `git worktree add .claude/worktrees/hooks fix/plant-care-eval`.
- **G1 (Eitan):** approve ADR 0004 before C2–C4. H1–H4 do not depend on it.

### Decisions (implementers do not reopen them)

- **D1 History clearing** (`scripts/history.mjs`, `clearHarnessHistory(root, { auth })`).
  - Runs as the step `Clearing the harness's own history` after `Verifying
    .fullstack/catalog.yaml`, so a failed generation leaves the clone intact; never on
    `--fetch`; a no-op when `root` has no `.plan/` or `.doc/` (a `--root` scratch).
  - Deletes every `.plan/<three digits>-*.md` except `000-backlog.md`. At that point only
    harness history can exist: the fresh-project check already passed. Each removed path is
    printed.
  - `.doc/glossary.md` and `.doc/architecture.md` carry `auth` markers: a line ending in
    `<!-- auth -->` is dropped when `auth` is false and loses the marker when true; the block
    between `<!-- auth-start -->` and `<!-- auth-end -->` likewise; a `<!-- noauth: text -->`
    line becomes `text` when false and is dropped when true. The glossary's `session`,
    `caller`, `OTP` and `target` rows carry the inline marker in their last cell (valid GFM, the
    table stays intact); the architecture Auth body is the fenced block, and the `none` wording
    from `bootstrap-project` section 1 moves into `noauth` lines. No marker survives in either
    variant. `auth` comes from `--flag auth=false`, default true.
  - EOL is detected per file (first line break) and preserved. Plain Node, no dependency, ESM,
    named exports, tested with LF and CRLF fixtures (`scripts/history.test.mjs`, `node --test`).
  - The harness's `.doc/architecture.md` Change Log loses its three dated entries (plans 004 and
    005, bun-express 2.0.0): template history that lives in the catalog's conventions and ADRs.
    The FILL line for the initial entry stays and is the only entry.
- **D2 Plan sizing** (`writing-plans` › a new `Sizing a product task` section).
  - The scope is the backlog line and the acceptance criteria it names. Pagination, rate limits
    and other hardening not named by an AC go under `Out` as a proposed backlog line (`- [ ] …`),
    which the driver adds to the backlog on the user's yes.
  - Caps: at most 12 Validation items and 4 Open Questions of at most 5 lines each; `Steps`
    name files, one line each, no code beyond the Contract table; rationale is one line under
    Assumptions. Target about 150 lines; above 250 the orchestrator plans the first half and
    proposes the rest as backlog lines, and says so on its last line.
  - Exempt: a plan whose `Stages:` names no role agent (harness milestones).
  - `template.md` carries the caps as one-line comments at `Open Questions` and `Validation`;
    `orchestrator.md` step 4 names them; `dev-loop` section 2 counts `^- V` lines, `^\d+\.`
    lines under Open Questions and total lines before showing the plan, re-dispatches once with
    "within the caps or split", and on a second overrun shows the counts to the user.
- **D3 Tests-first evidence.**
  - Report line, backend and frontend: `Tests first: <test command> → <N failed, M passed>
    before implementation; failing: <test names>` (and the `testDb` command's line where
    store-backed tests were added). The agents' step 3 says to keep that summary.
  - `qa.md` step 4 (diff hygiene) checks the line exists, that every named test is in
    `git diff <Base>`, and that at least one failing test covers each new behaviour; a missing
    or inconsistent line is a P1 finding owned by the stage.
  - `writing-tests › Order of work`: the red run's summary goes in the report; "after the fact"
    stays acceptable only with the reason. `AGENTS.md › Definition of done` item 2 ends with
    "and the stage report shows the red run (`Tests first:`)".
- **D4 Reviewers read reports.** `reviewer.md` and the `code-review` skill: the implementer's
  `Tests:` and `Gates:` lines and QA's report are the gate evidence; a reviewer runs at most the
  one test file that confirms a finding, never a package gate, never `testDb` (it writes
  `app_test`), never a dev server. `dev-loop` section 4 repeats the rule in one line.
- **D5 Hooks** (worktree only; suite before and after).
  - (a) `guardrail.mjs` gains `withoutHeredocBodies(command)`: for each `<<[-]?` operator with
    an optionally quoted word, the text from the end of that line to the terminator line is
    removed, the operator kept. `enforce-agent-boundaries.mjs` applies it before the `REDIRECT`
    scan, but only when no token of the owning segment (as written, and in every peeled view)
    is a shell, `eval`, `source`, `xargs` or an interpreter; otherwise the body stays scanned,
    because a shell or interpreter runs it. The destructive and secret hooks keep scanning
    bodies (F5c is deliberate).
  - (b) `GIT_READ` gains `hash-object`; `-w` anywhere in its arguments refuses as
    `git hash-object -w`.
  - Tests: `.claude/hooks/test/heredoc.test.mjs`. Passes for every role: `docker compose exec -T
    database psql -U app -d app <<'SQL' 2>/dev/null` with `>` and `<>` in the body; `psql <<EOF`
    with `select 1 > 0`; `cat <<'EOF'` with `a > b`; `git hash-object backend/src/x.py`;
    `git hash-object --stdin`. Blocks: `bash <<'EOF'` and `sh <<EOF` with a redirect in the body;
    `docker compose exec backend sh <<'EOF'` likewise; `eval "$(cat <<'EOF' … )"`; `cat <<'EOF' >
    backend/f` (the redirect is on the operator line); `python - <<'EOF'` (unchanged refusal);
    `git hash-object -w f`. The existing 1188 cases stay.
- **D6 UI baseline.**
  - Harness, `ui-and-styling.md`: mobile-first (unprefixed utilities are the phone layout;
    `sm`, `md`, `lg` widen it); four token scales as CSS variables (colour, spacing on a 4 px
    base, type, radius) and no literal in a component; 44 px touch targets for buttons, nav
    links and form controls; the shell owns `<header>`, `<nav aria-label>`, the one `<main>`
    with a skip link, and `<footer>`; the product definition's `Design` section is the brief
    and a `figma:` marker overrides it per task; the phone-viewport e2e project with axe passes.
  - `.doc/product-definition.md › Design` (FILL markers): tone in two or three adjectives;
    reference apps; colour seed (one primary hue, a neutral); type (system stack or a named
    font); density; primary viewport (phone or desktop first) and the breakpoints that matter;
    dark mode (no, system, toggle). `bootstrap-project` section 1 walks it; the orchestrator
    reads it for a frontend stage; `frontend.md` step 1 reads it; `template.md › Frontend` adds
    "the shell slot the feature fills (nav entry) and its phone layout".
  - QA (`qa.md`, a new step 6 "UX pass"): for each route the task adds or changes, read the
    `phone` project's screenshot (OQ9) and record PASS or FAIL against the Design section and
    the rules (shell present, no horizontal overflow, controls readable), with the file path as
    evidence; `testE2e` already covers axe and the shell spec on the phone project.
  - Catalog, both frontends (ADR 0004): `shared/ui/app-shell.tsx` (header with the project
    name, `<nav aria-label="Primary">` from `app/nav.ts`, skip link, `<main id="main">`,
    footer), composed by `app/layout.tsx`; `shared/ui/button.tsx` (44 px target, focus ring
    from tokens), used by the health feature's refresh button; `globals.css`: `--space-1…8`
    (4, 8, 12, 16, 24, 32, 48, 64 px), `--text-sm…2xl` with line heights, `--radius-sm/md/lg`,
    `--shadow-1/2`, exposed through `@theme inline`; `playwright.config.ts`: a `phone` project
    (`devices['Pixel 7']`, `screenshot: 'on'`) beside `chromium`; `tests/e2e/shell.spec.ts`:
    landmarks `banner`, `navigation`, `main`, `contentinfo`, the skip link, no horizontal
    overflow (`scrollWidth <= innerWidth`), every button and nav link at least 44 × 44 on the
    phone project, axe clean; `tests/unit/app-shell.test.tsx`; `smoke.spec.ts` asserts the
    shell landmarks. `AGENTS.md › Styling` states the rules above with the file names;
    `› Tests` states the phone project, the screenshots in `test-results/`, that e2e needs the
    database when the project has one (`docker compose up -d --wait <service>`, then the
    server's `migrate`), and the data rule (OQ6). Next implements the same in its idiom (the
    RSC layout, `loading.tsx`).
- **D7 Catalog fixes.** `by_ip` keys an IPv6 address by its /64 network and an IPv4 by its
  address; an IPv4-mapped IPv6 address is its IPv4. python-fastapi: `ipaddress` in
  `middleware/rate_limit.py`, test in `tests/middleware/test_rate_limit.py`; bun-express:
  `node:net` in `middleware/rate-limit.ts`, test in `tests/middleware/rate-limit.test.ts`.
  python-fastapi `AGENTS.md › Packages and conventions`: on Windows the `--reload` parent leaves
  its child on the port; stop by port
  (`Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id
  $_.OwningProcess }`), and the `dev` command stays.
- **D8 Bootstrap verify.** Section 4: before the app check, `docker compose stop database`
  (the app project publishes the same loopback port), after `down` `docker compose start
  database`; stop dev servers by port with the recipe above, naming the reload child. Section 5
  ends by ticking the three "Ready to plan" boxes once they hold (F9b); the Change Log's FILL
  line is replaced by the initial entry and later entries go above it (F9c). Section 6 names
  what the scaffold removed. `dev-loop` section 0 also requires the three boxes ticked.
- **D9 Line endings.** `.gitattributes`: `* text=auto eol=lf`, `*.ico binary`, `*.png binary`.
  The index is LF already, so nothing renormalises; a fresh clone checks out LF on Windows.
  An existing checkout is refreshed by Eitan by hand (`git checkout -- .` after the merge; the
  hooks refuse it for agents, and the tree is clean). README: the headless note names
  `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` as what the eval driver used (F9d), and the clone
  checklist says the bootstrap removes the harness plans. `AGENTS.md › Repository layout`: the
  `.plan/NNN-*` row says so too.

### Harness tasks (Sonnet implementers; disjoint files per task)

1. **H1, history** (D1): `scripts/history.mjs`, `scripts/history.test.mjs`, the call and step in
   `scripts/bootstrap.mjs`, the markers in `.doc/glossary.md` and `.doc/architecture.md`, the
   three Change Log entries removed, `bootstrap-project` section 1 (leave the marked Auth text
   alone; the scaffold resolves it) and section 6.
2. **H2, hooks** (D5), in the worktree: `guardrail.mjs`, `enforce-agent-boundaries.mjs`,
   `heredoc.test.mjs`; `node --test ".claude/hooks/test/*.test.mjs"` before (1188) and after.
3. **H3, process text** (D2, D3, D4): `writing-plans/SKILL.md`, `template.md`,
   `orchestrator.md`, `dev-loop/SKILL.md` sections 0, 2, 3, 4; `backend.md`, `frontend.md`
   (report formats, step 3), `qa.md` (step 4), `reviewer.md`, `code-review/SKILL.md`,
   `writing-tests/SKILL.md`, `AGENTS.md › Definition of done`.
4. **H4, UX and bootstrap text** (D6 harness side, D8, D9), after H1: `ui-and-styling.md`,
   `.doc/product-definition.md › Design`, `bootstrap-project` sections 1, 4, 5, `frontend.md`
   step 1, `qa.md` step 6, `template.md › Frontend`, `.gitattributes`, `README.md`, `AGENTS.md ›
   Repository layout`.
5. **H5, lock bump** (after Eitan tags `v1.3.0`): `catalog.lock` with a fresh-cache bootstrap
   (P2 is its proof). A separate one-line PR.

### Catalog tasks (paths relative to `fullstack-templates/`)

1. **C1, ADR 0004** (D6, D7, OQ6–OQ9): `docs/adr/0004-ui-baseline.md`, `docs/conventions.md`,
   a pointer in `docs/adr/0003-spa-and-deploy-modes.md`. Gate G1 follows.
2. **C2, react 1.1.0** (after G1): the D6 files under `frontend/react/base/`, `template.yaml`,
   `CHANGELOG.md`, `AGENTS.md › Styling` and `› Tests`.
3. **C3, next 1.2.0** (parallel with C2): the same under `frontend/next/base/`.
4. **C4, servers** (parallel with C2): python-fastapi 1.1.1 and bun-express 2.3.1 per D7, with
   `CHANGELOG.md` and `template.yaml` each. Pins: if `validate` reports a moved pin for an
   overlay-shadowed file, reconcile and re-pin with `validate --pin`, reading the diff.
5. **C5, release docs**: `index.yaml`, `README.md` (`bun tools/validate.ts --readme`), v1.3.0
   notes drafted for the annotated tag; ADR 0004 As built.

### Proofs (the interactive session drives; Eitan's yes before each commit)

- **P1, second loop on the eval app** (after the harness final review; no catalog dependency).
  In `C:/Dev/Playground/AI/test-plant-care-eval`, on `feat/plant-list-add`: copy `AGENTS.md`,
  `README.md`, `.claude/`, `scripts/`, `.gitattributes` and the `Design` section (filled from
  the brief) from the harness branch, remove the inherited `.plan/001–010` by hand, commit
  `chore(harness): sync plan 011 fixes` (its hash is the task's Base). Put
  `- [ ] app shell, mobile-first | stack:frontend` first in the backlog and run the loop
  unattended (`claude -p --model sonnet --permission-mode auto`,
  `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`, brief at `.orchestrate/eval-prompt-2.md`). The app is
  on react 1.0.0, so the shell is built by the product's frontend agent from the rules: a test
  of the rules, not of the template. Record the counts in the ledger (V30–V33).
- **P2, bootstrap only** (after H5). A fresh clone of harness `main` with its remote removed,
  the same brief's bootstrap answers (`react-python-fastapi`, `auth=false`, Postgres, `single`),
  `claude -p` through `/bootstrap-project` and the commit gate, no loop. About 15 minutes.

## Validation

**Harness**

- V01 — After a scaffold with `--flag auth=false`, `.plan/` holds only `000-backlog.md`; `.doc/`
  has no `<!-- auth` marker; the glossary has no `session`, `caller`, `OTP` or `target` row; the
  architecture Auth body is the `none` text; each file keeps its EOL — proof:
  `node --test scripts/history.test.mjs` (LF and CRLF fixtures) and P2.
- V02 — With `auth` on, the four rows and the default Auth body stay and no marker remains —
  proof: `scripts/history.test.mjs`.
- V03 — A `--root` scratch without `.plan/` is a no-op and `--fetch` never clears; a failed
  generation clears nothing — proof: `scripts/history.test.mjs`, and `ls .plan` in a `--root`
  scaffold.
- V04 — The harness's Change Log holds only the FILL line — proof: grep `^- 20` in
  `.doc/architecture.md › Change Log` is empty.
- V05 — The three F5 commands pass for every role agent; shell- and interpreter-consumed heredoc
  bodies and `hash-object -w` still block; the suite is green with no case removed — proof:
  `node --test ".claude/hooks/test/*.test.mjs"` in the worktree, ≥ 1188 passed plus the new
  cases, 0 failed.
- V06 — `writing-plans`, `orchestrator.md` and `dev-loop` name the same caps (12, 4, 250) and
  the scope rule — proof: grep the three files for the numbers.
- V07 — `Tests first:` is in both report formats, QA step 4 checks it, `writing-tests` and the
  Definition of done say it — proof: grep over `.claude/` and `AGENTS.md`.
- V08 — `reviewer.md` and `code-review` forbid gate re-runs, `testDb` and dev servers for
  reviewers — proof: grep.
- V09 — `bootstrap-project` section 4 stops the dev database before the app check and names the
  dev-server stop recipe; section 5 ticks the checklist; `dev-loop` section 0 requires it —
  proof: grep, and P2's driver transcript shows no hand intervention.
- V10 — A fresh clone's `.doc/*.md` are LF on Windows with `autocrlf=true` — proof:
  `git ls-files --eol .doc` in P2's clone shows `w/lf`.
- V11 — The `Design` section exists with FILL markers and is referenced by `ui-and-styling.md`,
  `bootstrap-project`, `frontend.md`, `qa.md` and `template.md` — proof: grep.
- V12 — The README names the headless variable and the removal — proof: grep.

**Catalog**

- V20 — The tools pass their gates and the catalog validates — proof: `cd tools && bun run
  check`; `bun tools/validate.ts`, `--lockfiles`, `--readme`.
- V21 — Every react and next case passes `check` and `testE2e` on both projects, with the shell
  spec (landmarks, skip link, no horizontal overflow, 44 px targets) and axe — proof:
  `bun tools/test-generated.ts --case frontend/react/<each> --e2e --with-services --with-app`,
  the same for `frontend/next/<each>`.
- V22 — The shell has a unit test in both templates — proof: `tests/unit/app-shell.test.tsx`
  inside each case's `check`.
- V23 — Two addresses in one IPv6 /64 share a bucket, two /64s do not, IPv4 is unchanged, an
  IPv4-mapped address is its IPv4 — proof: `tests/middleware/test_rate_limit.py` and
  `tests/middleware/rate-limit.test.ts`.
- V24 — `AGENTS.md › Tests` in react and next names the database dependency and the data rule;
  python-fastapi's `AGENTS.md` carries the Windows stop note; the headings check passes — proof:
  grep in the generated cases, `bun tools/validate.ts`.
- V25 — Every existing case still passes (regression) and the PR is green — proof: the full
  `test-generated` run and the PR's checks.
- V26 — On Windows, `frontend/react/default --with-app` builds and the phone project passes —
  proof: the command on Eitan's machine (CI is Linux).
- V27 — No `.skip`, `.only`, `test.fixme` or `describe.skip` in the changed templates — proof:
  grep.

**Proofs**

- V30 — P1's plan is within the caps (`grep -c '^- V[0-9]'` ≤ 12, `wc -l` ≤ 250, ≤ 4 open
  questions), lists no backend stage, has the sync commit as `Base:`, and `git diff --stat
  <Base>` names only the task's files although the branch carries plan 011's commit — proof:
  the plan file and the command.
- V31 — P1's frontend report carries a `Tests first:` line whose tests are in the diff, and QA
  marks it PASS — proof: `.orchestrate/report/{frontend,qa}.md`.
- V32 — P1's hook refusals contain no false positive: each is a shell write channel, inline
  code or a secret read — proof: the refusals in `.orchestrate/trace/*.jsonl` and the subagent
  transcripts, classified in the ledger.
- V33 — P1's reviewers ran no package gate (zero `check`, `test`, `testDb` or dev-server
  invocations; at most one targeted test file each), and QA's UX pass lists a phone screenshot
  per route with a verdict — proof: per-agent tool-call counts; `qa.md`.
- V34 — P2 ends with: `.plan/` holding only the backlog; no auth term and no harness Change Log
  entry in `.doc/`; the `Design` section filled; the three boxes ticked; LF `.doc/` files; the
  app check and the dev-server stop without hand intervention; the generated frontend with the
  shell and the phone project green — proof: the clone's files and the driver transcript.

## Risks

- **The script deletes files in a user's clone.** It deletes only `.plan/NNN-*.md`, only after a
  successful generation, only in a tree that passed the fresh-project check, and prints each
  path; a `git clone` keeps them in history, a GitHub-template copy loses them, which is the
  intent. V01–V03 and the README line.
- **A marker pass over CRLF files corrupts them.** EOL is detected per file and both fixtures
  are tested; the scripts stay dependency-free.
- **Stripping heredoc bodies opens a write channel.** Bodies are stripped only when no shell,
  `eval`, `source`, `xargs` or interpreter token is in the owning segment; the test set covers
  shells, `eval`, `docker exec … sh` and interpreters; the destructive and secret hooks still
  scan bodies.
- **Caps make the orchestrator under-specify.** The package `AGENTS.md` carries the shape and
  QA still checks every acceptance criterion; the user can raise a cap for one task by editing
  the plan.
- **A `Tests first:` line can be fabricated.** QA checks the names against the diff; an
  inconsistent line is a P1 and the transcript shows the run order.
- **The phone project doubles e2e time.** The suites are small (2–4 tests); accepted, in CI and
  locally.
- **A shipped shell constrains products.** It is a `shared/ui` component a product edits by
  plan; the rules fix the invariants (landmarks, one `main`, targets), not the look.
- **The /64 key throttles a household as one client.** Intended: the rotating attacker and the
  household share the prefix; limits are per product.
- **`.gitattributes` makes existing checkouts show changes.** The index is LF already, so only
  the working tree differs; the refresh is one named human command.
- **The catalog release gates the proofs.** P1 needs no catalog change; only P2 waits for H5.

## Rollout Order

1. G0; the hooks worktree.
2. H1, H2 and H3 in parallel (disjoint files); then H4.
3. C1, then G1; then C2, C3 and C4 in parallel; then C5.
4. A Sonnet review per task; one Opus final review per repository with one fix wave.
5. P1 on the eval app (after the harness final review).
6. The two PRs into `dev` on Eitan's yes. Eitan merges, merges `dev` → `main` and tags
   `v1.3.0`. Then H5, then P2.

## Rollback

- Each repository's change is one branch merged into `dev`: revert the merge commit there.
- Until H5 the lock pins `v1.2.0`, so every bootstrap is untouched by the catalog work; after
  it, revert the one-line lock change. A bad tag is superseded by a patch tag, never moved.
- History clearing acts only at a new bootstrap; no existing project changes. Reverting H1
  restores the inherited files for later clones.
- Removing `.gitattributes` restores `autocrlf` behaviour; the index was never rewritten.
- The hook change reverts to the 1188-case behaviour; no data or product is involved.

## As built (2026-10-25; rulings R1–R18 in the ledger)

- D1: the bootstrap deletes only plan files tracked at HEAD and unmodified, prints what it kept,
  resolves both `.doc/` texts before touching anything, and `history.mjs` has a CLI for
  recovery after a failed clear. The harness's own `.doc/` resolve to no marker in both variants.
- D3: `Tests first: after the fact — <reason>` is a valid report shape that QA judges.
- D5: heredoc bodies leave the redirect scan only for `cat` and `psql` consumers (after peeling
  docker and kubectl exec), with no pipe after the operator and a data body; the detector follows
  bash (word-boundary delimiters, comments, arithmetic, `$'`, continuations, quote state across
  non-body lines, bodies opaque); psql meta-commands `\!`, `\o`, `\out`, `\w`, `\write`, `\g`,
  `\gx`, `\s`, `\lo_export` are write channels on psql body lines; `hash-object` reads unless
  `-w`. Suite 1188 → 1367. Pre-existing and out of scope: quoted command substitution outside a
  heredoc is judged by no hook.
- D6: spacing is Tailwind's default 4 px multiplier (no `--spacing-N` keys); type, radius and
  shadow tokens live in a plain `@theme` block; an `input` colour token was added; the Windows
  stop recipe stops the port owner and its children (the owner is the dead reloader) and was
  proven on this machine; `focus-visible:outline-hidden` keeps the focus mark in forced colours.
- D7: the IPv6 /64 subject is the RFC 5952 compressed network string in both servers.
- Proofs: V20 ok; V21 for the react and next default cases and both `alone` cases; V25 subset
  (python stack, bun stack-auth-off); V26 proven on `react-bun-express` single on Windows; the
  python-backed `--with-app` smoke passed once the first eval's `plant-care-try` project was
  stopped (914 backend tests, e2e 10/10 against the container); P1 and P2 below.
- P1 (2026-10-25, eval clone, branch `feat/app-shell-mobile-first` from the sync commit
  55ffd32, task commit ecfc7bd; 23 min, about $10 on Sonnet with Opus reviewers): V30 holds
  (plan 012 is 218 lines, 11 validation items, 3 open questions, `Stages: frontend, qa`, Base
  55ffd32, the diff against Base is the task's 27 files only); V31 holds (`Tests first:` with
  8 failing tests named, QA checked each against the diff, PASS); V33 holds in letter (no
  reviewer ran a package gate; QA's UX pass read the `/` and not-found phone screenshots) but
  QA looked at 2 of 11 screenshots; V32 holds for the eval's three commands and every
  sub-agent refusal was a write channel (inline node and python, `sed -i`, redirects) except
  one new class: `git check-ignore` is refused for reviewers (read-only; a follow-up). Gates:
  frontend `check` 133 tests, `testE2e` 22/22 on chromium and phone; one fix round (the
  implementer's `format ok` claim was wrong). Follow-ups the run surfaced: re-run `check` last
  after a doc edit (frontend agent); no scratch files in the tree and relative `Delete:` paths;
  the e2e data rule for a product without a delete endpoint (OQ6 again); QA to read one
  screenshot per viewport and scheme the plan names; a delegated-approval clause and a P2
  disposition step in the dev loop; `git check-ignore` in the hooks' git read list.
- P2 (2026-10-25, fresh clone of `chore/catalog-v1.3.0` renamed `main`, remote removed, empty
  template cache; 6 min, 53 turns, $0.74 on Sonnet): V34 holds. The bootstrap cloned v1.3.0 and
  the provenance matches the lock; `.plan/` holds only the backlog (001–011 removed); `.doc/` has
  no auth marker or row, the Auth body is the `none` text, the only dated change-log line is the
  product's, the one `FILL` left is the production `TRUST_PROXY` marker; `Design` filled, three
  boxes ticked, all three files `i/lf w/lf`. Gates: `check` 632 + 65, `migrate`, `testDb` 707 with
  none skipped, `testE2e` 10/10 (chromium 5, phone 5) on the generated shell; the dev-server stop
  recipe freed both ports first time; the app check ran one container with the migrate one-shot
  and a clean `down`; the scaffold was committed on `chore/bootstrap`. Refusals: the clone
  checklist's secret-file probe (true) and a notes heredoc whose text named that file (the text
  rule). One self-recovered hiccup: the first `testE2e` exited 9 silently right after the browser
  install and left the dev servers listening; a cold re-run passed twice. Follow-ups: the react
  template's `webServer` should surface that failure and not reuse leaked servers (catalog);
  `bootstrap-project` §4 should name Compose's "variable is not set" warnings and §5 which `FILL`
  markers may remain; the Compose `name:` comes from `--name`, so two clones of one product share
  a dev database (P2 recreated the first eval's container on the same volume); `claude -p` in an
  untrusted workspace ignores the settings allow list (hooks still run); the bootstrap's "Done.
  Next" prints the poe task name where `AGENTS.md` says `testDb`.
- Release (2026-10-25): PRs #14 and catalog #9 merged into `dev`, then catalog #10 → `main`
  f1f38e7 tagged `v1.3.0` (release published) and harness #15 → `main` 2c27ce3; H5 on
  `chore/catalog-v1.3.0` (77c4e1c, PR #16 into `dev`) with the empty-cache `--fetch` proof. The
  hooks worktree is gone; branch `fix/plant-care-eval-hooks` and the eval Docker volumes are
  Eitan's to remove.
