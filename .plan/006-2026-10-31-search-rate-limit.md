# Search is rate limited per user

Status: done
Approval: delegated (2026-10-31, "5 per minute, approved")
Owner:
Last updated: 2026-10-31
Branch: feat/search-rate-limit
Base: d9e2dff9d98f8215fef492d644f48fba20c4f1ae
Stages: backend, frontend, qa
Retired: none

## Goal

A signed-in user can run a bounded number of searches in a window, so one account can no longer spend Voyage money without limit, and a user over the limit is told to wait rather than that the page failed. At 5 a minute one account also cannot queue other requests past the pool's acquire wait on its own, by arithmetic on the limit, the statement limit and the pool, which no test pins. No acceptance criterion asks for this: it answers Question 2 of plan 005, and AC01 and AC03 stay green.

## Scope

- In:
  - One `RATE_LIMITS` entry and the existing `rate_limit` with `by_caller` on `GET /api/search`, refusing before any call to Voyage and before any pooled connection.
  - The 429 in the contract and the generated client.
  - A `rate_limited` state on `/search`, and no search the user did not ask for.
- Out:
  - A bound on total spend: open sign-up multiplies a per-user limit (Risks). Proposed: `- [ ] search has a global spend cap`.
  - A bound across accounts on the pool: many accounts still reach the review's residual (Risks), and that takes a cap on concurrent searches in `search_ready_chunks`, not a rate limit. Proposed: `- [ ] concurrent searches are capped below the pool size`.
  - A limit per address: `by_ip` needs `TRUST_PROXY`, whose production value is still a `FILL` in `.doc/architecture.md › Operational Concerns`, and behind an untrusted proxy every user shares one bucket.
  - The agent's searches: the limiter sits on the route, so `search_knowledge_base` is not limited here, and `agent searches the knowledge base through our MCP server` must bound its own calls when it is planned.
  - Showing the wait from `Retry-After`: `call` exposes no headers, and the value is only an upper bound.

## Assumptions

- The scope is the user's answer to plan 005's Question 2 (2026-10-31): the existing `rate_limit` with `by_caller`, one `RATE_LIMITS` entry and its tests.
- Gates run `require_auth`, then the limiter, as in `api/conversation/routes.py` and `api/run/routes.py`; every authenticated attempt counts, a 400 and a 503 included, because the gate runs before validation and the handler (`middleware/rate_limit.py`), and no role is exempt; neither gate reads the database, so a refused search holds no connection.
- `by_caller` keys on the token's subject, not the client address, so the open `TRUST_PROXY` marker does not block this task.
- `(site)/error.tsx` says the page could not be loaded and to refresh, which is false while the limit lasts, so `/search` takes a segment `error.tsx` (`frontend/AGENTS.md`: only when a segment needs its own copy). It replaces the page and form as the accepted 503 does, which loses nothing while no search can run, and it keeps retry: a suspense query that failed is not asked again on remount (`ensurePreventErrorBoundaryRetry`), so leaving the state drops it, the retry or a reload clears it, and a refused retry neither calls Voyage nor moves the window's expiry (`MemoryStore.increment`).
- No client path retries a failed search: `main.tsx` sets `retry: false`, and the boundary unmounts the query's only observer. A search that succeeded does refetch once stale, on mount, focus and reconnect (query-core's `shouldFetchOn`), so Back to an earlier text, a return to the tab and a dropped connection would each re-embed it and spend the limit; `staleTime: Infinity` on the search's query stops all three, and a reload still asks.
- `measure_search.py` calls the rule and `live_retrieval.py` calls Voyage directly, neither the route. No e2e account sends more than 5 searches (the journey 5, `/search-result` 3 per project, `/search` none) against 100 times the limit at `RATE_LIMIT_SCALE=100`, and under `E2E_BASE_URL` none runs, so neither meets the limit.

## Open Questions

1. What is the limit? The count sets spend and friction; the window sets how much of it can arrive at once, and plan 005's security review leaves that to this task: at 3 s each the pool turns over about 3.3 slow searches a second. 6 a minute is at most 8,640 searches a day, about $0.18 a day for one account against Question 2's $1.80 and about 135 days of the free tokens; at most 12 pass across a window boundary, which the pool clears in about 3 s, and a caller over it waits up to a minute. 60 per 15 minutes, the siblings' window and this draft's earlier recommendation, is $0.12 and 200 days, but one account can pace its 60 above the turnover for 18 s, 36 s across a boundary, and a caller over it waits up to 15 minutes. 4 a minute spends the same $0.12, and a person refining a query reaches it; 10 a minute or more lets one account queue others past the 5 s acquire wait across a boundary. Recommended: 6 per minute: the 15-minute window was convention, and it is what lets one account fill the pool.
   > 5 per minute, window `1m` (2026-10-31, the user). At most 7,200 searches a day, about $0.15 a day for one account and about 163 days of the free tokens; at most 10 pass across a window boundary, which the pool holds at once, and a caller over it waits up to a minute.

## Contract

| Endpoint | Request | Response | Errors |
| --- | --- | --- | --- |
| `GET /api/search` | unchanged: `query.q`, `query.limit?` | unchanged: 200 `SearchResult` | 400, 401, 429 (`rate_limited`, with `Retry-After`), 503 (Voyage unreachable or limiting, the search passed its statement limit, or no pooled connection within 5 s) |

- Only the 429 is new. `Retry-After` is the window's length in seconds, an upper bound, as on every limit (`middleware/rate_limit.py`). A limited caller's rejected text is a 429, not a 400, because the gate runs first.

## UX

- /search — list — search the knowledge base — states: loading unchanged · empty unchanged · error the group's `ErrorState`, and for `rate_limited` a segment `ErrorState` saying to wait, with retry, each replacing the page and form inside the shell — tone: calm, dense, precise — phone: unchanged

## Steps

### Backend

1. `backend/src/app/config/constants.py` — `search_per_user` in `RateLimits` and `RATE_LIMITS`, the limit from Question 1, with its cost and its pool bound in a comment.
2. `backend/src/app/api/search/routes.py` — `search_limit` built above the table as in `api/run/routes.py`, gates `require_auth` then `search_limit`, 429 in `error_responses`.
3. `backend/tests/test_openapi.py`, `backend/openapi.json` — contract stage, with the two above: `TestTheDocument::test_documents_the_search_with_its_429`, shaped like `TestRunEventStream::test_documents_the_send_with_its_429`, then `contract`.
4. `backend/tests/test_search.py` — `TestRateLimit`, store-backed with `empty_store` and `fakes`, the proofs below, counted from `RATE_LIMITS.search_per_user`, never a literal; each caller holds one `headers`, because `member_bearer()` and `search_wire` mint a new caller per call, and the new window mints the same caller with `bearer(user_id)` from `tests/agent_support.py`, because an access token lives 15 minutes.
5. `backend/AGENTS.md` — the limit in `Search`, as `The agent` states the send's.

### Frontend

1. `frontend/src/shared/api/generated/` — `contract`, once the backend's contract stage has reported.
2. `frontend/src/entity/chunk/api/chunk.ts` — `staleTime: Infinity` on the search's query.
3. `frontend/src/app/(site)/search/error.tsx`, `frontend/src/app/(site)/error.tsx`, `frontend/src/app/routes.tsx` — the `search` route's `ErrorBoundary`: an `ActionError` with code `rate_limited` shows the segment's own copy, anything else renders `SiteError`; the group's retry is shared from `(site)/error.tsx`, not copied.
4. `frontend/tests/unit/search-routes.test.tsx` — the proofs below, through `stubApi` and `envelope`; V05's test moves `Date` past the freshness first, because a suspense query is fresh for its first second (`ensureSuspenseTimers`) and an unaged test passes on today's code; the two failure tests assert only `Try again`, which the segment also shows, so they gain the group's title; an e2e run sits at `RATE_LIMIT_SCALE=100`, so no journey reaches the limit, and the state has no screenshot, being the `ErrorState` pattern with other words.

### Driver

1. `.doc/architecture.md` — a Change Log entry with the limit, as the 2026-10-30 entry gives the send's and the stream's. `README.md` changes nothing: no capability and no variable.

## Validation

- V01 — Over `RATE_LIMITS.search_per_user.limit` one caller gets a 429 `rate_limited` with a positive `Retry-After` and a `requestId`, Voyage is called exactly `limit` times, and another caller still gets a 200 (AC03) — proof: `backend/tests/test_search.py::TestRateLimit::test_searches_over_the_per_user_limit_are_rate_limited`, `::test_a_limited_search_reaches_no_voyage_call`
- V02 — A rejected `q` counts, so `limit` 400s then a valid search is a 429; no token stays a 401 past the limit and counts nothing; a refused attempt leaves the window's expiry alone, and the same caller searches again in a new window (AC03) — proof: `backend/tests/test_search.py::TestRateLimit::test_a_rejected_text_counts_against_the_limit`, `::test_no_token_is_a_401_and_counts_nothing`, `::test_a_new_window_searches_again`
- V03 — `GET /api/search` documents its 429 and both generated results are fresh (AC01) — proof: `backend/tests/test_openapi.py::TestTheDocument::test_documents_the_search_with_its_429`, `verify`'s `contract-fresh` check
- V04 — At `/search` a `rate_limited` shows the segment's `ErrorState` after exactly one search, its retry sends one more and shows the hits, and any other failure still shows the group's title (AC03) — proof: `frontend/tests/unit/search-routes.test.tsx › the search route › asks a user over the limit to wait, and its retry searches again`, `› shows the group error state, with no server text, when the search fails`
- V05 — With a result's age past 30 s, window focus, reconnect and Back to its text each send no search (AC03) — proof: `frontend/tests/unit/search-routes.test.tsx › the search route › sends no search the user did not ask for`, with its red run on today's `chunk.ts`
- V06 — Every gate and the e2e suite pass with no network and no API key, `search.spec.ts` included (AC01) — proof: `node scripts/verify.mjs --plan <plan> --reuse`

## Risks

- The limit narrows the pool residual and does not close it: at 3 s each, ten pooled connections turn over about 3.3 slow searches a second, and a flood above that queues other requests past the 5 s acquire wait, so sign-in, chat and `/api/health/ready` answer 503 (plan 005's security review). A refused search holds no connection, and at 5 a minute one account alone cannot reach that, but four accounts can for a moment, because 20 slow searches landing together push the next request past the wait, and 40 accounts reach the turnover of 200 a minute, which holds it there. It needs slow searches, which take real scale: about 3 s for a word in 34,000 or more chunks of a source still indexing, about 1.7 s for a three-letter fragment with no match at 100,000 `ready` chunks — the `Out` cap on concurrent searches closes it.
- Open sign-up multiplies this limit: `register_per_ip` gives one address 960 accounts a day, so at 5 a minute spend reaches Question 2's $180 a day within two days, and 400 accounts reach Voyage's 2,000 requests a minute at tier 1, which turns every user's search into a 503 — the task bounds one account only, so the app must not be reachable from outside until both `Out` lines land, as plan 001 said of the send limit. The limit also counts searches, not tokens, so a 500-character text of costly characters spends more: $0.22 a day by `voyage.py`'s estimator and $0.43 at one token per code point, neither measured.
- The in-flight 503 plan 005 accepted counts: the gate runs first and the embedding runs before the statement that fails, so each retry while a very large source indexes spends one of the limit and pays Voyage, and the user then sees the wait instead of the failure — the cost sits inside the ceiling above, and that retry cannot succeed until the index ends either way.
- A kept result can be out of date: it stays until a reload or 5 minutes off screen, so a search run before a source turned `ready` keeps its answer on Back or a return to the tab — a reload asks again, and a result changes only when an index ends, while each ask costs money and a count.
- A fixed window can lock a heavy honest session out for up to one window, and lets twice the limit through across a boundary — Question 1 sets both; the `/search` state says to wait, and the daily ceiling holds.
- The count lives in process memory, so a restart clears it and a second replica doubles it — accepted, as for every limit here: `.doc/architecture.md › Operational Concerns` runs one instance until the cache task rebinds `services/cache.py`.

## Changes during the task
- Contract stage (backend report): `GET /api/search` documents a 429 `rate_limited`, `ErrorBody`, between its 401 and 500. No request or response schema, component or other path moved.
- Backend stage deviation (backend report): `TestRateLimit::test_an_admin_is_limited_like_a_member` is added, because the Assumptions say no role is exempt and no named test proved it. The gate landed in the contract stage, so `TestRateLimit` passed on its first run and its red runs come from mutating the gate, its order and key, and the window's expiry, each restored.
- Frontend stage (frontend report): V04 holds, so `Try again` after a render error works: a 429 then a 200 sends exactly two searches and brings back the hits and the form. The retry is `useSiteRetry`, a named export of `(site)/error.tsx`, and `frontend/AGENTS.md` gains the search's `staleTime` and the segment boundary.
- The backlog lines `search has a global spend cap` and `concurrent searches are capped below the pool size` went in on the user's yes at the commit gate (2026-10-31), beside `agent runs have a spend cap`, with `settled e2e test does not race its timers` at the top of the queue.
- Fix round 1, by the user's decision at the commit gate (2026-10-31): review's and QA's two P2s on the retry and the wait state, though neither is a P1, because both are in this task's new code.
- Fix round 1 deviations (frontend report): `useSiteRetry` navigates to the same URL with `replace` instead of calling `revalidate()`, on every `(site)` route. The filtered reset alone broke `Try again` in the browser: the old full reset also reset the cached session, which made the revalidation slow enough for the boundary to clear, and with it cached the boundary stays. `search-rate-limit.spec.ts` caught it, because React Testing Library's synchronous `act` hides it from a unit test. `(auth)/error.tsx` keeps its own reset and revalidate. `dropFailedSearch` lives in `entity/chunk/api/chunk.ts`, `tests/unit/support.tsx` gains `createAppClient()` and `render-routes.tsx` an optional `client`. The StrictMode test renders only the search route, because on React's development build StrictMode aborts the session read and sends a guarded route home (review's P2: since the bootstrap, not this task, and production is unaffected).
- Fix round 2 (2026-10-31): review raised a P1 on round 1. React Router treats a navigation to an equal non-empty hash as hash-only and runs no loader, so `Try again` was dead after a loader error on a URL with a hash, which the shell's skip link makes, and round 1 caused it. So the retry's target drops the hash, and a retry loses the fragment. The user's approval to commit stopped on this P1, so commit, push and merge need a fresh yes.
- Fix round 2 (frontend report): one retry test clicks outside React Testing Library's `act`, through `clickLikeABrowser` in `search-routes.test.tsx`, so it goes red on `revalidate()`; the others cannot. `frontend/AGENTS.md`'s segment note says a 503 is not dropped there, because the embedding may have been paid.
- `search-rate-limit-adversarial.test.tsx › sends one search per retry even when the retry is clicked twice at once` failed once in round 2's first gate run (expected 3 to be 2), then passed 19 runs, so about 1 in 21. Not from round 2: its URL has no hash. Review's round 2 settled it, and the frontend's reading was right: `userEvent.dblClick` awaits a real `setTimeout(0)`, so the first retry can finish between the clicks and the second is a real second retry. The test's premise was false. Review also found a real race that needs no second click: `dropFailedSearch` could delete the retry's own failure, so one click could send two searches. Those are two P1s, with a P0 for a stray `frontend/.vitest/` from the reviewer's `--reporter=json` runs.
- Fix round 3, past the loop's cap of two, by the user's yes (2026-10-31), for those two P1s only: `dropFailedSearch` takes the error the wait shows and drops only the query still holding it, compared by identity, so the retry's own newer failure stays. The double-click test sends both clicks in one tick and asserts the button is still there between them. `frontend/AGENTS.md`'s segment note changes the one phrase this made false. The P2s stay open.
- Round 3's first full `verify` failed e2e, 57 of 72, on tree `8ef0320`: `vite preview` on 5173 stopped a few seconds into the tests, shown by connection resets first, then refused connections, then timeouts. The cause is not found: `verify` keeps only the end of a step's output, so the server's stderr is lost, the Windows event log shows no crash, and three runs of the suite alone then passed 72 of 72.
- `verify` with nothing reused then passed on tree `cbcf393`, and review's round 3 closed both P1s with no new P0 or P1. The user read the unexplained failure at the commit gate and approved the commit (2026-10-31), with the backlog line `verify keeps the web server's output when e2e fails`, under `settled`.
- The backlog line `reloading a guarded route in development stays on that route` went in on the user's yes (2026-10-31), for the StrictMode session bug.
- The first review and QA raised no P0, P1 or FAIL; the fix rounds above came from its P2s, by the user's decision. QA added limit cases to `backend/tests/test_search_adversarial.py`, `frontend/tests/unit/search-rate-limit-adversarial.test.tsx` and `frontend/tests/e2e/search-rate-limit.spec.ts`, which reaches the limit on the real API with blank searches and captures the wait, so frontend step 4's "no journey reaches the limit" and "no screenshot" no longer hold. No reviewer read those three files.
- The driver corrected what review raised against the plan (2026-10-31): `$0.14` was the driver's sum when the answer moved to 5, and `$0.15` is the plan's own basis, in Question 1, `constants.py` and `backend/AGENTS.md`, each now saying it is no ceiling. The Goal's pool claim says it is arithmetic, and Risks now give the four-account moment and the cost of hostile text.
- `frontend/tests/e2e/settled.spec.ts` is flaky and not caused by this task: QA reproduced 12 and 15 failures in 240 runs at 16 workers, and one full run on this tree failed on it. It needs its own fix.
