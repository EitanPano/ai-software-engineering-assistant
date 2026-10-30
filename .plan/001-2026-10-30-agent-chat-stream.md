# User can chat with the agent and watch the response stream

Status: done
Approval: delegated (2026-10-30, "approve with both changes, questions as recommended, add the backlog lines")
Owner:
Last updated: 2026-10-30
Branch: feat/agent-chat-stream
Base: 5cd597ae95bd639aebfb3d4d24b7ba18f7e57dba
Stages: backend, frontend, qa
Retired: none

## Goal

A signed-in user can start a conversation, send a message and watch the agent's answer arrive as it is written, with each tool call's start and result in place; a client that drops or reloads catches up in order, once each. This satisfies AC02 and keeps AC01 green, and it ships the hand-written loop, the `run` and `run_event` store and the stream every later task builds on.

## Scope

- In:
  - Start, list and open the caller's conversations, and send a message, limited per user, which a background task executes as a `run` on the hand-written loop.
  - Every step stored as a `run_event` and streamed over SSE, with replay from `Last-Event-ID`.
  - The loop's tool path behind a default-deny seam, and recovery of a run the process lost.
- Out:
  - Tasks 2 to 10 of the backlog and their tables: `tool_call`, `tool_policy`, `mcp_server`, `approval`, `memory`.
  - `- [ ] drop the reference module`
  - `- [ ] user can delete a conversation`
  - `- [ ] user can stop a running agent`
  - `- [ ] user can load earlier messages in a conversation`
  - `- [ ] user can see a finished run's tool calls after a reload`
  - `- [ ] agent runs have a spend cap`

## Assumptions

- `.doc/conventions.md › Claude API` holds as written. This plan's own choices, which the backend stage confirms against the installed SDK before building on them: `anthropic>=2.3,<3`, `client.beta.messages.stream`, `fallbacks: "default"`, `thinking` omitted, `effort: high`, `max_tokens: 64000`, top-level `cache_control`.
- `conversation` owns `conversation` and `message`, `run` owns `run` and `run_event`, `agent` has no table or route; `agent` imports both and `conversation` imports `run`, so a run starts through `RUN_CREATED`, never a direct call.
- One active run per conversation, enforced by a partial unique index: a second send is a 409 through `classify_postgres_error`; queueing is not in scope.
- The SSE endpoint polls `run_event` every 100 ms, taking a connection per query, and deltas flush every 50 ms: `.doc/architecture.md` item 8 makes Postgres the channel and one replica keeps the load small, so no LISTEN/NOTIFY.
- `message` is one row per API turn, `role` `user`, `assistant` or `tool_result` (sent as `user`); the wire shows text only, and thinking, `tool_use` and `tool_result` blocks stay on the server.
- With one replica, a lost run is one started before this process booted, so one sweep at boot finds them all, with no job, no dependence on `JOBS_ENABLED` and no heartbeat a slow model turn could trip; a failed sweep is logged and the boot continues, like a failed job. The bus cancels a live run 1 s into shutdown, and the next boot's sweep catches what it leaves.

## Open Questions

1. Which tools does the first run offer? MCP (tasks 5, 7) and `tool_policy` (task 6) do not exist, and `.doc/conventions.md` denies a tool with no policy. A: offer the real model none; the fake scripts a `tool_use`, the default-deny seam answers it, and AC02 is proven end to end, but no live user sees a tool call until task 5. B: ship one read-only built-in with a hard-coded allow, visible live, at the price of a policy bypass task 6 must remove. Recommended: A.
   > A: offer the real model no tools; the scripted fake proves AC02's tool-call display.
2. Where does the scripted Anthropic fake sit? A: an HTTP fake in `backend/tests/` reached through `ANTHROPIC_BASE_URL`: the SDK's real stream handling runs and nothing test-only ships, at the price of a third Playwright server and a wire-format fixture to maintain. B: `LLM_PROVIDER=scripted` in `services/`, like `MAIL_PROVIDER`: one process fewer, but a fake in the production image and no SDK parsing in e2e. Recommended: A, with `ANTHROPIC_BASE_URL` refused in production.
   > A: an HTTP fake in `backend/tests/`, with `ANTHROPIC_BASE_URL` refused in production.
3. Drop the reference `module` now? `backend/AGENTS.md › Adding a module` says to once a real module exists, but that rewrites `tests/test_store.py`, `tests/db/test_postgres.py` and `tests/test_openapi.py`, removes `tests/test_module.py` (468 lines), and needs `backend/AGENTS.md` rewritten because `retired-terms` scans it; none of it serves AC02. The cost of waiting is a public, unused `GET /api/module`. Recommended: keep it here and take the `Out` line as the next backlog task.
   > Keep it here; `drop the reference module` is the next backlog task.

## Contract

| Endpoint | Request | Response | Errors |
| --- | --- | --- | --- |
| `POST /api/conversation` | none | 201 `Conversation { id, title: string \| null, createdAt, updatedAt }` | 401 |
| `GET /api/conversation` | `query.cursor?`, `query.limit?` | 200 `ConversationPage { items: Conversation[], nextCursor }`, latest activity first | 400, 401 |
| `GET /api/conversation/{id}` | `params.id` | 200 `ConversationDetail { ...Conversation, latestRun: Run \| null }` | 401, 404 |
| `GET /api/conversation/{id}/message` | `params.id`, `query.cursor?`, `query.limit?` | 200 `MessagePage { items: Message[], nextCursor }`, newest first | 400, 401, 404 |
| `POST /api/conversation/{id}/message` | `params.id`, `body.content: string` (1 to 32000 characters) | 201 `SentMessage { message: Message, run: Run }` | 400, 401, 404, 409, 429 |
| `GET /api/run/{id}/event` | `params.id`, header `Last-Event-ID?: integer >= 0` | 200 `text/event-stream` of `RunEvent`; each SSE `id` is the event's `sequence`; closes after `run_finished` or at 60 s | 400, 401, 404, 429 |

- `Message { id, role: user | assistant, text, runId, createdAt }`.
- `Run { id, status: queued | running | completed | failed, errorCode: refused | truncated | turn_limit | upstream_unavailable | interrupted | internal | null, createdAt }`.
- `RunEvent`, a union on `type`, each with `sequence` and `createdAt`: `run_started`; `text_delta { text }`; `tool_call_started { toolUseId, name, input }`; `tool_call_finished { toolUseId, status: succeeded | failed | denied, output: string }`; `run_finished { status: completed | failed, errorCode }`.

## UX

- /conversation — list — start a conversation — states: loading `ListSkeleton` · empty `EmptyState` with the start action · error the group's `ErrorState` — tone: calm, dense, precise — phone: one column, the action in `PageHeader`
- /conversation/:id — detail — send a message — states: loading `CardSkeleton` · empty `EmptyState` above the send form · error the group's `ErrorState`; a failed run is an inline alert with copy per `errorCode` and the form stays enabled — tone: calm, dense, precise — phone: one column, the send form sticky at the bottom

## Steps

### Backend

1. `backend/pyproject.toml`, `backend/uv.lock` — add `anthropic>=2.3,<3` (named in `.doc/conventions.md`); both `ignore_imports` lists that name `send_welcome` gain the new subscriber and the boot sweep's import.
2. `backend/src/app/config/env.py`, `config/constants.py`, `backend/.env.example`, `docker-compose.yml` — `ANTHROPIC_API_KEY` (in `_SECRET_NAMES`, no `sk-ant-` shaped placeholder), `LLM_MODEL`, `ANTHROPIC_BASE_URL` (refused in production), on both backend services; `AGENT_*` constants for the system prompt, effort, token and turn limits, flush and poll intervals; `RATE_LIMITS.message_per_user`, 30 per 15 min.
3. `backend/src/app/infra/migrations/0002-conversation.sql` — `conversation`, `message`, `run`, `run_event` per `.doc/architecture.md`, plus `run.user_id`, `run.error_code`, a partial unique index on active runs, unique `(run_id, sequence)` and the paging indexes.
4. `backend/src/app/services/anthropic.py` — the only importer of the SDK: builds the request, yields text deltas, returns stop reason, usage and content as JSON blocks; not a `Resource`, so readiness never depends on Anthropic.
5. `backend/src/app/services/tool.py` — `Tool` definitions (`strict`, `eager_input_streaming`, an input validator), `register_tool`, sorted definitions and `decide`, which denies anything not registered as allowed; empty in production.
6. `backend/src/app/models/conversation/`, `models/run/`, `api/conversation/`, `middleware/rate_limit.py` — the Contract's conversation rows; rules to read history and to append an assistant turn with its `tool_result` turn in one transaction; sending claims the `run`, stores the message, sets the title, publishes `RUN_CREATED`, and fails the run if the insert fails; a `by_caller` key limits the send, with `require_auth` declared before this limiter because the key needs the caller.
7. `backend/src/app/api/run/` — the Contract's stream, polling until `run_finished`; rules to create a run, append events through one per-run writer, finish a run and fail lost runs.
8. `backend/src/app/api/agent/controller.py` — `execute_run`, a system operation: the loop branches on `stop_reason` before reading content, runs parallel calls concurrently, validates input, stops at the turn limit and writes one `run_finished` on every exit, after the message commits; requests echo stored blocks unchanged except what the API omits before a `fallback` block, and tools run only from blocks after it.
9. `backend/src/app/services/event.py`, `infra/subscribers/execute_run.py`, `infra/pubsub.py`, `infra/dependency.py`, `main.py` — `RUN_CREATED` and its subscriber; `main.py`'s lifespan calls a sweep in `infra/dependency.py` (the only infra module it may import) once every resource is connected, before uvicorn binds the port, failing as `interrupted` the runs started before this process booted and writing each one's `run_finished`.
10. `backend/src/app/openapi.py`, `config/routes.py`, `middleware/error_handler.py`, `backend/openapi.json` — the mounts, the `COMPONENTS` names, `shape_document` rewriting `itemSchema` to `schema`, `header` in `_PARTS`, then `contract`.
11. `backend/tests/` — `fake_anthropic.py`, an ASGI fake of `POST /v1/messages` on the SSE wire format, scripted and gated by markers in the user's message so parallel journeys stay apart, served on 8101 by `python -m tests.fake_anthropic` for e2e; `test_conversation.py`, `test_run.py`, `test_agent.py` (`store_backed`), `services/test_anthropic.py`, `services/test_tool.py`, `test_openapi.py`.

### Frontend

1. `frontend/package.json`, `frontend/bun.lock`, `frontend/src/shared/ui/markdown.tsx` — `react-markdown` and `remark-gfm` (reason: `.doc/conventions.md › Agent security` requires sanitised Markdown, and these drop raw HTML), one renderer; then `contract`.
2. `frontend/src/entity/conversation/`, `entity/message/` — types, query options, rows.
3. `frontend/src/entity/run/` — `model.ts` (a reducer that ignores a `sequence` already seen, the `errorCode` copy), `api/run.ts` (the stream, reopening with `Last-Event-ID` until `run_finished`, bounded on consecutive failures), `ui/` (status badge, tool-call row with input and output as plain text).
4. `frontend/src/feature/start-conversation/`, `feature/send-message/` — mutations, the form schema from the generated body, a copy table with `conflict` and `rate_limited`.
5. `frontend/src/widget/conversation-list/`, `widget/conversation-history/` — sections and skeletons; the history is `role="log"`, announces a finished answer rather than each delta, and follows `latestRun` on load.
6. `frontend/src/app/(site)/conversation/page.tsx`, `(site)/conversation/[id]/page.tsx`, `app/routes.tsx`, `app/nav.ts` — both routes behind `requireAccount`.
7. `frontend/playwright.config.ts`, `frontend/tests/` — a third web server for the fake and `ANTHROPIC_BASE_URL` for the API; unit tests for the above; `e2e/conversation.spec.ts`, left out at collection under `E2E_BASE_URL` because that stack has no fake (noted in `frontend/AGENTS.md › Tests`); `screens.spec.ts` captures `/conversation` and one created conversation as `conversation-detail`.

### Driver

1. `.github/workflows/ci.yml`, outside both agents' lanes — add `ANTHROPIC_API_KEY` to the `image` job's generated secrets, or the production image refuses to boot; `.doc/glossary.md`, `.doc/architecture.md` — actions `start` and `send`, the `message` roles, `ANTHROPIC_BASE_URL`.

## Validation

- V01 — A signed-in user reads the answer's first part while the fake holds the rest, then the whole answer as rendered Markdown, and it survives a reload (AC02) — proof: `frontend/tests/e2e/conversation.spec.ts › streams the answer as it is written`
- V02 — A scripted `tool_use` shows its start and then its result; an unregistered tool is denied and never executes; a registered one runs, parallel calls return in one user message, and an input that fails validation is an `is_error` result (AC02) — proof: `frontend/tests/e2e/conversation.spec.ts › shows a tool call's start and result`, `backend/tests/test_agent.py::TestTools`
- V03 — `Last-Event-ID: N`, during and after a run, returns exactly the events after N, in order and once each, and `run_started` is readable before the fake answers (AC02) — proof: `backend/tests/test_run.py::TestReplay`
- V04 — A stream dropped or cleanly closed before `run_finished` reopens with `Last-Event-ID` and renders each event once, and a reload mid-run restores the text (AC02) — proof: `frontend/tests/unit/run-stream.test.ts`, `frontend/tests/e2e/conversation.spec.ts › catches up after a reload mid-run`
- V05 — Each `stop_reason`, a stream failure and a lost process end the run with exactly one `run_finished`, stored history replays unchanged, and every stored `tool_use` has its result (AC02) — proof: `backend/tests/test_agent.py::TestStopReason`, `backend/tests/test_agent.py::TestScripts`, `backend/tests/test_run.py::TestRecovery`, `frontend/tests/e2e/conversation.spec.ts › reports a failed run`
- V06 — No token answers 401, another user's conversation or run 404, a bad `Last-Event-ID` 400, a send during an active run 409 and a send over the per-user limit 429 with `Retry-After`, each with the envelope's `code` and `requestId` (AC02) — proof: `backend/tests/test_conversation.py::TestAccess`, `backend/tests/test_run.py::TestAccess`
- V07 — Raw HTML and `javascript:` links in assistant text stay inert (AC02) — proof: `frontend/tests/unit/markdown.test.tsx`
- V08 — Every gate and the e2e suite pass with no network and no API key, and the generated client types the stream as `RunEvent` (AC01) — proof: `node scripts/verify.mjs --plan <plan> --reuse`, `backend/tests/test_openapi.py::TestRunEventStream`

## Risks

- A generator endpoint's body runs after the 200 is sent, so a 404 raised there never reaches the client — authentication and ownership run as `Depends`, and the handler is annotated `AsyncIterable[RunEvent]`, with no `response_model`, so the item type reaches the contract.
- Hey API 0.99 ignores `itemSchema` and types the stream `unknown` (confirmed by generating both shapes), and its SSE client stops silently on a clean close and never resets its attempt count — `shape_document` rewrites the first, `tests/test_openapi.py` pins it, and `entity/run/api/run.ts` owns reconnection.
- Parallel tool calls could commit sequence N+1 before N, and a poller would then skip N for good — one per-run writer allocates and commits in order.
- Open sign-up with paid model calls: the send limit bounds one account's rate, not total spend, and new accounts multiply it — the `Out` spend-cap line ships before a public deployment.
- The fake can drift from the real wire format — the user sends one message with a real key before merge (under $0.05).
- A failed run has no final message, so a reload loses its partial text — accepted; its `run_event` rows keep it.

## Rollback

Revert the branch. `0002-conversation.sql` only adds tables, which the old code ignores; removing them deletes conversations, so that is a human's `drop table`, in the order `run_event`, `run`, `message`, `conversation`.

## Changes during the task

- Backend contract stage: `error_handler._PARTS` gained `"header"`, so a bad `Last-Event-ID` is a 400 `validation_failed` with the message `invalid header` (plan step 10).
- Backend contract stage: `shape_document` also turns the stream route's error entries from `text/event-stream` back to `application/json`; FastAPI puts the stream media type on them, which the plan did not foresee.
- Backend contract stage: the send's 429 is in the contract, and its gate (`RATE_LIMITS.message_per_user`, `by_caller`) lands with the implementation stage.
- Contract: `/api/conversation`, `/api/conversation/{id}`, `/api/conversation/{id}/message`, `/api/run/{id}/event` added to `backend/openapi.json`, with their components.
- Backend, test order: only the contract stage has a red run. The module, agent, recovery, tool, SDK-wrapper and env tests were written once the code compiled, so Definition of Done item 2 is not met as written for them; QA judges it.
- Backend: `message` gained a `text` column and an identity `position` column, for the ordering of a turn pair and the cursor; `run_event`'s primary key is `(run_id, sequence)`.
- Backend: each module service exposes `Tx` (an alias of `Executor`), because a controller cannot import the db seam.
- Backend: `pyproject.toml`'s import-linter lists gained the new subscriber and `infra/dependency -> api/run/controller`, in the layers, the "infra … import no api" and the independence contracts.
- Backend: a streamed `error` event surfaces as `APIStatusError` with status 200, so the wrapper also maps `overloaded_error` and `api_error` bodies to `upstream_unavailable`.
- Backend: the stored assistant turn stays complete; the request drops what precedes the last `fallback` block.
- Backend: the first Assumption's SDK choices are confirmed against `anthropic` 2.3.0.
- Frontend: `EmptyState` has no start button, unlike the UX section: the start action stays in `PageHeader` and the empty state points at it, because a second same-named button breaks the one-primary-action rule.
- Driver: `ANTHROPIC_API_KEY` added to the `image` job's generated secrets in `.github/workflows/ci.yml`.
- Frontend: a completed run stays on screen, with its stored turns hidden, until the next send or a reload, because tool calls are not stored and its tool rows would otherwise vanish when it ends; the history's `aria-label` is "Conversation history", because "Messages" clashed with the "Message" field in Playwright's label locator.
- QA: `frontend/tests/e2e/shell.spec.ts`, a template spec, now waits for the `Account menu` button before counting touch targets, which fixes its race with the session probe; a harness update may overwrite it, and the upstream catalog spec has the same race.
- Driver, fix round 1: the conversation list's paging stays in this task rather than a backlog line, because Scope says "list and open the caller's conversations".
- Contract, fix round 1: `GET /api/run/{id}/event` gains a 429 `rate_limited` with `Retry-After`. `RATE_LIMITS.run_stream_per_user` is 60 per 15 min and `AGENT_STREAM_MAX_SECONDS` is 60: a stream ends with a clean close, and the frontend's `streamRun` does not count that as a failure, so a long silent turn is not reported lost.
- Backend, fix round 1: `httpx2>=2.16` declared in `backend/pyproject.toml`, because `services/anthropic.py` now catches `httpx2.TransportError`, which the SDK re-raises raw when a stream breaks mid-body.
- Backend, fix round 1: `block.to_dict(warnings=False)` in `services/anthropic.py`, because a non-object tool input makes pydantic warn on serialization and `filterwarnings = error` fails it; an empty `end_turn`, `stop_sequence` or `pause_turn` turn is not stored and fails the run as `internal`.
- Backend, fix round 1, test order: findings 1 to 5 have real red runs. Findings 6 and 7 pin existing code, so they passed first time and carry `mutation:` evidence, as do the six implementation-stage suites; that evidence shows the tests can fail, not that they came first.
- Driver, fix round 1: `.doc/architecture.md` and `.doc/glossary.md` updated in this round rather than at the finish, so the security reviewer can close that finding from the fix diff.
- Backend, fix round 2: a `tool_use` whose input is not a JSON object fails the run as `internal` before any tool runs and is never stored, because the API would refuse the echoed turn on every later send; an object that fails validation stays an `is_error` result, as V02 says. The fake now answers a 400 to a request with an empty `content` or a non-object `tool_use.input`. `_call_tool`'s earlier non-object branch is now unreachable and stays, as the round touched nothing else.
- Backend, fix round 2: `to_dict(warnings=block.type != "tool_use")` replaces `warnings=False`.
- Exception to Definition of Done item 2, accepted by the user with the go-ahead to commit (2026-10-30, "lets commit and push, merge to dev"): the backend's implementation-stage tests were written after the code, and their sensitivity was shown by `mutation:` runs, not red runs. QA left this open as the user's decision.
