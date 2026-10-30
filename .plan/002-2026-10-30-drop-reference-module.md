# Drop the reference module

Status: done
Approval: delegated (2026-10-30, "Approve this plan")
Owner:
Last updated: 2026-10-30
Branch: chore/drop-reference-module
Base: 44bf820244dbdfd02791a5c2db4194cd083f105f
Stages: backend, frontend, qa
Retired: `api/module`, `app.api.module`, `models/module`, `app.models.module`, `tests/test_module.py`, `module_router`, `MODULE_CREATED`, `ModuleCreated`, `module.created`, `create_post_per_ip`, `ModulePage`, `CreateModuleBody`, `UpdateModuleBody`, `ModuleRecord`, `ModuleStatus`, `ModuleId`, `create_module`, `get_module`, `list_module`, `update_module`, `delete_module`, `find_module_by_id`, `Drop the reference module`, `belongs to the reference module`, `the commented reference`

## Goal

The template's public, unused `/api/module` CRUD and its `module` table leave the product, so the API holds only product routes and `api/conversation/` is what the next module copies. Users see no change; AC01 stays green, with every shared behaviour the reference module proved still proved on surviving code.

## Scope

- In: the removal `backend/AGENTS.md › Adding a module` lists, a migration dropping the `module` table, the tests that lean on the module, and that file's rewrite around `api/conversation/`.
- Out: editing `0001-init.sql`, which every database has applied, so the drop is `0003-drop-module.sql` after `0002-conversation.sql`; a worked example of PATCH and DELETE, which `user can delete a conversation` starts.

## Assumptions

- `api/conversation/` is the new reference (`backend/AGENTS.md`: copy your first module for the next one): at `44bf820` it has `with_transaction`, `Tx` and all four `models/` files. Its `_to_conversation` mapping and `(updated_at, id)` paging differ, so `api/user/service.py` stays the example of `_to_record` and `(created_at, id)`.
- `retired-terms` matches case-insensitive substrings per line and skips `*.sql`, `openapi.json` and `api/generated/`: `Retired:` holds no bare `module`, no test spells a retired term to assert its absence, and exact-set tests prove the contract.
- Only steps 1 and 2 have a red run: the repointed and ported tests pin existing behaviour, so the report names each one's source test instead.

## Open Questions

None.

## Contract

| Endpoint | Request | Response | Errors |
| --- | --- | --- | --- |
| `GET`, `POST /api/module` | removed, with `CreateModuleBody` | removed, with `Module`, `ModulePage` | 404 `not_found` |
| `GET`, `PATCH`, `DELETE /api/module/{id}` | removed, with `UpdateModuleBody` | removed | 404 `not_found` |

## UX

No route changes: the frontend stage only regenerates the client.

## Steps

### Backend

1. `backend/tests/test_openapi.py`, `backend/src/app/config/routes.py`, `backend/src/app/openapi.py`, `backend/openapi.json` — red first, an exact set of documented paths; the module tests repoint (paths and page to `/api/user`, enum and timestamps to `PublicUser`, the 204 to `POST /api/auth/logout`, the create to `POST /api/conversation`, whose set is `201`, `401`, `500` with no 400 because it has no body, the 401 and 403 to `GET /api/user/{id}`); drop the mount and the four `COMPONENTS` names, then `contract`.
2. `backend/src/app/infra/migrations/0003-drop-module.sql` — drop the table, which takes its index; `backend/tests/db/test_postgres.py::TestMigrate` proves it, red first.
3. `backend/src/app/services/event.py`, `backend/src/app/config/constants.py`, `backend/src/app/services/utils/pagination.py`, `backend/src/app/api/user/service.py` — drop the topic, its payload type and `create_post_per_ip`; the docstrings name `api/user/`, `ConversationPage` and `api/conversation/service.py`.
4. `backend/tests/test_store.py`, `backend/tests/services/test_event.py`, `backend/tests/services/test_pagination.py` — `TestTheSeam` on `user` rows through `api/user/service.py`; a test-local `Topic`, so no live subscriber runs; the docstring.
5. `backend/tests/db/test_postgres.py`, `backend/tests/db/test_user.py` — `TestWithTransaction` keeps its three tests on `api/conversation/service.py`, `table_exists` probes move to `session`; `TestTheModuleService` leaves, and `test_user.py` gains what has no twin: the hostile value, the UTC round trip, the empty page, `TestCursorIsStrict`'s parametrised cases.
6. `backend/AGENTS.md` — the layer map, `Where does X go`, the handler and `with_transaction` examples and `Adding a module` name `api/conversation/` and its identifiers; the `service.py` bullet and `Adding the data layer` name `api/user/service.py` for `_to_record` and `(created_at, id)`; `Renaming the roles` keeps only `api/user/`; the drop instructions and the `module` table paragraph go.
7. Report `Delete:`, one path per line, in the contract stage's report, so the driver removes them before the rest of the plan runs: `retired-terms` and `test_module.py` keep `verify --package backend` red while they exist, and no role agent can delete. The five files of `backend/src/app/api/module/`, the five of `backend/src/app/models/module/`, `backend/tests/test_module.py`. Step 5 ports from `git show <Base>:backend/tests/test_module.py`.

### Frontend

1. `frontend/src/shared/api/generated/` — `contract`, once the backend reports `Contract: changed`; no other file changes.

### Driver

1. `.doc/glossary.md`, `.doc/architecture.md` — remove the `module (reference)` row; a change-log line for the removed routes and table.

## Validation

- V01 — The contract documents exactly the surviving paths and components, nothing undocumented stays mounted, and the committed `openapi.json` and generated client match it (AC01) — proof: `backend/tests/test_openapi.py::TestTheDocument::test_documents_exactly_the_surviving_paths`, `::TestEveryDocumentedPathIsMounted::test_documents_every_api_path_and_method_it_mounts`, `::TestTheShaping::test_makes_a_component_of_exactly_the_listed_names`, `::TestTheCommittedContract`, `verify`'s `contract` steps
- V02 — The shipped migrations leave no `module` table and no index whose name starts with `module`, and record `0003-drop-module.sql` (AC01) — proof: `backend/tests/db/test_postgres.py::TestMigrate::test_has_dropped_the_module_table_from_the_shipped_migrations`, which probes `pg_indexes` by that prefix, because the index's full name contains the retired `MODULE_CREATED`
- V03 — The store seam, the pool, `with_transaction` and the event bus keep their proofs, and `user` now proves what only the module did: a hostile value stays a parameter, a timestamp returns in UTC, an empty table is an empty page, a cursor without an ISO timestamp and timezone is a 400 (AC01) — proof: `backend/tests/test_store.py::TestTheSeam`, `backend/tests/db/test_postgres.py::TestThePostgresResource`, `::TestWithTransaction`, `backend/tests/services/test_event.py::TestEvent`, `backend/tests/db/test_user.py::TestTheUserServiceOnPostgres`, `::TestCursorIsStrict`, `::TestGetUserOnPostgres`
- V04 — Every gate and the e2e suite pass, no `Retired:` term remains, the glossary row is gone, and a stage report names each removed test with its reason or twin (AC01) — proof: `node scripts/verify.mjs --plan <plan> --reuse`, `git grep -n "module (reference)" -- .doc/glossary.md` finding nothing, `git diff --name-status <Base>` against the backend report

## Risks

- Deleting 468 lines of tests hides coverage of shared code — step 5 ports what has no twin, the rest has one in `tests/test_user.py`, `tests/test_conversation.py`, `tests/test_server.py` and `tests/middleware/`, and QA checks the report's list.

## Rollback

Revert the branch for the code. The migration is forward-only: `backend-migrate` drops the table before the old server stops, and a reverted branch finds no table, so `/api/module` answers 500 until a new migration recreates it from `0001-init.sql`'s text. Nothing calls that route or reads its rows, which only a backup restores.

## Changes during the task

- Contract: `/api/module`, `/api/module/{id}` and the components `Module`, `ModulePage`, `CreateModuleBody`, `UpdateModuleBody` left `backend/openapi.json`, as the Contract table says; nothing else changed.
- Driver: the eleven `Delete:` paths were removed after the contract stage, per step 7. The next `verify` follows the implementation stage, because `tests/test_store.py` and `tests/db/test_postgres.py` import the removed code until steps 4 and 5.
- Backend: `tests/services/test_event.py`'s test-local topic is `test.pinged`, with a `Pinged` payload.
- Backend: step 6's first pass skipped the `service.py` bullet of `backend/AGENTS.md`; fix round 1 made it name `api/user/service.py` for `_to_record` and `(created_at, id)`.
- Backend: `TestCursorIsStrict` moved to `tests/db/test_user.py` as its own class, including the accepted list cursor, so V03's proof names it. The naive-timestamp case came from `TestList`, and fix round 1 adds it to this class.
- Driver: `Retired:` was narrowed during QA for a test that requested `/api/module`, then restored in fix round 1 after the general review showed an assertion over `app.routes` proves the same without spelling the path. The term never left the gate on a passing run.
- Backend: the module's delete-by-id test has no surviving twin, because `user` has no delete; `user can delete a conversation` brings a delete back.
- Backend, fix round 1: QA's `tests/test_qa_drop_module.py` was uncommitted, and its cases moved to files that mirror `src/app/`: limit bounds, trailing slash, 403 before 400 and HEAD to `tests/test_user.py::TestListUser`, forged fields to `tests/test_auth.py::TestRegister`. Its route-absence test became the V01 assertion over `app.routes`, so no test spells a retired term.
- Frontend, fix round 1: `expectNoSeriousViolations` and `screenProblems` wait for finite animations, and `conversation.spec.ts` waits for Send to re-enable before its scan. axe could measure Send mid-fade between `disabled:opacity-50` and 1 (1 failure in 30 repeats before, 60 of 60 after). The race came with plan 001, not this task. `tests/e2e/support.ts` may be template code a harness update overwrites.
- Frontend, fix round 2: `settled` loops with `Promise.allSettled` until no finite animation remains, because round 1 put it in front of every scan and a cancelled transition rejected `Promise.all` with an `AbortError`. `tests/e2e/settled.spec.ts` proves it, red first. The reload test also waits for Send, because `busy` can flip after first paint when the latest run ends.
- Open at the task's end, both fix rounds used: `settled`'s loop in `tests/e2e/support.ts` never ends on a finished animation with `fill: forwards` or `both`, which keeps it in `getAnimations()`. Nothing in the app reaches that today, and it would fail at the test timeout, never pass falsely. The fix is `animation.playState === 'running'` in the filter, with a `forwards` case in `settled.spec.ts`.
- Frontend, fix round 1: two debugging or partial runs failed with an unknown cause, one with `ERR_CONNECTION_REFUSED` on `127.0.0.1:5173`, while the backend's `verify` ran alongside. `scripts/verify/reap.mjs` is ruled out, because it kills only its own step's descendants. From here the driver runs one package's e2e with no other `verify` active.
