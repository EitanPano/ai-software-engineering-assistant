# Admin can connect a GitHub repository to the knowledge base

Status: done
Approval: delegated (2026-10-31, "Approve")
Owner:
Last updated: 2026-10-31
Branch: feat/connect-github-repository
Base: f591cf6ed71af41d3e407ddbb84358bc9485c466
Stages: backend, frontend, qa
Retired: none

## Goal

An admin pastes a public GitHub repository's URL, watches it index, and its code lands in the knowledge base as documents and chunks with line ranges and embeddings. Nothing searches them yet: AC03 closes with the next backlog task, on the fixture repository and the chunks this task ships, and AC01 stays green.

## Scope

- In:
  - Connect a public repository at a ref, list sources with their status, and retry a failed one.
  - A background index: download, skip what is not source text, chunk by symbol, embed, store.
- Out:
  - The keyword column, `pg_trgm` and both search indexes: no query here needs them, so they ship in the search task's migration.
  - Private repositories, re-indexing, removing a source and a limit on connect: the backlog's `admin can connect a private GitHub repository`, `admin can re-index a connected source`, `admin can remove a source` and `connect is rate limited per admin`.

## Assumptions

- Plan 003 shipped Postgres 18, `vector` in `0004-vector-extension.sql`, the `%s::halfvec(1024)` cast `TestTheEngine` proves, and `grant_admin`; `0005-source.sql` follows that migration and no step here touches the Compose image.
- Ingestion reads `GET /repos/{owner}/{repo}/tarball/{commit}` as a stream and never extracts it: the image has no `git`, a clone needs a subprocess the selector loop cannot run on Windows, and writing no file means no path traversal.
- `services/github.py` and `services/voyage.py` use `httpx2`, already declared; there is no `voyageai` or `pgvector` Python package, because a vector travels as text cast to `halfvec`.
- `voyage-code-4`, per Voyage's docs on 2026-10-30: 1024 dimensions by default, so `halfvec(1024)`; 1000 texts a request; no published token limit per request, so batches stay under voyage-code-3's 120,000.
- Indexing is a bus reaction like `execute_run`, and one replica lets a boot sweep find what a lost process left; chunks embed and commit in batches, because a large repository's embeddings do not fit in memory, so the search task reads only `ready` sources.
- The caps bound one index: 32 MiB of text embeds as at most 64 MiB, about 20 million tokens, about $2.40 at $0.12 per million once the 200 million free tokens are spent, and a retry pays again. A repository over a cap fails whole, never indexed in part.

## Open Questions

1. Who may connect? The backlog line said `user` and `.doc/product-definition.md › Purpose` says engineers connect, while `Auth and Tenancy` and `.doc/architecture.md › Auth` give sources to `admin`. Any user: no admin step, but every account can spend Voyage money and add third-party text to the knowledge base all users' agents read. Admin only: both stay controlled, at the price of a way to make the first admin, which `move-database-postgres-18` ships. Recommended: admin only, and reword the backlog line.
   > Admin only (2026-10-30, the user).
2. Public repositories only? `.doc/conventions.md` keeps the GitHub token in its MCP server's container, so ingestion has none: public repositories, 60 API requests an hour per server address, about 15 connects an hour. Private code needs a read-only token in the backend, which changes that rule and puts a credential in the process that handles repository content. Recommended: public only; `admin can connect a private GitHub repository` decides private access with the GitHub MCP task.
   > Public repositories only (2026-10-30, the user).

## Contract

| Endpoint | Request | Response | Errors |
| --- | --- | --- | --- |
| `POST /api/source` | `body.url: string`, exactly `https://github.com/<owner>/<repo>`; `body.ref?: string`, a branch, tag or commit, default the repository's default branch | 201 `Source`, `status: queued`, `url` in GitHub's own spelling | 400, 401, 403, 404 (no such public repository or ref, or an empty one), 409 (this url and ref are connected), 503 (GitHub unreachable or limiting) |
| `GET /api/source` | `query.cursor?`, `query.limit?` | 200 `SourcePage { items: Source[], nextCursor }`, newest first | 400, 401, 403 |
| `POST /api/source/{id}/indexing` | `params.id` | 202 `Source`, `status: queued` | 400, 401, 403, 404, 409 (not `failed`) |

- `Source { id, url, ref, status: queued | indexing | ready | failed, errorCode: repository_unavailable | repository_too_large | embedding_unavailable | interrupted | internal | null, indexedCommit: string | null, documentCount, chunkCount, createdAt, updatedAt }`.
- `<owner>` is 1 to 39 letters, digits or hyphens; `<repo>` is 1 to 100 letters, digits, `.`, `_` or `-`, not `.` or `..`, not ending in `.git`. Nothing else: no userinfo, port, query, fragment or trailing slash.
- `ref` is 1 to 255 letters, digits, `.`, `_`, `/` or `-`, with no `.` segment, no `..` anywhere and no leading `/` or `-`.

## UX

- /source — list — connect a repository — states: loading `ListSkeleton` · empty `EmptyState` pointing at the header's action · error the group's `ErrorState`; a failed row shows its reason, mapped from `errorCode`, and a retry action; the rows refresh every 3 s while one is `queued` or `indexing` — tone: calm, dense, precise — phone: one column, the action in `PageHeader`
- /source/connect — form — connect the repository — states: loading the group's `loading` · empty not applicable · error under the URL field for `not_found` and `conflict`, a toast for `upstream_unavailable` — tone: calm, dense, precise — phone: one column, `FormActions` sticky

## Steps

### Backend

1. `backend/pyproject.toml`, `backend/uv.lock` — `tree-sitter>=0.26` and the `tree-sitter-python`, `tree-sitter-javascript`, `tree-sitter-typescript` grammars (`.doc/conventions.md › Tooling`); `index_source` joins the import-linter lists naming `execute_run`, and `infra/dependency -> api/source/controller` those naming `api/run/controller`.
2. `docker-compose.yml`, `backend/.env.example`, `backend/src/app/config/env.py` — `VOYAGE_API_KEY` (in `_SECRET_NAMES`, on both backend services), `VOYAGE_BASE_URL` and `GITHUB_BASE_URL` (refused in production).
3. `backend/src/app/config/constants.py`, `backend/src/app/models/source/` — the caps (32 MiB of text, 5,000 documents, 1 MiB a file, 256 MiB an archive, 1 GiB unpacked and 200,000 members, both counted across skipped members too, because skipping one still decompresses it; 64 MiB of embedded text and 100,000 chunks, because the input caps do not bound what chunking produces), the chunk bound, the skipped directories and suffixes, the embedding model and dimension; the records, `SourceStatus`, `SourceErrorCode` and the `url` and `ref` limits.
4. `backend/src/app/infra/migrations/0005-source.sql` — after `0004-vector-extension.sql`: `source` with unique `(url, ref)`, `(created_at, id)` and an active-status index; `document` with unique `(source_id, path)`; `chunk` with `symbol`, `start_line`, `end_line`, `content`, `embedding halfvec(1024) not null`; both keys cascade.
5. `backend/src/app/api/source/schema.py`, `routes.py`, `backend/src/app/config/routes.py`, `backend/src/app/openapi.py`, `backend/openapi.json`, `backend/tests/test_openapi.py` — contract stage: `require_role(UserRole.admin)` on every route, `Source`, `SourcePage`, `ConnectSourceBody` in `COMPONENTS`, the paths in `TestTheDocument::test_documents_exactly_the_surviving_paths` and the names in `TestTheShaping::test_makes_a_component_of_exactly_the_listed_names`, then `contract`.
6. `backend/src/app/services/github.py` — no credentials and no automatic redirects: repository and commit lookups, and an archive streamed to a spooled temporary file under its byte cap, following one redirect only to `codeload.github.com` or the configured base URL; `ref` percent-encoded as one path segment.
7. `backend/src/app/services/voyage.py` — paid, $0.12 per million tokens: `embed_documents` with `input_type: document` and `truncation: false`, bounded retries on 429 and 5xx, `use_client` as in `services/anthropic.py`.
8. `backend/src/app/services/chunk.py` — from the symbols `services/parse.py` returns, one chunk per symbol for Python, JavaScript, TypeScript and TSX; the code between symbols and every other file in overlapping line windows, each under the chunk bound; lines split on `\n` only, as tree-sitter and GitHub number them, never `str.splitlines`.
9. `backend/src/app/services/parse_worker.py`, `backend/src/app/services/parse.py` — `parse_worker` is the only importer of `tree_sitter`, a long-lived child started with `subprocess.Popen([sys.executable, "-m", "app.services.parse_worker"])` from the indexing thread and a minimal environment, one JSON line per file over its pipes; not `multiprocessing`, whose spawn re-imports `app.main` and with it the secrets, and whose fork inherits them. `parse.py` gives each file 2 s and each index 60 s: an overrun or a crash kills and restarts the child and that file goes to line windows, a spent budget sends the remaining files there, and the child ends with the index.
10. `backend/src/app/api/source/service.py`, `controller.py` — copied from `api/conversation/` without what `backend/AGENTS.md › Adding a module` keeps out, paged and mapped like `api/user/service.py`, each handler rechecking the role like `api/user/controller.py`, because the copy has no role check: the connect handler canonicalises through GitHub, stores and publishes; `index_source`, a system operation, claims the `queued` row, clears an earlier attempt, reads the archive and chunks on a worker thread, embeds and commits batch by batch, and ends `ready` or `failed` on every exit; `fail_lost_sources`.
11. `backend/src/app/services/event.py`, `infra/subscribers/index_source.py`, `infra/pubsub.py`, `infra/dependency.py`, `main.py` — `SOURCE_QUEUED` and its subscriber; `sweep_lost_sources` beside `sweep_lost_runs`.
12. `backend/tests/` — `fixture_repository.py`; `fake_github.py` (port 8102, the fixture as a tarball behind a 302, the repository name picks a script); `fake_voyage.py` (port 8103, deterministic unit vectors, a marker fails the call until released); `source_support.py`; `test_source.py` (`store_backed`), `services/test_github.py`, `services/test_voyage.py`, `services/test_chunk.py`, `services/test_parse.py`, `infra/test_sweep.py`, `test_entry.py`.
13. `backend/AGENTS.md` — the layer map, the new services and the parse worker, the fakes.

### Frontend

1. `frontend/src/shared/api/generated/` — `contract`, once the backend's contract stage has reported.
2. `frontend/src/entity/source/` — types, status label and tone, the `errorCode` copy, the list's infinite query with its refresh while a row is active, the row.
3. `frontend/src/feature/connect/` — the form schema extending the generated body, the copy table, the connect mutation and form, the retry mutation and row button.
4. `frontend/src/widget/source-list/` — the section, its `Show more` as in `widget/conversation-list/`, the skeleton.
5. `frontend/src/app/(site)/source/page.tsx`, `(site)/source/connect/page.tsx`, `app/routes.tsx`, `app/nav.ts`, `(site)/layout.tsx` — both routes in a pathless admin group with `requireRole` in every loader; a nav entry with an optional role, which the layout filters through `useCurrentUser`.
6. `frontend/tests/e2e/support.ts`, `frontend/tests/e2e/settled.spec.ts` — `settled`'s filter also requires `animation.playState === 'running'`, because its loop never ends on a finished animation with `fill: forwards` or `both` (the open P2 in plan 002); a `forwards` case, red first, whose red run ends at the test timeout.
7. `frontend/playwright.config.ts`, `frontend/tests/` — web servers for both fakes and their URLs on the API; `e2e/source-support.ts`, whose `setup` runs `uv run python -m app.infra.scripts.grant_admin <email>` from `backend/` through `execFileSync`, with `PASSWORD` from `auth-support.ts` as `input` and `account.databaseUrl` as `DATABASE_URL`, so a non-zero exit fails the test; each admin journey then signs out and in through the UI, as `screens.spec.ts` does, because `grant_admin` ends the account's sessions and the old token keeps the old role; `e2e/source.spec.ts`, left out under `E2E_BASE_URL`, each scan after a state change asserting the end state first (`Ready`, an enabled button), because `settled` cannot wait for a transition that has not started; both routes in `SIGNED_IN_ROUTES`; unit tests for the above and in `playwright-config.test.ts`.
8. `frontend/AGENTS.md` — the fakes, the staff group and its `setup`, the role on a nav entry.

Every e2e run, step 6's red run included, waits for the driver's `backend ready`: no e2e runs beside a `verify` (plan 002).

### Driver

1. `.github/workflows/ci.yml`, outside both lanes — `VOYAGE_API_KEY` in the `image` job's generated secrets, or the production image refuses to boot.
2. `.doc/architecture.md`, `.doc/glossary.md` — the Data Model, External Dependencies (GitHub's public REST API, Voyage with `VOYAGE_BASE_URL`), the change log; the terms `symbol` and `fixture repository`.

## Validation

- V01 — An admin connects a repository, with and without a `ref`, and gets a `queued` source in GitHub's spelling; an unknown repository or ref is a 404, a second connect a 409, GitHub down or limiting a 503 (AC03) — proof: `backend/tests/test_source.py::TestConnect`
- V02 — Every URL outside the exact form (`http`, another host, userinfo, a port, a query, a fragment, a trailing slash or newline, `.git`, `..`, a third path segment) and a malformed `ref` is a 400 with no call to GitHub (AC03) — proof: `backend/tests/test_source.py::TestUrlShape`
- V03 — No token is a 401 and a `user` a 403 on every endpoint, with the envelope's `code` and `requestId`; a `user` reaches `/forbidden` and sees no nav entry (AC01) — proof: `backend/tests/test_source.py::TestAccess`, `frontend/tests/unit/source-routes.test.tsx`
- V04 — The fixture repository ends `ready` with its commit and counts; skipped directories and binary, undecodable and oversized files store nothing; each chunk's `content` is exactly its document's lines `start_line` to `end_line`, every non-blank line is in a chunk, and each embedding has 1024 dimensions (AC03) — proof: `backend/tests/test_source.py::TestIndex`
- V05 — Python, JavaScript, TypeScript and TSX split by symbol, with exact line ranges past line 256 and column 256; an oversized symbol, an unknown language and a file that fails to parse fall back to line windows; a crafted file that overruns its deadline or a worker crash falls back too, a spent budget sends the remaining files there, and `GET /api/health` keeps answering throughout; a file with form feeds keeps GitHub's line numbers (AC03) — proof: `backend/tests/services/test_chunk.py`, `backend/tests/services/test_parse.py`
- V06 — GitHub receives no `Authorization` header; a redirect to any other host is refused; an archive, its unpacked size, its member count, its document count, its text, its embedded text or its chunk count over a cap fails as `repository_too_large`, before anything is embedded where the cap allows, with no chunk left; symlink and traversal members store nothing; the parse worker's environment holds no secret and it imports no `app.config`; both `*_BASE_URL` variables are refused in production (AC03) — proof: `backend/tests/services/test_github.py`, `backend/tests/services/test_parse.py`, `backend/tests/test_source.py::TestHostileRepository`, `backend/tests/test_entry.py`
- V07 — A Voyage failure ends `failed` with `embedding_unavailable` and no partial rows; a retry ends `ready` with no duplicate; retrying a source that is not `failed` is a 409; a source a lost process left active ends `interrupted` at boot (AC03) — proof: `backend/tests/test_source.py::TestRetry`, `backend/tests/infra/test_sweep.py`
- V08 — An admin connects through the UI, sees `Ready` with counts, a field error for a missing repository and a retry that recovers; `settled` ends on a finished `forwards` animation; every gate and the e2e suite pass with no network and no API key (AC01, AC03) — proof: `frontend/tests/e2e/source.spec.ts`, `frontend/tests/e2e/settled.spec.ts`, `node scripts/verify.mjs --plan <plan> --reuse`

## Risks

- The fakes can drift from GitHub's and Voyage's wire formats — the user, signed in as an admin made per `backend/AGENTS.md › Authentication`, connects `https://github.com/octocat/Hello-World` with a real `VOYAGE_API_KEY` before merge: a few hundred tokens, under $0.001 and inside the free allowance, plus four anonymous GitHub requests.
- Voyage publishes rate limits only for accounts with a payment method (8M tokens and 2,000 requests a minute at tier 1), so the free allowance may not carry a real repository until one is added — bounded retries end the source as `embedding_unavailable`, and a retry embeds the whole repository again, at its cost.
- Repository text is attacker-controlled, and the shared knowledge base reaches every user's agent once the search tool lands — admin-only connect is the control here; nothing in this task sends that text to the model.
- Anonymous GitHub calls share 60 an hour per server address, and a connect spends four — a limit answers 503 or fails as `repository_unavailable`, and a retry works after the reset.
- `tree-sitter` holds the GIL for a whole parse, which cannot be interrupted, and its time grows about with the square of a crafted file's size (measured 2026-10-31: 0.18 s for 1 MiB of ordinary code, 9.9 s for 64 KiB of `"'` as TypeScript, over 20 s for 128 KiB) — it runs only in the parse worker, with a deadline. That child is isolation, not a sandbox: it holds no secret, and it runs as the same user.
- A long-lived child is one more process to keep healthy on a server that also serves chat — it starts with an index and ends with it, so nothing runs while no index does.

## Rollback

Revert the branch. `0005-source.sql` only adds tables, which the old code ignores; removing them deletes every indexed source, so that is a human's `drop table chunk, document, source`. `vector` stays: it belongs to `0004-vector-extension.sql`.

## Changes during the task

- Plan amended on the user's decision (2026-10-31, "Parse in a separate process"), after step 1's probe showed `tree-sitter` holds the GIL for a whole parse and the driver's probe showed crafted input takes about quadratic time: 10 s for 64 KiB. A lower file cap could not bound that. Steps 8 and 9, V05, V06 and the Risks changed; the old steps 9 to 12 became 10 to 13.
- Driver: `backend/tests/probe_tmp.py`, emptied by the backend, was removed.
- Contract: `POST` and `GET /api/source`, `POST /api/source/{id}/indexing` and the components `Source`, `SourcePage`, `ConnectSourceBody` added to `backend/openapi.json`, as the Contract table says. The `.git`, `.`, `..` and ref `..` rules are server-side only, not in the schema's pattern.
- Backend, contract stage: chose what the plan left open: a chunk bound of 6,000 characters, line windows of 60 lines overlapping 10, embedding batches of 128 texts or 100,000 tokens, commits of 512 chunks. The implementation stage may tune them.
- Backend, contract stage: `index_source` joins the import-linter `layers` list when the subscriber lands, not in step 1, because that contract fails on an ignore that matches nothing.
- Backend: the worker starts with `-I -X utf8`, so `PYTHON*` variables, the user site and the current directory stay out of it. On Windows a virtual environment's `python.exe` is a launcher, so the worker reports its pid and a kill ends both, guarded against a reused pid.
- Backend: a line longer than the 6,000-character bound is cut into pieces that share its line number, because "every chunk under the bound" and "every non-blank line is in a chunk" could not otherwise both hold. V04's "exactly its lines" excepts such a line.
- Backend: the skipped directories and suffixes, and the unpacked cap counting tar headers and padding, are its choices. `ArchiveRefused` is a `GithubUnavailable`, and a redirect on a repository or commit lookup answers not found, since it is never followed.
- Backend, open for review: the tarball reaches its spooled file through blocking writes on the event loop, 64 KiB at a time; and a SIGKILL of the API leaves the worker running until its current parse ends, which graceful exits do not.
- Frontend: e2e waited for the backend, per the plan. Its handoff on the fakes was relayed; they match, and `embedfail-<key>` adds a `FAIL.txt`, so that source ends with 7 documents.
- Frontend: the `Failed` badge is an outline in the destructive text colour with an icon and the word, because the filled badge failed axe `color-contrast` in dark mode. The `settled` `forwards` case was red at the test timeout, then green with the `playState` filter.
- Security review, P0: reading `.row` or `.column` on a `tree_sitter.Point` in 0.26.0 corrupts memory from 257 upward; indexing and unpacking do not. The driver reproduced it on Windows. Every fixture file was under 30 lines, so no gate saw it, and on `pallets/flask` 18 of 80 files crashed the worker and fell silently to line windows. The separate process is why it never reached the API.
- Plan corrected in fix round 1: "$1.15" and "the caps bound one index" were wrong, because nothing bounded what chunking produces (up to 11x embedded text, about $13). The Assumption, step 3, V05 and V06 changed, adding member, chunk and embedded-text caps.
- Backend, fix round 1: the P0 is fixed with indexing and unpacking, and `_symbols_of` validates a reply strictly, treating anything else as a crash. Fallbacks are counted per index and logged as `parse fell back`, because the P0 hid behind a silent one. The fixture gained `src/late.py` with a definition on lines 299 to 300.
- Backend, fix round 1: windows advance by at least half their length: 2.0x embedded text on 545-character lines, down from 9.95x. A repository over the 64 MiB embedded cap fails whole, so the cap is the bound, not the measured ratio. `finish_failed` updates first and deletes only when it matched. `tarfile` runs with `stream=True` behind a 200,000-member cap, with one `type: ignore` because typeshed lacks the keyword.
- Backend, fix round 1: `resolve_commit` asks for `application/vnd.github.sha`, which has only run against the fake, so the user's smoke test covers it. The worker thread, not `_index`, closes the archive, so a cancelled index never closes it under a reader. `backend/tests/measure_tmp.py` was removed.
- Frontend, fix round 1: the pathless admin group gained its own `requireRole` loader, so the group is the gate, and the children keep theirs because matched loaders run in parallel. `screens.spec.ts`'s `/source` capture now connects a ready and a failed source, so phone rows were judged populated, and `PREPARE_MS` rose to 70 s.
- Reviews, re-review 1: P0 and the three P1s closed; two new P1s on the worker's reply, both in fix round 2: `_symbols_of` bounded no symbol name, and a worker `internal` error fell back uncounted. The reply is now treated as untrusted input throughout.
- Backend, fix round 2: the reply is untrusted. `SYMBOL_NAME_MAX` is 256: a longer name keeps its symbol without the name, because an honest worker can send one, and NUL or a lone surrogate counts as a bad reply. Only `{"error": "syntax"}` is not a fault; every other reply without valid symbols is a counted crash. A reply is read to at most 8 MiB, and a deep one cannot raise out of `symbols()`. The ready line's pid must be an integer above 1 and not this process. `syntaxErrors` joins `parse fell back`, and the worker's exception class is logged as `parse worker raised`.
- Backend, fix round 2: the comments now say the caps bound the cost, not the ratio: 2.0x on uniform lines and 3.28x at worst measured. The new `test_source.py` cases ran only under `testDb`, so they have no red run.
- Left open at the end of the fix rounds: a child that stops reading its stdin, or a grandchild holding its stdout, can hold an index past its deadline, and both need code execution in the child; a cancelled queued `to_thread` leaves the child until the process exits; `service.py:220` formats inside the transaction; a redirect with no `Location` has no test; the SIGKILL orphan.
- QA: V05 and V06 re-judged after the amendments, PASS, adding `TestARealShapedLargeFile`: 5,000-line files in all four languages keep exact symbols with no crash.
- Open at the task's end, from re-review 2: `_lines` bounds a line, not the number of lines, so a compromised child can flood the queue through the embedding stage; an oversized ready-line pid raises out of `close()`; `SYMBOL_NAME_MAX` belongs in `models/`. The real smoke test was not run: the user chose to merge after CI without it (2026-10-31, "Commit, push, merge after CI"), so Voyage and `resolve_commit`'s sha request have run only against the fakes until a later task exercises them.
