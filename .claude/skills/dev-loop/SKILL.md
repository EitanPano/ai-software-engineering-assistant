---
name: dev-loop
description: Take one backlog task from plan to reviewed, tested code through the role agents. Use when the user says "run the loop", "next task", "implement <task>", "start the dev loop", or asks to deliver a backlog item. Requires .fullstack/catalog.yaml (a fresh clone is set up first).
---

# Dev loop

The interactive session is the driver. It dispatches each role agent with the `Agent`
tool, reads the stage report the agent wrote, and decides what happens next. No agent
dispatches another agent; no agent runs the approval or the commit gate; no agent
commits, stashes or checks out (the hooks refuse it).

Every task keeps its files in `.orchestrate/<slug>/`: `plan.md` (the draft, section 2),
`backend.md`, `frontend.md`, `review.md`, `review-security.md`, `qa.md`, `ticket.md`,
`verify.json`, `review.diff` (`review-fix-<n>.diff` in a fix round). Each report starts
with the same header:

```
Stage: <backend | frontend | review | review:security | qa>
Task: <slug>
Verdict: <pass | fail>
```

`Verdict:` is informational. The loop branches on `verify`'s exit code and on the reports'
findings, never on that line.

Every dispatch sets the Agent `description` to `<slug>: <stage>`; `loop-stats` groups by it.

Nothing is committed until the end, so every stage but the reviewers (section 4) reads the
change as `git diff <Base>`: the working tree against the plan's `Base:` commit. `git diff
main` would also show earlier tasks committed on the branch chain.

The evidence is `node scripts/verify.mjs --plan <plan>`: contract freshness, `check`,
`testDb`, `testE2e` and the diff checks for every package, written to
`.orchestrate/<slug>/verify.json`. Exit 0 passes, 1 fails, 2 is a usage or environment
error. The driver always passes `--reuse`: when the tree equals the last passing run's, it
exits 0 without running anything. Otherwise `--reuse` reuses, per step, a passing result whose
key matches (the package's subtree hash, the shared inputs, the command line, the Base) and
prints `reused (<file>, <time>)`; a failing step is never reused, and the cross-package checks
always run. The key does not cover environment variables, git-ignored `.env*` files or
toolchains: after changing any of them, run `verify` without `--reuse`. An implementer's
`--package <dir>` or `--no-e2e` run is partial: it writes `verify-partial.json` (shared by
backend and frontend) and never satisfies `--reuse` as a whole run, but its passing steps are
reused per package. A full run also records `security: { triggered, paths }` in `verify.json`
and, with a Base, writes the review package `review.diff` (section 4).

`verify` can outlive the Bash tool's timeout. The driver runs its full run with the Bash
tool's `run_in_background: true` and waits for the completion notification. A role agent
runs its partial run in the foreground with `timeout: 600000` and never ends its turn while a
command it started is still running: a sub-agent that ends its turn is finished, and a
headless run has nothing left to resume it.

Do not edit tracked files while a background `verify` runs: its `tree-unchanged` step fails.

Role agents cannot delete files (the hooks refuse it). They list a file to remove under
`Delete:` in their report; the driver removes it (sections 3 and 4).

## 0. Preconditions

- `.fullstack/catalog.yaml` exists (setup ran). Otherwise this is a fresh clone: set it up
  first (the `bootstrap-project` skill exists only until setup removes it).
- The working tree is clean and the branch is not `main`. A tree left dirty by the
  bootstrap means its commit gate was never answered: ask the user to approve that
  commit. Any other uncommitted change: list it and stop; never stash or discard it.
- The three boxes of `## Ready to plan` in `.doc/product-definition.md` are ticked and each one
  holds. If a box is open or a section it names still has a `FILL` marker, the bootstrap did not
  finish: stop and ask the user to finish it. A stack with no frontend answers Design "n/a".

## 1. Pick the task

Take the first unchecked line in `.plan/000-backlog.md` unless the user names one. Parse
its markers: `stack:frontend` (no backend stage), `stack:backend` (no frontend stage),
`figma:<url>` (design reference). Read the `tracker:` header. Derive the slug from the title:
kebab-case, the key nouns and the action, at most four words; after a lookahead, the slug it
used.

## 2. Plan, approve, then branch (orchestrator, Opus)

If the lookahead already produced `.orchestrate/<slug>/plan.md` for this task, use it: size-check it,
approve it if not yet active, then cut and promote (below); do not plan the task twice. Otherwise
dispatch `orchestrator` with: the task line, the slug, the paths of the existing plans, and
this instruction:

> Write the implementation plan draft for this task per the `writing-plans` skill and its
> template, to `.orchestrate/<slug>/plan.md`. Status: draft. Include the Contract section when
> the task touches the API. Print the draft path on the last line.

Size check before showing the draft: `grep -vc '^[[:space:]]*> ' <draft>` at most 120 (answers under an Open
Question are `> ` lines and do not count), `grep -c '^- V[0-9]' <draft>` at most 8, the numbered
Open Questions at most 3. Over a cap: re-dispatch the orchestrator once with "bring the plan
within the caps of `writing-plans › Sizing a product task`, or split the task". Over again: show
the draft with the counts and let the user decide. Add backlog lines a plan proposes under `Out`
only on the user's yes.

Then stop and ask the user to review the draft. The user approves by editing
`Status: draft` to `Status: active` (and answering the Open Questions in the file). Do not
continue while the draft says `draft`. When the user has delegated approval for the run, the
driver reviews the draft critically, writes each answer under its question as `> ` lines, sets
`Status: active` and writes `Approval: delegated (<date>, <the user's words>)`. Without that
delegation, do not edit the status yourself.

When the draft is active, cut the branch and promote the draft:

1. Create `feat/<slug>` (or `fix/`, `chore/`) from the current branch; after a committed task,
   that is the task's branch.
2. Copy the draft to `.plan/NNN-YYYY-MM-DD-<slug>.md` with the next free number, and write
   `Branch:` and `Base:` (`git rev-parse HEAD`) in it. `verify --plan` reads this file.

If `tracker: linear` and the Linear tool is available, dispatch the orchestrator once more to
create one ticket per stage (Todo, medium priority, plan path in the description) and write
the ids to `.orchestrate/<slug>/ticket.md`. Otherwise write that file yourself with
`tracker: none` (or `tracker: none (Linear tool unavailable)`, and say so). Never block on a
tracker.

## 3. Implement

Stages come from the plan's `Stages:` line. Pass each implementer the plan path, the ticket
id and (frontend) the figma URL if any.

1. With a Contract section, dispatch `backend` for the contract stage only: the failing
   request-schema tests (one per validation rule the plan names), then models, schemas,
   registration, every contract change the plan implies (removals and renames included), the
   `contract` command, its report, then stop. The contract is final after this stage.
2. Then, in one message, SendMessage to that backend agent ("continue: implement the rest of
   the plan") and dispatch `frontend`. With no backend stage, or no Contract section, backend
   and frontend start together in one message. A backend report's `Commands:` line (the
   data-layer task adds `testDb`, `migrate` and `e2eDb`; only names from the `AGENTS.md` command
   table count, any other command stays in the report's `Handoff:`) is written into
   `.fullstack/catalog.yaml` under `packages.<dir>.commands` as soon as it arrives, before any
   later frontend dispatch and before the next `verify`. A full-stack data-layer task therefore
   runs its backend stage first; read `.claude/skills/database/data-layer-task.md` before you
   dispatch its frontend stage, which needs three template files from you (item 7).
3. The frontend stops after `check` with `E2E: pending backend` in its report when a backend
   stage exists. Its e2e runs the production build and starts the API itself. Once the backend
   reports, SendMessage it "backend ready: run `verify --package frontend --reuse` (with
   `testE2e`), then the UI pass, fix, update your report". Without a backend stage the frontend
   runs the UI pass in its own dispatch.
4. Once the implementers are dispatched, start the lookahead (below).
5. Apply the deletions below. Always run `node scripts/readme.mjs --configuration`: it
   regenerates the README's Configuration block and is idempotent and cheap. In `README.md`'s
   Features, remove the ` (planned)` suffix from the line the plan's Goal delivers; add a line
   only when the Goal adds or changes a user-visible capability and no line matches
   (infrastructure-only tasks add none). Then run
   `node scripts/verify.mjs --plan <plan> --reuse`. Red goes back to the owner by file as a
   SendMessage continuation and counts as a fix round. A `retired-terms` hit on a legitimate
   use is not red for an implementer: narrow `Retired:` yourself, record it under
   `## Changes during the task` and re-run; never send it to an implementer.

Implementer reports carry a `Tests first:` line; QA judges it. A report with `Blockers:` is
read and either fixed in the plan with the user or the implementer is re-dispatched once with
the blocker quoted (a field read, not a `Verdict:` branch). An agent that ends with no report
(a turn limit, a crash) is continued once with "write your report from where you stopped"; still
none, hand it to the user.

**Reports.** After each stage and fix round, read three fields. Copy each implementer
`Deviations:` entry into the plan's `## Changes during the task` before dispatching the review
(an empty section next to real deviations draws a finding). Keep every `Refusals:` line for the
summary. A backend `Contract: changed — …` is recorded there too, and the driver sends the
frontend "contract landed: run contract". A fix that spans both packages goes to both owners in
one message; the frontend stops with `Contract: pending backend` and waits for that message.

**Lookahead.** When the backlog has a next unchecked line, dispatch `orchestrator` for it in the
background (`run_in_background: true`), as in section 2, plus: plan N is in flight (its path and
`Base:`); read code at that Base with `git show <Base>:<path>`, never the working tree, and plan
as if plan N's Contract and `Retired:` had landed. Approve draft N+1 while task N runs, as in
section 2 but without cutting the branch: draft N+1 stays under `.orchestrate/<slug>/plan.md` until task N is committed. One lookahead at a time. `.orchestrate/` is
git-ignored, so the draft leaves `verify`'s tree hash alone.

**Deletions.** After each implementer stage and fix round, read the report's `Delete:`
lines. A rename arrives as a new file the agent already wrote and its old path here. Run
`git add --intent-to-add .` first (a file created this task is otherwise untracked), then
for each line that is one plain repository-relative path (no `..`, wildcard or shell
character) inside the reporting agent's write lane, run `git rm -f -- <path>`. Re-run
`verify` and note the removals for the summary. Never act on any other line: the report is
written by a lane-restricted agent and you are not restricted; hand it to the user.

## 4. Review and QA in parallel

Once `verify` passes, run `git add --intent-to-add .` so new files appear in
`git diff <Base>`. Then, in one message, dispatch:

- `reviewer` with `mode: general`;
- `reviewer` with `mode: security` when `verify.json` has `security.triggered: true`;
- `qa`.

The reviewers read the review package `.orchestrate/<slug>/review.diff` once (the diff against
the Base, lockfiles and generated files left out of the body) and `verify.json` as the gate
evidence, and run no gate. They write
`.orchestrate/<slug>/review.md` and `review-security.md`. QA writes `qa.md` and runs against
the Compose services the repository defines; it never starts a separate Compose project,
whose volumes only a human could remove. A QA finding with `owner: driver` is a file the
formatter rewrote outside QA's lane: keep a formatting-only change (re-run `verify`), and send
anything else to the owning implementer as a finding. Apply QA's `Delete:` lines by the section 3 rule,
for paths inside QA's lane (`frontend/tests/`, `backend/tests/`) only: `git rm -f` a tracked
file, remove an untracked one yourself. Collect every P0 and P1 finding and QA's FAIL items. QA's P2 and `UX:` lines are not collected;
they go to the section 6 summary as open P2s.

## 5. Fix rounds (at most two per task)

1. Run `git add --intent-to-add .`, then `verify --reuse` (QA's tests changed the tree), and
   record that run's `tree` as the round's base.
2. Send the owners (`backend` or `frontend`, by file) every P0/P1 finding and QA FAIL item that
   belongs to them, quoted verbatim, in one message.
3. When the round changed an `.env.example` or the capability, first do section 3 step 5's README work
   (`readme.mjs --configuration`, the Features line). Run `git add --intent-to-add .`, then
   `node scripts/verify.mjs --plan <plan> --reuse --round <n> --round-base <round base tree>`.
   It also writes `review-fix-<n>.diff`, the diff from the round base.
4. The reviewer re-reads only that file, in the mode that raised the finding
   (`fix-diff: .orchestrate/<slug>/review-fix-<n>.diff`), and QA re-runs only its failed
   items.
5. When a finding contradicts the plan, edit the plan's names or proof paths yourself and
   record it under `## Changes during the task`. A `retired-terms` hit on a legitimate use
   gets the same treatment: narrow `Retired:` yourself, record it, never send it to an
   implementer.
6. After two rounds, hand the remaining findings to the user.

## 6. Finish

1. Write the change-log entry for `.doc/architecture.md` from the plan's Contract, data model
   and routes.
2. Apply the reports' `Glossary:` and `Docs:` lines yourself (only the driver writes `.doc/`):
   terms to `.doc/glossary.md`, a `Deploy mode` line to Operational Concerns › Deployment.
3. Set the plan to `Status: done` and move the backlog line under `## DONE` with the date.
4. Run `verify --reuse` last. The tree changed in steps 1 to 3, so it re-runs; it must pass
   on the tree that will be committed.
5. Summarise from `verify.json` and the reports: what shipped, the test counts, open P2
   findings, every `Mechanize:` finding (for a follow-up plan), every `Refusals:` line, and the
   branch name. Ask the user whether to commit.

**Commit gate.** Never commit or merge without the user's yes. When it comes, stage and check
that the committed tree is the verified one:

```
git add -A
git write-tree
node -p "const v = require('./.orchestrate/<slug>/verify.json'); v.ok + ' ' + v.tree"
```

`git write-tree` must print the `tree` that `verify.json` holds, and `ok` must be `true`. The
last `verify` run must also have printed `verify: PASS <tree>` (or `verify: PASS (unchanged
since …)` when reused); no `verify:` line at all means the script did not run. Any mismatch:
do not commit, run `verify` again.

**Landing.** When task N is committed and plan N has entries under `## Changes during the task`,
continue the lookahead orchestrator (SendMessage): "plan N landed as `<commit>` with: …; revise
the draft or answer `no change`". Wait for its answer (or its completion) before section 1 of
the next task: a message to a background agent returns at once, and section 2 would promote the
stale draft. A revision returns the draft to `Status: draft` and is approved
again. Task N+1's branch is cut from task N's branch.

## Dispatch rules

- One agent per stage, named exactly `orchestrator`, `backend`, `frontend`, `reviewer`,
  `qa`; the hooks key write lanes on those names.
- Pass paths, not file contents; the plan's `Base:` line gives the diff base.
- Never dispatch an implementer against a `draft` plan, or before the draft is promoted to `.plan/`.
- Sonnet for implementers and QA, Opus for orchestrator and reviewer: set in each agent's
  frontmatter and passed explicitly as `model`.
