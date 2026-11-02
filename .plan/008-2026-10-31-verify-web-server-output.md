# Verify keeps the web server's output when e2e fails

Status: done
Approval: delegated (2026-10-31, "continue by completing smaller tasks and merging them to dev")
Owner:
Last updated: 2026-10-31
Branch: fix/verify-web-server-output
Base: 913a3898ce667ef950cd69414328cd00c756ac0f
Stages: frontend, qa
Retired: none

## Goal

When e2e fails, `verify.json`'s `log` for `testE2e` holds what each web server last printed. `vite preview` died mid-run on tree `8ef0320` (plan 006) and the cause was never found, because `verify` keeps the last 80 lines of a failed step and a failing suite prints far more.

## Scope

- In: a Playwright reporter in the frontend package that prints each web server's last lines after the summary; a name per web server; the preview server's stdout.
- Out: `scripts/verify/`, because a local edit there makes `harness-update` refuse until `--overwrite`, which would drop it. The cause of the `vite preview` death: this makes the next one readable.

## Assumptions

- Playwright hands a web server's output to reporters with no test and with a `[name] ` prefix per line, and `onEnd` runs in reporter order, so a reporter listed after `list` prints last.
- Keeping `verify`'s tail is enough: the lines printed last are in it, so `verify` needs no change.
- The API logs far more than the preview server, so the limit is per server. Only the preview server's stdout is piped, which keeps the API's noise out of the run's output.

## Open Questions

None.

## UX

No route changes.

## Steps

### Frontend

1. `frontend/scripts/web-server-tail.ts`, `frontend/tests/unit/web-server-tail.test.ts` — the reporter and its unit tests.
2. `frontend/playwright.config.ts` — the reporter after `list`, a `name` on each web server, `stdout: 'pipe'` on `preview`.
3. `frontend/AGENTS.md › Tests` — what a failed run prints, and its limit.

## Validation

- V01 — After a failed run each server's last lines print, limited per server; a passed run, a run with no web server and a test's own output print nothing (AC01) — proof: `frontend/tests/unit/web-server-tail.test.ts`
- V02 — A real failing run through the real web servers shows `[preview]` lines in the last 80 lines of its output, the part `verify` keeps (AC01) — proof: a temporary failing spec, recorded under `Changes during the task` and removed
- V03 — Every gate and the e2e suite pass with no network and no API key (AC01) — proof: `node scripts/verify.mjs --plan <plan> --reuse`

## Risks

- A server killed from outside writes nothing, so its absence from the tail is the only sign, and no exit code is recorded; a process that wrote its last words before the tail limit is lost. Both are accepted: the case this serves is a server that said why it died.

## Changes during the task

- Red first: `web-server-tail.test.ts` failed on the missing module, then passed with the reporter.
- V02: 30 failing tests through the real web servers printed 922 lines. `tail` from `scripts/verify/summary.mjs` kept 79 of them, with 12 `[preview]`, 5 `[api]` and 4 lines each for `anthropic`, `github` and `voyage`; `parseSummary` still counted 30 failed. The temporary spec is removed.
- The driver made this change itself, with one reviewer and no `frontend` or `qa` agent, because the user is at 92% of their weekly usage. V02 is the driver's own run.
