# Settled e2e test does not race its timers

Status: done
Approval: delegated (2026-10-31, "continue by completing smaller tasks and merging them to dev")
Owner:
Last updated: 2026-10-31
Branch: fix/settled-test-timers
Base: 84c8718ce0e7213fba53eba0eacf4082acb44116
Stages: frontend, qa
Retired: none

## Goal

`frontend/tests/e2e/settled.spec.ts` stops failing under load, so a red full e2e run means a real failure. QA reproduced 12 and 15 failures in 240 runs at 16 workers on plan 006's tree, all in one test. `settled` is not at fault: the spec's own wall-clock timers race it.

## Scope

- In: `frontend/tests/e2e/settled.spec.ts`, with no wall-clock timer left in it.
- Out: `settled` itself; the unexplained `vite preview` death, which `verify keeps the web server's output when e2e fails` serves.

## Assumptions

- `settled` cannot wait for a transition that has not started (`frontend/tests/e2e/support.ts`), and reversing a fade at 25% shortens the fade down to about 100 ms, so it ends just as the spec's second 100 ms timer fires. If that timer lands late, `settled` has already returned.
- A transition at `playbackRate` 0 stays `running` until cancelled, so the spec holds it instead of timing it.
- `settled` starts first and the test then cancels the held fade from a second `evaluate`. The other order still passes and proves less on that run; it can never fail a correct `settled`.

## Open Questions

None.

## UX

No route changes.

## Steps

### Frontend

1. `frontend/tests/e2e/settled.spec.ts` — a helper that takes a computed style, starts the fade, seeks it mid-way and holds it; the cancelled-replacement and removed-element tests drive it with no timer. The `forwards` test has no timer and stays as it is.

## Validation

- V01 — A correct `settled` survives the load that failed before: 0 failures of 240 (AC01) — proof: `bun run test:e2e tests/e2e/settled.spec.ts --project=phone --repeat-each=80 --workers=16`, with `E2E_BASE_URL` set so no web server starts
- V02 — The spec still fails a broken `settled`: `Promise.all` in place of `allSettled`, and one batch in place of the loop, each turn the cancelled-replacement test red (AC01) — proof: the same command against each temporary edit of `frontend/tests/e2e/support.ts`, reverted
- V03 — Every gate and the e2e suite pass with no network and no API key (AC01) — proof: `node scripts/verify.mjs --plan <plan> --reuse`

## Risks

- A fix that only widened the timers would hide the race and lose nothing visible, so V02 holds the spec to its purpose.

## Changes during the task

- Red first: the old spec failed 11 of 240 at 16 workers on this Base, 9 at `running` and 2 at `opacity` (`0.52`, `0.54`), the two sites QA named. With the held fade, 240 of 240 passed under the same command (V01).
- V02: against the fixed spec, `Promise.all` in place of `allSettled` failed 8 of 12 and one batch in place of the loop failed 4 of 12, on `frontend/tests/e2e/support.ts` edits that were reverted.
- The cancelled-replacement test now ends at opacity `0.5`: one retarget proves the loop, and a second would only add a transition to hold.
- The driver made this change itself, with one reviewer and no `frontend` or `qa` agent, because the user is at 92% of their weekly usage. V01 and V02 are the driver's own runs.
