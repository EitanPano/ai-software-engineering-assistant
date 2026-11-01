# Admin can manage MCP servers and tool policy

Status: done
Owner:
Last updated: 2026-11-02
Branch: feat/manage-mcp-server-policy
Base: d230e78b8a4e37b653945ff8e54b4903ebc3a5e2
Approval: by the user on 2026-11-01, after the driver's read against the code ("Approve and start")
Stages: backend, frontend, qa
Retired: `_holds_nul`

## Goal

An admin opens `/mcp-server`, sees each server and whether its pin still matches, reads a changed definition whole before accepting it, accepts with a click instead of plan 012's shell command, turns a server off or on, and sets each tool to allow, ask or deny, effective on the next call. This is the `MCP servers, tool policy` half of `.doc/product-definition.md › Auth and Tenancy`. It adds no AC: it keeps AC05 and AC06 true through an admin's hands, and `a tool with no policy is denied` becomes visible and fixable. No model call changes, so nothing here needs a real key and no paid run is proposed.

## Scope

- In:
  - Read the servers and each one's pin status, with no call to any server; enable and disable a server.
  - Review a third-party server's live listing whole, each tool's change and both versions of a changed tool, its invisible characters shown, then accept it, bound by digest to what was shown, over plan 012's `read_listing` and `accept_listing`.
  - Refuse the listings `accept_mcp_server` refuses through one shared rule, and what the store cannot hold at `list_tools`, which also closes `review-security.md`'s NUL P2.
  - Read and set each tool's policy, a tool with no row included, within Question 2's cap.
- Out:
  - Later tools in existing conversations: already `a tool accepted later reaches existing conversations`. No `tool_addition` here; a frozen conversation denies, as plan 012 left it.
  - Question 1: `- [ ] admin can add and remove a third-party MCP server`
  - A text diff, because the admin reads both versions whole anyway: `- [ ] admin reads a changed tool definition as a word diff`
  - Pagination (`review.md`, `mcp.py:189`), which fails closed: `GITHUB_TOOLS` holds `github` to seven tools and under Question 1 an admin reaches no other server, so `whole` holds. A yes to Question 1 brings it in: `- [ ] a server's listing is read past its first page`
  - An audit history, because this task only logs: `- [ ] admin sees who accepted a listing or changed a tool policy`
  - A limit on the live read, which the admin role bounds as on `source` and `eval`: `- [ ] reading a server's listing is rate limited per admin`

## Assumptions

- Plan 012 as landed: `read_listing(server)` returns the live listing, a disabled row included, or `None` when the server has no address or did not answer; `accept_listing(server, tools)` stores `tools` as the pin and the last listing and enables the row in one statement (`service.save_pin`), so `pinStatus` reads `current` at once.
- An accept binds as an approval does (plan 011): the review returns `tool.listing_digest`, the accept echoes it, the handler reads the server live again, compares and pins exactly what it just read; a difference is a 409 that writes nothing. Both digests come from live reads, so the digest's unnormalised numbers (`review.md`, `type.py:39`) can only cost a 409. The browser never sends a definition, and shows every third-party string through `visibleText`: the pinned bytes are what the model reads, so this screen is the trust decision.
- `pinStatus` compares the stored last listing with the pin by `canonical` JSON, through `tool.listing_changes`, and makes no call, so the list and detail work while a server is down; only the review page reads live, and its loader prefetches nothing. `tool_definition` is only as fresh as the last run, so the review page is the truth and plan 012's gates hold regardless.
- `GET /api/tool-policy/{mcpServerId}` is one document, not a paged list: a listing bounds it, and it must name tools with no row, which no cursor over `tool_policy` can. `tool_policy`'s controller imports `mcp_server`'s, never the reverse, so there is no cycle.
- `knowledge` has no pin, so its review and accept are a 409; its `enabled` and its `search` policy are editable like any other. The `accept_mcp_server` command stays, `grant_admin`'s shape for a shell; both doors call `accept_listing` and refuse through one rule, `tool.listing_problem`, which takes over the command's empty, repeated-name and `[A-Za-z0-9_-]+` checks.
- No migration: `0009` to `0011` hold every column, and the loop already reads `enabled` and `tool_policy` at each call and at a resume, so a change needs no restart. The one edit on a run's path is `list_tools` refusing what JSONB refuses, measured: an escaped NUL, `NaN`, `Infinity` and `1e400` pass the SDK's parser and JSONB refuses each, so the new routes would answer 500; a lone surrogate never passes the parser.

## Open Questions

1. Does `manage` include adding and removing a server? v1 names two servers (`.doc/product-definition.md › Product Scope`) and no AC asks for a third.
   Adding one means an admin-typed URL the backend connects to, the door `.doc/conventions.md` closes for sources, plus a name rule (`__` splits `<server>__<tool>`) and a token story, since `_endpoint` sends a third party none; a server behind a proxy would also have to change `trust_env=False` (`services/mcp.py`). Removing one leaves `tool_call.mcp_server_id` and frozen conversations pointing at nothing. The cost of no: a third server takes a task.
   Recommended: no. Disabling covers stopping a server, and the line stays under `Out`.
   > No: enable and disable only (the user, 2026-11-01). The line stays under `Out`.
2. Can a GitHub write be set to `allow`? `.doc/product-definition.md › Purpose` says anything the agent changes on GitHub needs approval, and this screen is the first place that can undo it: `issue_write` at `allow`, then injected issue text writes with no click.
   A: on `github` only plan 012's five reads may be `allow`; every other tool there, a future one included, offers `ask` and `deny`. The API returns `effects` per tool, so the browser holds no rule. Cost: one constant, one 400, and loosening it takes a code change.
   B: any effect on any tool: no rule, one less test, but the Purpose line becomes a default an admin's click can end.
   Recommended: A. Under B, `effects` and V06 drop out.
   > A: on `github` only the five reads may be `allow` (the user, 2026-11-01).

## Contract

| Endpoint | Request | Response | Errors |
| --- | --- | --- | --- |
| `GET /api/mcp-server` | `query.cursor?`, `query.limit?` | `McpServerPage { items: McpServer[], nextCursor }`, newest first | 400, 401, 403, 500 |
| `GET /api/mcp-server/{id}` | `params.id` | `McpServer` | 401, 403, 404, 500 |
| `PATCH /api/mcp-server/{id}` | `params.id`, `body.enabled: boolean` | `McpServer` | 400, 401, 403, 404, 409 (enabling a third-party server with no pin), 500 |
| `GET /api/mcp-server/{id}/listing` | `params.id` | `McpServerListing { mcpServerId, listingDigest, items: ListingTool[] }`, sorted by name | 401, 403, 404, 409 (`knowledge`, or a listing `listing_problem` refuses), 500, 503 (no answer, or a listing the store cannot hold) |
| `POST /api/mcp-server/{id}/acceptance` | `params.id`, `body.listingDigest: string` (64 lowercase hex) | `McpServer`, status 200 | 400, 401, 403, 404, 409 (`knowledge`, a refused listing, or a live listing that no longer has that digest), 500, 503 |
| `GET /api/tool-policy/{mcpServerId}` | `params.mcpServerId` | `ToolPolicySet { mcpServerId, items: ToolPolicy[] }`, sorted by name | 401, 403, 404, 500 |
| `PUT /api/tool-policy/{mcpServerId}/{toolName}` | `params.mcpServerId`, `params.toolName`, `body.effect: 'allow' \| 'ask' \| 'deny'` | `ToolPolicy`, status 200, created or changed | 400 (a bad effect, or a known tool's effect outside its `effects`), 401, 403, 404 (no such server, or a tool it does not know, checked before `effects`), 500 |

All are `require_role(UserRole.admin)`, rechecked in each handler. Shapes:

- `McpServer`: `{ id, name, enabled, pinStatus: 'not_required' | 'unpinned' | 'current' | 'changed', createdAt, updatedAt }`. No URL and no token. `not_required` is `knowledge`; `changed` is a stored last listing that differs from the pin.
- `ListingTool`: `{ name, change: 'added' | 'removed' | 'changed' | 'unchanged', description, inputSchema, pinnedDescription, pinnedInputSchema }`. Live fields are null on `removed`, pinned fields are set only on `changed` and `removed`. Both schemas are strings the server prints (`json.dumps`, `sort_keys`, `indent=2`, `ensure_ascii=False`): `canonical` calls `1` and `1.0` different and the browser's `JSON.parse` would print them alike and round past 2^53, so a `changed` tool could show two identical versions.
- `ToolPolicy`: `{ toolName, effect: 'allow' | 'ask' | 'deny' | null, effects: ('allow' | 'ask' | 'deny')[] }`. `null` is no row, which denies. The items are the union of the rows and the pin (`knowledge`: its last listing), which is what `a tool it does not know` is measured against.

## UX

- /mcp-server — list — open a server — states: loading `ListSkeleton` of two rows · empty `EmptyState` · error the group's `ErrorState` — tone: calm, dense, precise; the pin status is a `Badge` in words, and enabled or disabled a second one — phone: rows stack, badges wrap under the name
- /mcp-server/:id — detail — review the listing, filled only at `unpinned` or `changed`, otherwise outline; `knowledge` has no review — states: loading `CardSkeleton` per section · empty `EmptyState` in the tools section · error the group's `ErrorState`; a failed policy write is a toast and the select returns to the stored effect — tone: calm, dense, precise; a tool with no row reads as denied in words; enable or disable is outline, beside a line saying a conversation started while a server is off never gets its tools — phone: one column, each tool's name above its select
- /mcp-server/:id/listing — detail — accept the listing, absent when the listing matches the pin — states: loading `CardSkeleton` · empty none, because a listing with no tool is refused · error `ErrorState` with retry, in the segment's own words for a server that did not answer and for a refused listing; a stale accept is a toast and the listing reloads — tone: calm, dense, precise; each tool shows its change as a `Badge`, third-party text as plain text through `visibleText` and never Markdown, and the section above the action states that accepting enables the server, and that existing conversations keep their tools and deny a changed one — phone: one column; text wraps with no inner scroll, no height cap and no sideways scroll, so the action comes after all of it, plan 012's rule for the waiting row

## Steps

### Backend

1. `backend/src/app/models/mcp_server/enums.py`, `type.py`, `models/tool_policy/constants.py` — `PinStatus`, `ToolChange`, the five `github` reads of Question 2; the docstring no longer says no route lists servers.
2. `backend/src/app/services/tool.py`, `infra/scripts/accept_mcp_server.py` — pure: `pin_status`; a per-tool change kind beneath `listing_changes`, whose lines stay, so the wire and the command share one comparison; `effects_for(server, tool_name)`; `listing_problem(tools)` and `TOOL_NAME`, moved from the command, which calls it and loses its no-screen line.
3. `backend/src/app/services/utils/jsonb.py`, `services/mcp.py`, `api/agent/controller.py`, `backend/tests/test_qa_knowledge.py` — `jsonb_safe`, `_holds_nul` moved and widened to non-finite numbers, its two test assertions keeping their meaning; `list_tools` raises `McpUnavailable("unstorable_listing")` after `_in_own_task` returns, because `_session` rewrites anything `work` raises and the reason would never reach the log; it is the one point a run, the review and the command all pass, so a run offers the pin and `call_tool` still denies. The `_answer_tools` log line stops saying NUL alone.
4. `backend/src/app/api/mcp_server/schema.py`, `routes.py` — the models of the table, the digest pattern as in `api/approval/schema.py`; one `add_api_route` per row, gates only.
5. `backend/src/app/api/mcp_server/service.py`, `controller.py` — a `(created_at, id)` page, `find_by_id`, `set_enabled`; the five handlers, each with `_assert_admin`; rules `find_server_by_id` and `known_tool_names`; a log line per write with the account, server and digest, no definition; `read_listing`'s `None` becomes `upstream_unavailable` and a `listing_problem` a `conflict`; the docstrings saying no route, `Only ... calls this` and that `updated_at` means the listing changed all go.
6. `backend/src/app/api/tool_policy/schema.py`, `service.py`, `controller.py`, `routes.py` — the rows of a server; an upsert on `tool_policy_server_tool_key`; the two handlers, the union and `effects_for`, a log line per write; `find_effect` unchanged.
7. `backend/src/app/config/routes.py`, `backend/src/app/openapi.py`, `backend/openapi.json` — both mounts, `COMPONENTS`, `contract`, at the contract stage.
8. `backend/tests/seed_changed_server.py` — `python -m tests.seed_changed_server <name>` (a `_test` or `_e2e` database only): a disabled third-party row at the fake's `/mcp`, a pin on an older `note` description, `tool_definition` set to today's, and a `tool_policy` row at `ask`. The name is unique per journey, never `knowledge` or `github`, so `mcp_server_url_check` holds.
9. `backend/tests/test_mcp_server.py`, `test_tool_policy.py`, `services/test_tool.py`, `services/test_mcp.py`, `db/test_accept_mcp_server.py`, `test_agent_github.py` — the proofs below, on `github` through `fake_mcp.py`: `recorded_tools()` from `github_tools.json`, a test editing `Github.tools` to change one, `lab` where a server has no cap.
10. `backend/AGENTS.md` — the layer map's `mcp_server, tool_policy` line and `The agent`.

### Frontend

1. `frontend/src/shared/api/generated/` — `contract`, once the backend's contract stage has reported.
2. `frontend/src/entity/mcp-server/`, `entity/tool-policy/` — `model.ts` (labels and tones, the no-row label), the queries in `api/`, `ui/mcp-server-row.tsx`, `ui/tool-policy-row.tsx`, `ui/listing-tool.tsx`, which passes the description and the printed schema, each version, through `shared/lib/visible-text.ts`.
3. `frontend/src/feature/accept/` — the mutation echoing the digest, `retry: false` and `networkMode: 'always'` like `feature/approve`, because an accept paused offline must never send itself; the copy table's 409 and 503; its button.
4. `frontend/src/feature/toggle-server/`, `feature/set-policy/` — the `PATCH` and its button; the `PUT` and a labelled `Select` per tool, its options read from `effects`.
5. `frontend/src/widget/mcp-server-list/`, `widget/mcp-server-detail/`, `widget/listing-review/` — each section and its skeleton.
6. `frontend/src/app/(site)/mcp-server/page.tsx`, `[id]/page.tsx`, `[id]/listing/page.tsx`, `[id]/listing/error.tsx`, `app/routes.tsx`, `app/nav.ts` — in the admin group, each loader calling `requireRole`; the segment's boundary after `(site)/search/error.tsx`; an admin-only nav entry.
7. `frontend/tests/unit/mcp-server-routes.test.tsx`, `listing-tool.test.tsx`, `frontend/tests/e2e/mcp-server-support.ts`, `mcp-server.spec.ts`, `screens.spec.ts`, `frontend/AGENTS.md › Auth`, `› Tests` — the routes, the guard and an unreachable API on `stubApi`; hidden characters in a description and a schema key; one journey on a row of its own from `tests.seed_changed_server`, written only to `account.databaseUrl` and disabled again at its end, because `github` and `fixture` are shared by parallel journeys; left out under `E2E_BASE_URL`; `/mcp-server`, then `/mcp-server/github` and `/mcp-server/github/listing` in `SIGNED_IN_ROUTES`, read-only over the seven recorded tools, the longest real text there is.

### Driver

1. `.doc/glossary.md`, before the agents start — `listing`, `pin status`, `toggle` (`feature/toggle-server`), `set policy` (`feature/set-policy`); `accept` gains its route and `feature/accept`. `.doc/architecture.md` — item 9, Change Log. `README.md` — Features, and Usage's accept: the screen, with the command for a shell; no new variable.

## Validation

- V01 — The list and one server answer `knowledge`, an unpinned, a current and a changed server with the right `pinStatus`, `0` against `false` reading `changed` where Python calls them equal, with no URL or token on the wire, and answer while every server is down (AC05) — proof: `backend/tests/test_mcp_server.py::TestRead`, `backend/tests/services/test_tool.py`
- V02 — The review returns the live listing whole, its digest and each tool's change, a changed tool with both versions, `1` against `1.0` printing differently, and `github_tools.json`'s seven with every `x-mcp-header` intact; it stores nothing and reads a disabled server; a server down is a 503, `knowledge` a 409 (AC06) — proof: `backend/tests/test_mcp_server.py::TestListing`
- V03 — An accept with the shown digest pins exactly that listing, enables the row and reads `current` at once, and a new conversation offers the tools; a stale digest, a server down and `knowledge` change nothing (AC05, AC06) — proof: `backend/tests/test_mcp_server.py::TestAccept`
- V04 — A listing with no tool, a repeated name or a name outside `[A-Za-z0-9_-]+` is a 409 at the review and the accept and exit 1 at the command, by one rule, with nothing of it on the wire; a NUL, `NaN`, `Infinity` or `1e400` is a 503 at both and exit 1, and a run with one writes one notice, offers the pin and finishes on `knowledge` (AC05, AC06) — proof: `backend/tests/test_mcp_server.py::TestRefusedListing`, `backend/tests/db/test_accept_mcp_server.py::TestRefusals`, `backend/tests/services/test_mcp.py`, `backend/tests/test_agent_github.py::TestDownServer`
- V05 — An admin's change reaches the next call with no restart: disabling drops a server from the next run and denies a frozen conversation's call and a held approval with no server call, and enabling with no pin is a 409; the policy document names every known tool, one with no row as `null`, and a `PUT` creates or changes the one row, so `allow` runs, `ask` waits, `deny` refuses and a held call denies at the resume; an unknown server or tool is a 404, a bad effect a 400 (AC05, AC06) — proof: `backend/tests/test_mcp_server.py::TestEnabled`, `backend/tests/test_tool_policy.py`
- V06 — `allow` on `issue_write` or `add_issue_comment` is a 400 that writes nothing, `effects` says so, `effects_for` caps a `github` name it has never seen the same way, and the constant equals `0011`'s `allow` rows (AC06) — proof: `backend/tests/test_tool_policy.py::TestEffects`, `backend/tests/services/test_tool.py`
- V07 — Every endpoint is a 401 with no token and a 403 for a `user`, with the envelope's `code` and `requestId`; a handler mounted without its gate still refuses; each write logs the account, server and tool, and no definition (AC06) — proof: `backend/tests/test_mcp_server.py::TestAccess`, `backend/tests/test_tool_policy.py::TestAccess`
- V08 — An admin reads a changed definition whole above the accept button, a hidden character showing as `[U+XXXX]` in each version, accepts, sets a policy and disables the server, and a `user` reaches `/forbidden`; a stale accept shows our copy and the new listing; each screen passes its scan; every gate and the e2e suite pass with no network and no key, and both contract files are committed (AC01, AC06) — proof: `frontend/tests/e2e/mcp-server.spec.ts`, `frontend/tests/unit/mcp-server-routes.test.tsx`, `frontend/tests/unit/listing-tool.test.tsx`, `node scripts/verify.mjs --plan <plan> --reuse`

## Risks

- `visibleText` shows an invisible character, not a look-alike letter, so a Cyrillic `а` still reads as Latin — a change is flagged on bytes and both versions are whole, but a first accept has no earlier version to compare.
- `list_tools` is on every run's path, and a refusal there reports a live server as down — the walk is linear in a listing, and the log's `unstorable_listing` tells it from an outage.
- `allow` removes the approval, so a misjudged read tool runs unattended — Question 2 caps `github`; the row names the effect in words, and `tool_policy` stays enforced in the loop.
- `freeze_prefix` binds a conversation once, so one started while `knowledge` is off never searches, even after it is back on, and with every server off it freezes at `[]` — the detail page says so; `a tool accepted later reaches existing conversations` owns it, and `[]` stays the shape the docs leave unproven.

## Changes during the task

- Contract stage (backend): the list's malformed-`cursor` 400 is tested with Step 5's service, because the shared `PageQuery` does not check a cursor's shape and the data layer's `decode_cursor` does; `limit`'s rules are tested over HTTP at the contract stage.
- Contract stage (backend): `backend/tests/test_openapi.py`'s expected path and component sets gain the new entries; assertions kept, nothing deleted.
- Contract stage (backend): the `controller.py` docstrings saying `no route` changed at this stage, ahead of Steps 5 and 6, which replace the stand-in handlers.
- Backend: a new `tool_policy` row gets a uuid id, not `<server>-<tool>`, because that spelling can collide for hyphenated names.
- Backend: `enabling needs a pin` is enforced inside `set_enabled`'s `UPDATE`, so the check and the write are one statement.
- Backend: the held-approval and disable cases of V05 are proven with `lab` through `settle`, not `github`.
- QA: `frontend/tests/e2e/qa-mcp-server.spec.ts` failed `lint` after QA's report; the driver fixed its two errors, with no change in behaviour.
- Round 1's base is tree `a4c1806009b47eafca29262ea5c58d6d7bd825dc`, red on e2e for two reasons outside the reviews. The `mcp-server` journey raced (line 34 matched the list row, so line 35 ran on the list, where QA's spec had added a second disabled row), which round 1 fixes. `vite preview` died 2 s later, as on plan 006's tree `8ef0320`: 56 tests failed behind it. Cause not found, recorded here. `script "preview" exited with code 9` is bun's low 8 bits of a 32-bit code (measured: `0xC0000409` prints as 9), so this may be a native fail-fast, not a kill. Project code never terminates with 9, `taskkill` gives 1, and 30,000 client and upstream resets on real `vite preview` did not reproduce it.
- Review: the review page shows each tool's stored effect, read from `GET /api/tool-policy/{mcpServerId}` with no contract change, because a `changed` tool at `allow` otherwise keeps running unattended with no sign (`review-security.md`). The driver took this over dropping such a tool to `ask` on accept, which would reopen approvals on every routine re-accept.
- Round 1 (driver): the review's note read `none set` for a tool with no row and showed nothing for a tool new in the listing, where no row denies. Both now read as denied, through `NO_RULE_LABEL`.
- Round 3, past the loop's limit of two, by the user's decision (2026-11-02): the security re-review of round 2 left one P0 open, a `refetchOnMount` read after a 409, and the user chose a third round over accepting it as a P2.
- Round 1 (backend): `set_enabled` refuses a NUL id too, because `PATCH` hit the same `DataError`; `TestHostileInput` now asserts exactly 404 `not_found`, not `400 or 404`.
- Review: `.plan/000-backlog.md`'s `reading a server's listing is rate limited per admin` widens to the accept, which makes the same live read (`review-security.md`).
- Backend: `backend/tests/rewrite_app.py` is new: pydantic prints `NaN`, `Infinity` and `1e400` as `null`, so a fake cannot send them, and V04 swaps the bytes of a fake's answer to reach the client. `backend/tests/test_seed_changed_server.py` covers Step 8's seed.
