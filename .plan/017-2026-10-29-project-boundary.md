# The project boundary: harness updates, the frontend choice and the project README

Status: done
Owner: Eitan
Last updated: 2026-10-29
Approval: delegated (2026-10-29, Eitan: "go, yes to both recommendations"), confirming OQ1 and OQ2
as recommended.
Input: the design `.superpowers/specs/2026-10-29-project-boundary-design.md` (approved by Eitan
2026-10-29: "approved, write the plan"); the survey of a generated project,
`C:/Dev/Playground/AI/fullstack-dev-harness-proof-015`.
Scope ruling (2026-10-26): only this repository and the catalog. C1 edits the catalog only on
Eitan's yes (OQ2).
Branch: harness `feat/project-boundary`, from `origin/dev`; catalog `fix/next-gitignore`, from
catalog `dev`.
Base: d67b222
Stages: harness only. Sonnet implementers, a Sonnet review per task, and an Opus final review.
The plan ends in one PR per repository into `dev`. No dev-loop proof: Eitan dropped P2's loop
proof on 2026-10-29, so this plan proves itself with scripted runs (Proof PB).

## Goal

A project made from the harness holds only what it needs, and keeps taking harness updates for
harness files only. Its frontend is Next.js only when public pages must be found by search
engines or show a rich preview when shared; otherwise it is the React single-page app. Its root
`README.md` describes the product in Eitan's structure, and the dev loop keeps that README's
Features and Configuration current.

## Scope

- In: a manifest that sorts every harness file into `harness`, `project` or `dev` (D1).
- In: a setup finish step that removes the `dev` group and records the harness version (D2, D8).
- In: the generated project README, its Configuration table, and the `verify` check (D3, D4).
- In: the frontend choice by need (D5).
- In: the `.gitignore` blocks (D6) and the catalog patch that keeps `.next/` out of React
  projects (C1, OQ2).
- In: the update command, with its compatibility check and the settings merge (D7–D9).
- In: the agent manual and the project conventions file (D10, D11).
- In: plan 016's closing note (D12).
- Out: migrating a React project to Next later. Proposed backlog line: `- [ ] migrate a
  single-page frontend to Next when search or share previews become a need`.
- Out: moving projects bootstrapped before this plan onto the update command. The existing ones
  are proofs and evals; `.claude/README.md` states the manual path.
- Out: new stacks, brownfield adoption (Phase 5), package READMEs.

## Assumptions

- The bootstrap skill already reads `static` from each package's `template.yaml` for the
  deploy-mode question (`bootstrap-project` §2), so D5 needs no catalog or script change.
- The catalog generator always appends a `base` section and each template's `gitignore:`
  sections to the root `.gitignore` (catalog `tools/lib/generate.ts`, `tools/lib/gitignore.ts`).
- `.env.example` files put a variable's description in the comment lines directly above it, and
  write an optional variable as `# NAME=value` (proof-015's `backend/` and `frontend/`).
- The dev-loop driver is `general-purpose`, with no write lane, so it can edit `README.md`
  without a hook change. This plan does not touch `.claude/hooks/`.
- `AGENTS.md` is at 1,199 words, so every addition must be paid for by a cut.
- A lock bump does not upgrade generated packages (`README.md` › Updating the harness), so a
  project's catalog version is frozen at setup.

## Open Questions

1. Which version does the first harness release carry, and when is it tagged? The harness has
   no tags today. Recommended: `v1.0.0`, tagged on harness `main` after this plan merges, through
   `cutting-a-release`. The manifest's `version` carries it.
   > Yes, as recommended (Eitan, 2026-10-29).
2. May C1 edit the catalog repository `C:/dev/Playground/AI/fullstack-templates`? That means
   branch `fix/next-gitignore`, then PRs into `dev` and `main`, then tag `v1.5.1`. Recommended:
   yes. Without it, every React project keeps two Next-only ignore lines.
   > Yes, as recommended (Eitan, 2026-10-29).

## Steps

### Decisions

- **D1, the manifest.** `.claude/harness.json` (a `harness` file) holds these fields:
  - `version`: the release tag, or `unreleased` on a branch;
  - `repository`: `https://github.com/EitanPano/fullstack-dev-harness`;
  - `rootCommit`: the harness's root commit, used by D2's history warning;
  - `minCatalog`: `v1.5.0`;
  - `groups`: glob lists for `harness`, `project` and `dev`;
  - `references`: the allowlist of `harness` files that may name a `dev` path, each with the
    path it names.

  `scripts/manifest.mjs` (harness) loads and matches it, reusing `scripts/verify/glob.mjs`.
  `scripts/manifest.test.mjs` (dev) checks two rules. Every `git ls-files` path matches exactly
  one group. No `harness` file names a `dev` path, except an allowlisted pair. The groups start
  as follows:
  - **`harness`:**
    - `.claude/agents/**`, `.claude/hooks/*.mjs`, `.claude/hooks/lib/**`, `.claude/rules/**`;
    - `.claude/skills/**` except `bootstrap-project/**`;
    - `.claude/settings.json`, `.claude/README.md`, `.claude/harness.json`;
    - `AGENTS.md`, `CLAUDE.md`, `.cursor/**`, `.github/copilot-instructions.md`,
      `.orchestrate/README.md`;
    - `scripts/verify.mjs`, `scripts/verify/*.mjs` except `*.test.mjs`;
    - `scripts/provenance.mjs`, `scripts/loop-stats.mjs`, `scripts/manifest.mjs`,
      `scripts/readme.mjs`, `scripts/harness-update.mjs`.
  - **`project`:** `.doc/**`, `.plan/000-backlog.md`, `catalog.lock`, `.gitignore` (outside its
    harness block, D6), `.gitattributes`.
  - **`dev`:**
    - `README.md` (replaced at setup);
    - `.claude/hooks/test/**`, `**/*.test.mjs`;
    - `scripts/bootstrap.mjs`, `scripts/history.mjs`, `.claude/skills/bootstrap-project/**`;
    - `.plan/[0-9][0-9][0-9]-*.md`.

  A file a project adds belongs to no group, so the update command never touches it.
- **D2, the setup finish.** `node scripts/bootstrap.mjs --finish` is the bootstrap skill's last
  step, just before its commit gate. It runs in this order:
  1. It refuses while `README.md` still holds a template placeholder (D3).
  2. It writes `.fullstack/harness.json` (D8).
  3. It removes the `.gitignore` dev block (D6).
  4. It removes every `dev` file that git tracks unmodified, by the same rule `history.mjs`
     applies to plans today; it never removes a modified or untracked file.
  5. It warns, and changes nothing, when the history contains the manifest's `rootCommit`.
     Agents never rewrite history; `.claude/README.md` recommends "Use this template".

  The step removes `bootstrap.mjs` itself. That is safe because Node has already loaded the
  file.
- **D3, the project README.**
  - **Template.** `.claude/skills/bootstrap-project/readme-template.md` (dev) holds Eitan's
    structure: About, Features, Getting Started (Prerequisites, Installation), Usage,
    Configuration, Running Tests, Contributing, License. The table of contents lists every
    section, Running Tests included.
  - **Mechanical sections.** `bootstrap.mjs` writes `README.md` from the template once the
    generator has run. It fills the mechanical sections from these sources:
    - Prerequisites: the stack's tools;
    - Installation: `git remote get-url origin`, or a placeholder, plus each package's
      `install`;
    - Usage: each package's `dev` command and port, plus the Compose `app` profile;
    - Running Tests: each package's `check`, `test` and e2e command.

    The commands are resolved from `.fullstack/catalog.yaml`, never typed into the template.
  - **Prose sections.** It leaves an explicit placeholder in About and Features. The skill
    replaces both from the product definition in §5: About from Purpose and the Problem
    Statement; Features from Product Scope, marked as planned.
  - **Contributing and License.** Contributing links to `.claude/README.md`. License names the
    `LICENSE` file, or states that none is chosen.
  - **Configuration.** `scripts/readme.mjs` (harness) parses every tracked `.env.example`. It
    renders `Variable | Description | Default` between `<!-- configuration:start -->` and
    `<!-- configuration:end -->`. An optional variable is marked optional, and a placeholder
    secret (`change-me…`) shows no default. Its CLI, `node scripts/readme.mjs --configuration`,
    rewrites that block only.
- **D4, README upkeep.**
  - **Definition of done.** `AGENTS.md` gets a new item: the README's Features names each
    user-visible capability the change adds, and its Configuration block is regenerated.
  - **The `verify` check.** The full `verify` run gains a `readme` step: `README.md` exists, and
    its Configuration block equals `readme.mjs`'s output. A `--package` or `--no-e2e` run skips
    the step, so implementers never need the README in their lane.
  - **The driver.** `dev-loop` §3 step 5 has the driver apply the deletions, run
    `readme.mjs --configuration`, and add the Features line from the plan's Goal, all before
    the full `verify`; §5 repeats this before each round's run.
  - **Review.** `code-review` gets one checklist line: a Goal that adds a capability has its
    Features line.
- **D5, the frontend choice.**
  - **The question.** `.doc/product-definition.md` › Non-functional Requirements gets
    `- Search and sharing:`, with a FILL marker that asks the yes/no question: do any public pages
    need to be found by search engines or show a rich preview when shared?
  - **Asking it.** `bootstrap-project` §1 infers the answer from a pasted brief and asks only
    when the brief is silent; without a brief, it asks.
  - **Choosing.** §2 stops listing stacks. "Yes" keeps the stacks whose frontend lacks `static`,
    and "no" keeps those whose frontend declares it. §2 then asks only the remaining choice,
    shows the stack with its reason, and accepts an override. A stack with no frontend skips
    the question.
  - **Recording.** The reason goes in `.doc/architecture.md`'s Stack row.
  - **The harness README.** Its stack paragraph says React is the default.
- **D6, the `.gitignore`.** Two marked blocks, in this order:
  - **The harness block** (D7 rewrites it): `.claude/settings.local.json`,
    `.claude/worktrees/`, `.superpowers/`, `.orchestrate/*`, `!.orchestrate/README.md`.
    - Opening marker: `# >>> harness: replaced on harness updates, do not edit inside this block`.
    - Closing marker: `# <<< harness`.
  - **The dev block:** the secrets, OS and build lines the harness repository needs before
    setup.
    - Opening marker: `# >>> harness-dev: removed at setup`.
    - Closing marker: `# <<< harness-dev`.

  The catalog's `base`, `node`, `python` and (after C1) `next` sections then supply a project's
  own lines, each once.
- **D7, the update command.** `node scripts/harness-update.mjs --version <tag|commit>`, or
  `--from <path>` for a local checkout. It fetches into
  `~/.cache/fullstack-dev-harness/<version>/` (`FULLSTACK_HARNESS_CACHE` overrides the path),
  the same way the bootstrap fetches the catalog. Its steps:
  1. It refuses a dirty tree.
  2. It refuses when the release's `minCatalog` is newer than the project's `catalog.lock`, and
     names the newest release the project can take.
  3. It lists the `harness` files whose hash differs from `.fullstack/harness.json`, and stops
     unless `--overwrite` is given.
  4. It backs up the current `harness` files to the OS temp directory.
  5. It writes every `harness` path of the new manifest and deletes the `harness` paths the old
     manifest had and the new one dropped. It refuses when a new `harness` path already exists
     as a project file. It rewrites the `.gitignore` harness block and merges `settings.json`
     (D9).
  6. It runs each hook in `.claude/settings.json` once, with a benign payload. If any hook
     fails, it restores the backup and exits non-zero.
  7. It prints, as advice only, the upstream diff of the seeded `project` files, then rewrites
     `.fullstack/harness.json`.

  `.claude/settings.json` allows `node scripts/harness-update.mjs*` and
  `node scripts/readme.mjs*`.
- **D8, the version record.** `.fullstack/harness.json` (project) holds the manifest's
  `version`, the harness commit (or `null` when the history does not contain it), and a SHA-256
  hash per `harness` file. A project that started from "Use this template" still gets a
  complete record.
- **D9, the settings merge.**
  - **Project entries.** An entry in `permissions.allow` or `permissions.deny` is a project
    entry when the `settings.json` content recorded at the last setup or update lacks it.
    D8 stores that content.
  - **The merge.** The result is the new release's file, with the project entries appended to
    their arrays.
  - **Other keys.** A project change to any other key is a local edit, handled by D7 step 3.
- **D10, the agent manual.**
  - **`.claude/README.md` (`harness`).** It takes these sections from today's `README.md`:
    How work moves, the guardrails and their recovery, Integrations, and Updating the harness
    (rewritten around D7). It also documents the manual path for older projects.
  - **`AGENTS.md`.** Its recovery pointer moves to `.claude/README.md`.
  - **The harness `README.md` (`dev`).** It keeps the rest: what the harness is,
    prerequisites, the clone checklist ("Use this template" first), the lock-bump checklist,
    and how a harness release is cut.
- **D11, the conventions file.** `.doc/conventions.md` (`project`) is tracked with a header line
  and an empty list. `AGENTS.md` › Product and domain names it, and `CLAUDE.md` imports it after
  `AGENTS.md`. Project-specific agent rules go there; updates never touch it.
- **D12, closing plan 016.** `.plan/016-2026-10-29-visual-loop.md` gets `Status: done` and a
  `## Changes during the task` entry: P2 was dropped by Eitan on 2026-10-29, so V09–V11 were not
  measured.

### Tasks

H1, H2, H5 and C1 work on disjoint files in parallel. H3 and H4 follow H1, and H3 also follows
H2. A Sonnet review follows each task.

| Task | Content | Files |
| --- | --- | --- |
| H1, the manifest | D1 | `.claude/harness.json`, `scripts/manifest.mjs`, `scripts/manifest.test.mjs` |
| H2, the README tooling | D3 (Configuration), D4 (the `verify` step) | `scripts/readme.mjs`, `scripts/readme.test.mjs`, `scripts/verify.mjs`, a new `scripts/verify/readme.mjs`, `scripts/verify.test.mjs` |
| H3, the setup | D2, D3 (the template and its filling), D8 (writing the record) | `scripts/bootstrap.mjs`, `scripts/bootstrap.test.mjs`, `scripts/history.mjs`, `scripts/history.test.mjs`, `.claude/skills/bootstrap-project/readme-template.md` |
| H4, the update command | D7, D8 (reading the record), D9 | `scripts/harness-update.mjs`, `scripts/harness-update.test.mjs` |
| H5, the text | D4 and D5 text, D6's file, D10, D11 | `AGENTS.md`, `CLAUDE.md`, `README.md`, `.claude/README.md`, `.doc/product-definition.md`, `.doc/conventions.md`, `.gitignore`, `.claude/settings.json`, and the skills `bootstrap-project`, `dev-loop`, `code-review` |
| C1, the catalog patch (OQ2) | D6's `next` section | catalog `shared/gitignore/node.gitignore`, a new `shared/gitignore/next.gitignore`, `frontend/next/template.yaml` (`gitignore: [node, next]`), `tools/tests/gitignore.test.ts`, and the schema if it lists section names |
| H6, the driver | the lock, D12 | `catalog.lock` → `v1.5.1`, after C1's tag; `.plan/016-2026-10-29-visual-loop.md` |

Then the Opus final review of both branches, and a fix wave.

### Proof PB

PB runs in disposable sibling clones of the branch head. Before it starts, the session checks
that nothing listens on ports 3000, 4000, 5173 or 8000, and asks Eitan if something does.

1. **PB1**, in `C:/Dev/Playground/AI/fullstack-dev-harness-proof-017`: a bootstrap from a short
   brief that says "Search and sharing: no", with the Bun server and no database. It must pick
   `react-bun-express` and state the reason.
2. **PB2**, in `…-proof-017-next`: the bootstrap skill with a "yes" brief, stopped at the §2
   summary. It must pick a Next stack and state the reason.
3. **PB3**, an update applied to PB1's project from a scratch clone of the branch head. The
   scratch clone carries one extra commit that edits a hook comment, removes one `harness`
   file and adds one. PB3 runs four times:
   - a clean run;
   - a run after hand-editing a `harness` file;
   - a run with a deliberately broken hook;
   - a run after adding a project `allow` entry.

## Validation

- V01 — Every tracked harness file sits in exactly one group, and no `harness` file names a
  `dev` path outside the allowlist. Proof: `node --test scripts/manifest.test.mjs`.
- V02 — `--finish` holds four properties:
  - it removes only unmodified tracked `dev` files and the dev block;
  - it writes the record with a hash per `harness` file;
  - it refuses a README that still holds a placeholder;
  - it warns on harness history.

  Proof: `node --test scripts/bootstrap.test.mjs scripts/history.test.mjs`.
- V03 — `readme.mjs` renders the Configuration table from `.env.example` files: optional
  variables marked, placeholder secrets without a default. The full `verify` fails on a
  missing variable, an extra one, or a missing `README.md`, and passes once the table is
  regenerated. A `--package` run skips the check. Proof: `node --test scripts/readme.test.mjs
  scripts/verify.test.mjs`, with a red run first.
- V04 — The update command:
  - replaces only `harness` paths and deletes the dropped ones;
  - rewrites the harness block and keeps project `allow` and `deny` entries;
  - stops on a local edit and refuses a dirty tree;
  - refuses a `minCatalog` above the project's lock, naming the newest compatible release;
  - restores the backup after a failed hook run.

  Proof: `node --test scripts/harness-update.test.mjs`.
- V05 — PB1 shows the finished project:
  - a README in Eitan's structure, with no placeholder left;
  - no `dev` file;
  - a `.gitignore` with no duplicate line and no `.next/`;
  - `.doc/conventions.md` present;
  - the bootstrap's `verify` exits 0.

  Proof: the clone's `verify.json`; `git ls-files` checked against the dev globs;
  `grep -v -e '^#' -e '^$' .gitignore | sort | uniq -d` prints nothing.
- V06 — PB1 picks React and PB2 picks Next, each with its reason in the summary and in
  `.doc/architecture.md` (PB1). Proof: both transcripts and PB1's `architecture.md`.
- V07 — In PB3, the clean run changes only `harness` paths, the harness block and the record
  `.fullstack/harness.json` (rewritten by design), leaving every other project file
  byte-identical. The three other runs stop, roll back, and keep the entry, respectively.
  Proof: `git status` and `git diff --stat` after each run.
- V08 — Catalog v1.5.1:
  - a React stack's generated `.gitignore` has no `.next/` or `next-env.d.ts`;
  - a Next stack's still has both;
  - catalog CI is green.

  Proof: `tools/tests/gitignore.test.ts`, the PR's checks, PB1.
- V09 — The suites hold:
  - hooks 1702/1702;
  - every scripts test passes;
  - `AGENTS.md` is at 1,200 words or fewer.

  Proof: the hooks and scripts test runs; the word count, in the ledger.
- V10 — Each task got a Sonnet review, and each branch an Opus final review, with no open P0 or
  P1. Proof: the ledger `.superpowers/sdd/017-2026-10-29-project-boundary/progress.md`.

## Risks

- **An update leaves a broken hook in a project, which blocks every tool call.** Mitigation: D7
  step 6 restores the backup (V04, V07). `.claude/README.md` keeps the manual recovery.
- **The finish step deletes something a project needs.** Mitigation: it removes only unmodified
  tracked `dev` files, and V01 keeps the groups complete. The check `references` makes a shipped
  pointer to a `dev` file fail.
- **`AGENTS.md` exceeds its budget.** Mitigation: the new layout rows replace the rows they
  supersede, and the DoD item is one line (V09).
- **React is now the default but barely exercised by the loop.** One proof clone ran it (P3a).
  Mitigation: stated in `.claude/README.md`; the first React projects find its gaps.
- **The settings merge misclassifies an entry.** Mitigation: the classification compares
  against the recorded file, not a guess (V04).
- **The catalog patch is not approved.** Mitigation: H1–H5 do not depend on it; without C1, V08
  and V05's `.next/` clause drop and are recorded.

## Rollout Order

1. G1: Eitan sets `Status: active` and answers OQ1 and OQ2.
2. H1 ∥ H2 ∥ H5 ∥ C1 (C1 only on OQ2's yes), each followed by its review.
3. H3 ∥ H4, each followed by its review.
4. C1's PR into catalog `dev`, then `main`, then tag `v1.5.1`, each on Eitan's yes. Then H6.
5. The Opus final review and a fix wave.
6. PB, then the As built section, then the PR into `dev` on Eitan's yes.

## Rollback

One branch per repository, each merged with a merge commit; reverting a merge restores the
previous files. Catalog v1.5.1 affects only new projects. No project yet carries a
`.fullstack/harness.json`, so no project depends on the update command.

## Changes during the task

- **Execution (driver, 2026-10-29).**
  - Nothing is committed until Eitan's yes. Implementers leave the work uncommitted, and the
    reviews read working-tree diffs.
  - H1, H2, H5 and C1 ran in parallel; H5 was split into H5a (root text) and H5b (skills and the
    product form).
  - A Sonnet review per task, an Opus whole-branch review and one fix wave. The rulings (R1–R24)
    are in the ledger `.superpowers/sdd/017-2026-10-29-project-boundary/progress.md`.
- **D1 as built.**
  - A group entry that starts with `!` excludes. The plan glob is `.plan/*.md` minus
    `!.plan/000-backlog.md`, because the glob syntax has no character classes.
  - `README.md` is in the `project` group, as the design's table has it: setup replaces it and
    never removes it.
  - The manifest and the record carry `format: 1`, and the updater refuses an unknown format.
- **D2 as built.**
  - `--finish` refuses without a HEAD or with an empty harness list. The skill's `git init` path
    asks to commit the untouched harness first.
  - It also reports modified harness files and the dev files it kept.
- **D3 as built.**
  - The prose placeholders are `<!-- readme:about -->` and `<!-- readme:features -->`.
  - Planned features read `- <capability> (planned)`.
  - Prerequisites come from each template's declared `tools`.
  - Untracked, non-ignored `.env.example` files count, because a loop's new example file is
    uncommitted at the full `verify`.
  - The dev URL is the frontend's port.
- **D4 as built.** The driver's README step is unconditional and removes the ` (planned)` suffix
  from a delivered line.
- **D7–D9 as built.**
  - **Ownership.** The record's file list, not glob matches, defines what the harness owns in a
    project. `buildRecord` takes an explicit list. Deletions cover only record files that the
    release no longer tracks at all; a file reclassified out of `harness` stays.
  - **Hook check.** It runs only the `PreToolUse` hooks, with Read, Bash and Edit payloads.
  - **Atomic apply.** The apply phase, including the record, sits inside one backup and restore.
  - **The record.** A record without `settings` is refused.
  - **Advice.** The advice diff skips `README.md` and falls back to the recorded version tag.
  - **Permission.** `node scripts/harness-update.mjs` moved from `permissions.allow` to
    `permissions.ask`.
- **Validation edits.** V05's duplicate-line command ignores blank lines, and V07 exempts the
  record.

## As built

- **Harness:** eight commits on `feat/project-boundary` (49901dc..87ff3ba), base d67b222.
- **Catalog:**
  - #18 (`fix/next-gitignore`) merged into catalog `dev` as aa4cbe1, CI 32/32;
  - release #19 merged into catalog `main` as 87820a3, CI 64/64;
  - tag v1.5.1 on 87820a3, published by the release workflow (run 40933781863);
  - harness `catalog.lock` pins v1.5.1 (239a7f9).
- **Ledger:** `.superpowers/sdd/017-2026-10-29-project-boundary/progress.md`, rulings R1–R26, where every
  proof command's output is recorded.

Validation:

- **V01 holds.** The manifest's real-tree tests pass inside the scripts suite: 262/262 on the
  branch head. Every tracked file is in exactly one group. No `harness` file names a `dev` path
  outside the allowlist. No `harness` module imports a `dev` one.
- **V02 holds.** `bootstrap.test.mjs` and `history.test.mjs` cover these cases:
  - no HEAD, or an empty harness list;
  - a README placeholder or a missing README;
  - a staged-new dev file, and one already deleted;
  - the multi-group guard and an unterminated dev block;
  - the history warning and the record.
- **V03 holds.** `readme.test.mjs` and `verify.test.mjs` cover these cases:
  - optional variables and placeholder secrets;
  - a deleted unstaged example;
  - a stale table, a missing block and a missing README;
  - partial runs skipping the check.
- **V04 holds.** `harness-update.test.mjs` passes 27/27. It covers these cases:
  - the record keys deletions and collisions;
  - a reclassified file is kept;
  - the settings merge, and a non-permission edit counts as a local edit;
  - a null `settings` and an unknown `format` are refused;
  - `minCatalog` names the newest compatible tag;
  - a dirty tree and a non-repository root are refused;
  - the atomic apply restores after a failure past the hook check;
  - the real shipped hooks pass the three payloads.
- **V05 holds.** PB1 ran in `…-proof-017`: a "no" brief, Bun, no database, about 6.5 minutes.
  - The bootstrap's `verify` passed: backend check 419, frontend check 254, e2e 40, nothing
    skipped. The dev check and the Compose app check passed too.
  - `--finish` exited 0 and the scaffold was committed (ef77cfc).
  - No `dev` file is left; `.plan/000-backlog.md` stays.
  - `.gitignore` has no duplicate line and no `.next/` or `next-env.d.ts`.
  - The README follows the structure, with no `readme:` marker, and
    `readme.mjs --configuration` leaves the tree clean.
  - `.doc/conventions.md` is present, and `.fullstack/harness.json` records the commit and the
    harness files.
- **V06 holds.**
  - PB1 inferred "no" from the brief and chose `react-bun-express`, deploy `single`, with the
    reason "single-page app: no public page needs search or sharing" in the summary and in the
    Stack row.
  - PB2 (`…-proof-017-next`, stopped at the summary) inferred "yes" and chose
    `next-bun-express`, with the reason "server-rendered (Next): public recipe pages need search
    and sharing previews".
  - Both offered an override.
- **V07 holds.** PB3 applied a scratch release (`…-proof-017-release`) to PB1's project four times:
  - **Clean run:** exit 0. Only the edited hook, the removed and the added harness file, and
    the record changed.
  - **Hand-edited harness file:** the update stopped (exit 1), named the file and wrote
    nothing.
  - **Broken hook:** the hook check failed, everything was restored and the backup path was
    printed; the tree and HEAD were unchanged.
  - **Project allow entry:** the entry was kept, and the record's `settings` stayed the
    release's own.
- **V08 holds.**
  - `tools/tests/real-catalog.test.ts` covers all four stacks.
  - Catalog CI passed: 32/32 on #18 and 64/64 on #19.
  - PB1's React `.gitignore` has no Next lines.
- **V09 holds.**
  - hooks 1702/1702 (unchanged);
  - scripts 262/262 (163 before the plan);
  - `AGENTS.md` at 1,200 words.
- **V10 holds.**
  - Each task got a Sonnet review, with fix rounds on H1, H2, H4 and H5a.
  - An Opus whole-branch review found six Important issues, fixed in one wave. Its Opus
    re-review found three deleted tests, which were restored.
  - PB1's two defects were fixed and re-reviewed.
  - No P0 or P1 finding is open; the minors are parked in the ledger.

Found by the proof and fixed (87ff3ba):

- A project made by `git clone` of the harness got the harness URL in its README.
- `--finish` listed already-deleted plans as kept.

Follow-ups (proposed backlog for the harness, not done here):

- `harness-update.mjs`: `main()` loads the project manifest unwrapped (a stack trace on a bad
  format). `localEdits` refuses on an edited file that a release reclassifies to `project`.
- `history.mjs`: `templateTools` reads `min` only in the one-line YAML style, and keeps the first
  minimum on dedupe.
- `bootstrap-project` SKILL.md (PB2): lines ~51–56, which read the server `AGENTS.md` for template
  gaps, conflict with ~160–162, which allow only three catalog files. It is also unclear how much
  of `architecture.md` and `glossary.md` to fill before the summary.
- `verify.mjs --help` exits 2. This predates the plan.
- The remaining parked minors are listed in the ledger.

Release: harness v1.0.0 is tagged on `main` after this branch merges (OQ1). The release commit sets
`version` in `.claude/harness.json`.
