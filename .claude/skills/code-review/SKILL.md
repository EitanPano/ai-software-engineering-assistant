---
name: code-review
description: Review a change against this repository's standards. Use when acting as the reviewer agent, when the user asks for a review of a branch or diff, or when deciding whether a stage is done. Covers the six-priority checklist, the P0/P1/P2 scale, what counts as evidence, and the report format.
---

# Code Review

One reviewer applies the whole checklist below (`mode: general`). `mode: security` deepens
priority 1 only; the driver adds it when `verify.json` has `security.triggered: true`. `verify`
computes that from the diff, `security.paths` lists the files that fired, and
`scripts/verify/security.mjs` holds the rule. Migrations and SQL do not trigger it; the general
reviewer covers the data model (priorities 1 and 2). A defect outside security found in
`mode: security` is still a finding, in the same report, at its own severity.

Be critical. Surface real problems and say them plainly; do not soften, do not pad with
praise. A review with no findings states what was checked and why it holds.

## What to read

The change is uncommitted. Inside the loop, `verify` prepared a review package,
`.orchestrate/<slug>/review.diff`: the working tree against the plan's `Base:` commit, with
the stat of every file and lockfiles and generated files left out of the body. Read it once,
paging through a long file until the last file in its stat;
open code outside it only for a named risk, one check per risk; never re-run the suites
(`verify.json` is the evidence). A `fix-diff: <path>` re-review reads only that file
(`review-fix-<n>.diff`). Outside the loop, read `git diff <Base>` (`main` unless the user
names a base) and `git status --short`. Never `git diff <Base>...HEAD`, which ignores the
working tree, and inside the loop never `git diff main`, which also shows earlier tasks
committed on the branch. Read the plan's Scope, Contract and Validation first, then the
diff, then what the change should have touched but did not (a migration or index, a
failure-path test, an error state, a change-log line).

## Priorities, highest first

1. **Security**: injection, auth and tenancy boundaries, secrets in code or logs, data
   exposure in responses, unsafe dependencies; in a data-model change, grants and roles,
   destructive statements and new personal-data columns. In `mode: security` go further: auth and
   session flows, authorization per endpoint, injection, secrets, CORS and proxy trust, the
   Compose and Docker surface (privileges, bind mounts, host networking, ports published
   beyond loopback).
2. **Scalability**: N+1 queries, missing indexes, unbounded lists, work on the request
   path that belongs in a job, state that cannot be replicated.
3. **Maintainability and architecture**: layering and import direction per `AGENTS.md` and
   `backend/AGENTS.md`, naming, duplication, a feature that reaches into another, logic in
   the routing layer or in a `routes` file beyond declaring gates, validating and
   naming the handler (business logic belongs in the controller, its handlers and exported
   rules; queries in the service), a controller reaching another module's service, a
   service imported from outside its module.
   Is every new file in the home the `backend/AGENTS.md` table names for it (module file,
   `models/`, `middleware/`, `services/`, `services/utils/`, `infra/jobs/`,
   `infra/subscribers/`)? A file in two defensible homes is a finding.
   Frontend: layer direction (`app` → `widget` → `feature` → `entity` → `shared`, no sibling
   slice); no raw `button`, `input`, `select` or `textarea`, hex colour or palette class
   outside `shared/ui`; status never by colour alone; no `revalidatePath`; no limit copied
   from the backend into a form schema; every new file in the slice the frontend's
   `AGENTS.md` table names for it.
4. **Error handling and validation**: validation at the edge with the envelope, correct
   status codes, no swallowed errors, user-safe failure UX, logs with request id.
5. **Unnecessary complexity**: abstraction without a second caller (a controller function
   that only forwards to its service is the module's public API, not an abstraction to
   remove), configuration no one reads, dead code, cleverness that a comment has to
   explain.
6. **Deployment and operations**: data change shipped with its migration or index, env variable in
   the package's env module (named in its `AGENTS.md`) and `.env.example`, Docker build still
   valid, change log updated. A change whose plan Goal adds or changes a user-visible capability
   has its Features line in `README.md` with the ` (planned)` suffix removed (or added as a new
   line), and the README's Configuration block matches the
   `.env.example` files (the full `verify` run enforces the latter).

## Severity

- **P0**: must fix before the stage is done. A security hole, data loss, a broken gate,
  a contract that drifted, a lane or rule violated.
- **P1**: fix in this task. Wrong layering, missing failure-path test, misleading name,
  error leaking internals.
- **P2**: note for later. Style, minor duplication, a better library call. A finding class
  that an earlier task's `.orchestrate/*/review.md` already shows is tagged `Mechanize:` and
  filed with the check that would catch it; the driver lists those for a follow-up plan.

## Evidence

`verify`'s `retired-terms` check covers the plan's `Retired:` strings, so flag a leftover old
name only when the list missed it.

Every finding names `file:line`, quotes the problem in one line, states the consequence,
and gives the fix. "Looks wrong" is not a finding; run the test or read the schema when
in doubt. `.orchestrate/<slug>/verify.json` is the gate evidence (and QA's report, when it exists): do
not re-run `check`, `test`, `typecheck` or `lint`. To confirm one
finding, run at most the one test file that covers it. Never run `testDb` (it writes the test
database), a dev server, `format` or anything that writes.

## Report

Write `.orchestrate/<slug>/review.md` (`review-security.md` for `mode: security`). `Verdict`
is informational: `fail` when any P0 or P1 remains, otherwise `pass`; the loop branches on the
findings.

```
Stage: <review | review:security>
Task: <slug>
Verdict: <pass | fail>

## Findings
- P0 — <file:line> — <problem> — <consequence> — Fix: <what to change>
- P1 — …
- P2 — … (`Mechanize: <check that would catch it>` when the class repeats)

## Checked and holds
- <what was examined and found correct, one line each>

Refusals: <command — the hook's reason, one per line | none>
```

A `fix-diff:` re-review rewrites the file with the earlier content kept and a new
`## Re-review <n>` section at the end (you have Write, not Edit).

The dev loop re-dispatches the implementer with the P0 and P1 lines verbatim, so each
must be self-contained.
