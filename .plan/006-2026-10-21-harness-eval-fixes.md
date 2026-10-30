# Harness fixes from the todo-app evaluation

Status: done (executed 2026-10-21 by the interactive session with one Sonnet implementer for
the auth prune; V01–V08 verified independently in fresh `--root` scaffolds; final Opus review
fixed in one wave and re-verified; uncommitted, awaiting Eitan's review)
Owner: Eitan
Last updated: 2026-10-21
Approval: Eitan's instruction on 2026-10-21, "also fix the issues", after the side-by-side
todo-app evaluation; decisions taken by question the same day: "bootstrap --auth none" and
"driver applies moves".
Branch: `feat/fullstack-capability`
Stages: harness only (no role agents; the interactive session executes it with one Sonnet
implementer for the auth prune)

## Goal

An unattended Sonnet run of this harness built a working todo app (eval clone
`harness-eval/todo-branch`, transcript `harness-eval/logs/todo-branch.jsonl`) but hit
avoidable friction: 28 guardrail blocks, 17 of them false positives; a backend lane that
cannot write the files the `database` skill requires; a bootstrap that never commits feeding
a dev loop that demands a clean tree; reviewers reading `git diff main`, which on a task
branch includes every earlier committed task; role agents unable to move a file; a QA
stack only a human could remove; and ~4.4k lines of auth template shipped into an
`Auth: none` product, which the data-layer task then ported to Postgres. After this plan
each of those holds by construction.

## Scope

- In:
  - `enforce-agent-boundaries.mjs`: redirect parsing stops at shell operators, so
    `2>&1;`, `>/dev/null;` and `2>&1|tail` are harmless; git global options (`-C <dir>`,
    `--no-pager`, `-P`, `--git-dir`, `--work-tree`) are skipped before the subcommand;
    `git -c` stays refused (a config override such as `core.pager` runs commands);
    `--output` on a git read command is a write channel; the backend lane gains
    `docker-compose.yml` and `db/`.
  - The dev loop records the task's base commit as `Base:` in the plan; every stage reads
    `git diff <Base>`; outside the loop the base is `main` unless the user names one.
  - The bootstrap ends at a commit gate; the dev loop's dirty-tree precondition says what
    to do.
  - Deletions (and so renames): a role agent writes the new file itself and lists the path
    to remove under `Delete:` in its stage report; the driver runs
    `git add --intent-to-add .` then `git rm -f -- <path>`, only for a plain path inside
    that agent's own lane, and hands any other line to the user. (Revised after review:
    the first draft's `Moves:` with `git mv` failed on untracked and modified files and let
    a restricted agent steer the unrestricted driver.)
  - AGENTS.md states the lanes' threat model: they stop accidental writes outside a lane;
    they are not a sandbox, since a role agent runs scripts and code can write anywhere.
  - QA never starts a separate Compose project.
  - README: a fresh clone ignores `permissions.allow` until the workspace is trusted.
  - `node scripts/bootstrap.mjs --auth none` scaffolds a backend without authentication;
    `--auth full` (the default) is today's scaffold.
- Out:
  - Re-running the evaluation (offered separately).
  - The main-branch harness (superseded by this branch).
  - Claude Code's own background-agent wakeups in headless runs (not harness behaviour).

## Assumptions

- Role-agent shell posture is unchanged: Edit/Write only, no deletions, no git writes
  (AGENTS.md Guardrails; `.plan/001`). This plan only removes false positives.
- The template ships working auth and a product starts from it (`.plan/005`); `--auth none`
  is the explicit opt-out recorded as `Auth: none` in `.doc/architecture.md`.
- Harness validation happens in scratch scaffolds made with `--root` (`.plan/003`–`005`).

## Open Questions

1. Does `--auth none` keep `ENCRYPTION_KEY` and `services/security/crypto.ts`?
   Recommended: yes. Crypto is a generic capability (rate-limit hashing, field
   encryption), not an auth feature.
2. Does `--auth none` keep the reference module `api/module/`? Recommended: yes, as public
   endpoints with the caller, role gate and ownership comments removed, so the exemplar
   stays in every scaffold.
3. Marker comments in `templates/` or overlay copies of the changed files? Recommended:
   markers (`// @auth` drops a line, `@auth-start` … `@auth-end` drops a block, in the
   comment syntax of the file). One source per file; the bootstrap strips the markers in
   both variants and Prettier runs last, so no scaffold contains one.

## Steps

### Guardrails

1. `.claude/hooks/enforce-agent-boundaries.mjs`: the redirect target capture stops at
   whitespace and `; | & ( ) < >`; `HARMLESS_REDIRECT` also accepts `N>&-`; git global
   options are skipped before the subcommand, with `-c` refused by name; `--output`
   (any spelling) on a git read refuses; the `backend` lane adds `docker-compose.yml` and
   `db/`.
2. A payload probe (scratch) covers every command the eval refused plus the must-still-block
   set.

### Process

1. `.claude/skills/writing-plans/` (SKILL and template): `Base: <commit>` metadata.
2. `.claude/skills/dev-loop/SKILL.md`: record the base at branch creation; `git diff <Base>`;
   the dirty-tree precondition; applying `Delete:`; QA compose rule.
3. `.claude/skills/bootstrap-project/SKILL.md`: the Auth answer picks `--auth`, and for
   `none` the skill gives the exact text that replaces `.doc/architecture.md` Auth; the
   commit gate ends the skill. `database` and `api-design` skills say what does not exist
   under Auth: none.
4. `.claude/skills/code-review/SKILL.md`, `.claude/agents/reviewer.md`, `.claude/agents/qa.md`:
   `git diff <Base>`.
5. `.claude/agents/backend.md`, `frontend.md`, `qa.md`: the `Delete:` report line; the
   backend lane prose; the QA Compose rule.
6. `AGENTS.md` (Guardrails, Authentication) and `README.md` (trust note, `--auth`).

### Auth prune (Sonnet implementer)

1. `scripts/bootstrap.mjs`: `--auth full|none` (default `full`); a delete list of whole
   files for `none`; a marker pass over `backend/` and `docker-compose.yml` that drops
   marked lines and blocks for `none` and strips the markers for `full`; package
   dependencies only auth uses are removed for `none`.
2. `templates/backend/**` and `templates/root/docker-compose.yml`: markers on routes,
   env secrets (`JWT_ACCESS_SECRET`, `JWT_REFRESH_SECRET`, `OTP_SECRET`, `COOKIE_DOMAIN`),
   cookie parsing, the session job and the welcome subscriber, `res.locals` caller typing,
   the reference module's auth, the auth parts of tests, `.env.example`, compose, and the
   Authentication section of `templates/backend/AGENTS.md`. `@noauth` markers (line and
   block) carry the `none` wording where a line differs, so `full` stays byte-identical
   (V08). `DUMMY_HASH` (an argon2 hash at import) is auth-only.
3. The bootstrap checks every template marker for both variants before it creates anything,
   so a marker mistake cannot leave a half-built scaffold; the leftover check matches a
   marker only in comment form.

### Final review (Opus) and its outcome

Three P1s, all fixed: the `Moves:` flow (see Scope), the driver acting on a restricted
agent's report lines, and `.doc/architecture.md` describing auth under `--auth none`. P2s
fixed: skill carve-outs, template `AGENTS.md` drift, `DUMMY_HASH`, an authorization note in
the public reference module, the pre-scaffold marker check, the QA Compose line in the dev
loop, the layout table, compose scrutiny for the operations reviewer, "role agents" in the
README. The reviewer could not run its bypass hunt on the hook; the interactive session did
it (54-case probe, eval replay, abbreviated `--output` rejected by git). Recorded, not
patched: `git grep -O<cmd>` and `GIT_EXTERNAL_DIFF` run a program under a read subcommand
(also true at HEAD); they are the same class as running a script by path, which the lanes
allow by design, so AGENTS.md now states that the lanes are not a sandbox.

## Validation

- V01 — every guardrail block the eval logged as a false positive now passes for a role
  agent; every real write channel still blocks — proof: scratch payload probe, all cases pass
- V02 — the backend agent may write `docker-compose.yml` and `db/init.sql`, and still not
  `frontend/` — proof: payload probe
- V03 — `--auth full` scaffold passes every gate — proof: `bun run check` in both packages and
  `bun run test:e2e` in a `--root` scratch scaffold
- V04 — `--auth none` scaffold passes every gate — proof: the same commands in a second scratch
  scaffold
- V05 — no scaffold contains an `@auth` marker; the `none` scaffold contains no `jwt`, `otp`,
  `session`, `cookie` or `requireAuth` reference — proof: grep over both scaffolds
- V06 — `--auth` with any value other than `full` or `none` fails before scaffolding — proof:
  run it
- V07 — no `git diff main` remains in a dev-loop stage instruction — proof: grep over `.claude/`
- V08 — `--auth full` changes nothing: its `backend/` and `docker-compose.yml` equal, byte for
  byte, those of a scaffold made from the committed templates — proof: `git archive HEAD` export,
  both bootstraps with `--skip-install`, tree comparison

## Risks

- Markers drift from the code they mark — V03 and V04 scaffold and gate both variants; a
  stale marker fails a gate.
- A wider redirect allowance opens a write channel — the capture only stops earlier; every
  target is still matched against an anchored allow-list, and quoted targets stay blocked.
- The reference module loses its auth example in `none` scaffolds — intended; `full` keeps it.

## Rollout Order

guardrails → process docs → auth prune → validation in scratch scaffolds → final review

## Rollback

Every change is in harness files on `feat/fullstack-capability`, uncommitted. Revert the
files; no product, data or migration is involved.
