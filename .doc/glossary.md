# Glossary

Canonical domain terms and their approved short forms. Code, routes, tables, plans and
docs use these words and no synonyms. Add a term here before using it anywhere else.

## Core Terms

| Term | Meaning | Used as |
| --- | --- | --- |
| session | A refresh-token record: hashed token, rotation state, expiry | table `session`, model `session` |
| caller | The authenticated principal on a request: `{ id, role, sessionId }` | the resolved caller |
| OTP | A six-digit one-time code sent to a target; valid 10 min, 5 attempts | module `auth` |
| target | An email or phone a message or OTP is sent to: `{ type, value }` | OTP endpoints, the user entity's public type (`ContactTarget`); the communicate layer calls the address `to` |
| user | A person with an account, role `user` or `admin` | table `user`, route `/api/user`, module `user` |
| conversation | One chat thread owned by a user; never called a session, which is a refresh-token record | table `conversation`, route `/api/conversation`, module `conversation` |
| message | One turn in a conversation; together they are its conversation history. Roles: `user`, `assistant` and `tool_result`, which the API receives as `user` and the wire never shows | table `message` |
| agent | The loop that reads a conversation, calls tools and writes the answer | module `agent` |
| run | One execution of the agent for one user message | table `run`, route `/api/run`, module `run` |
| run event | One persisted step of a run, streamed over SSE and replayed on reconnect | table `run_event` |
| lost run | A run still active whose process is gone, ended as `interrupted` by the sweep at the next boot | `fail_lost_runs` in module `run` |
| tool call | One request by the agent to execute a tool, with its arguments and result | table `tool_call` |
| tool definition | What a tool offers the model: its `<server>__<tool>` name, description and input schema | `mcp_server.tool_definition`, `conversation.tool_definition` |
| approval | A human's decision on a tool call | table `approval`, route `/api/approval`, module `approval` |
| awaiting approval | The status of a run, and of a tool call, that waits for a person's decision | `run.status`, `tool_call.status` value `awaiting_approval` |
| pending turn | The assistant turn a paused run keeps whole, with the results already known, stored as two turns when the run resumes | `run.pending_turn`, model `PendingTurn` |
| arguments digest | SHA-256 of a held call's canonical stored arguments, echoed by the decision so it binds to what the person was shown | `approval.arguments_digest`, field `argumentsDigest` |
| tool policy | The rule that allows, asks about or denies a tool | table `tool_policy`, route `/api/tool-policy`, module `tool_policy` |
| MCP server | A Model Context Protocol server the agent's tools come from | table `mcp_server`, route `/api/mcp-server`, module `mcp_server` |
| pin | The tool definitions of a third-party MCP server that an admin accepted; only pinned definitions are offered, and a changed one is denied | column `mcp_server.pinned_tool_definition` |
| accept | An admin's act of pinning a server's live listing after reading it, which also enables the server | command `accept_mcp_server` |
| GitHub gateway | Our process in front of GitHub's MCP server: the only one that holds the GitHub token, and it adds that token to each forwarded request | entry `app.github_gateway_main`, Compose service `github-gateway` |
| knowledge base | Every chunk of every `ready` source, searched by a signed-in person and by the agent | route `/api/search`, MCP server `knowledge` |
| source | A connected GitHub repository at a ref | table `source`, route `/api/source`, module `source` |
| document | One file from a source | table `document` |
| chunk | A searchable slice of a document, with its line range, keyword index and embedding | table `chunk` |
| symbol | A named definition, such as a function or class, that one chunk holds | column `chunk.symbol` |
| parse worker | The child process that runs `tree-sitter` on repository files, with no secrets and a deadline | `services/parse_worker.py` |
| fixture repository | The small repository the fakes serve, which tests and evals index | `tests/fixture_repository.py` |
| hybrid search | Semantic and keyword search fused with reciprocal rank fusion (RRF) | module `search`, route `/api/search` |
| search hit | One chunk a search returns, with its repository, file, line range and ranks | `SearchHit`, `entity/chunk` |
| memory | Long-term knowledge about a user, distinct from conversation history | table `memory`, route `/api/memory`, module `memory` |
| eval case | One labelled question, of a kind, pinned to a commit; the correctness task adds its expected answer | table `eval_case` |
| expected chunk | A label: lines of one file at a pinned commit that a good answer must contain; never a chunk id | `EvalExpectedChunk`, column `eval_case.expected_chunk` |
| identifier, paraphrase, no_answer | The kinds of eval case: names a symbol; shares no identifier with its lines; cannot be answered from the corpus, so it enters no mean, only the cosine evidence | column `eval_case.kind` |
| eval run | One execution of the eval cases, with its corpus, settings and scores | table `eval_run`, route `/api/eval-run`, module `eval` |
| approve | Allow a pending tool call to execute | `feature/approve` |
| reject | Refuse a pending tool call; the agent receives a denied result | `feature/reject` |
| connect | Add a source and index it | `feature/connect` |
| start | Begin a new empty conversation | `feature/start-conversation` |
| send | Add a user message to a conversation and start a run | `feature/send-message` |
| search | Find the chunks of `ready` sources for a text | `feature/search` |
| measure | Start an eval run | `feature/measure` |

## Actions

Features are named by actions, so a product's glossary also holds verbs. List each action
beside the nouns, in the same table, with `feature/<action>` in the Used as column (for
example `refresh`: re-read an entity's data, `feature/refresh-health`).

## Rules

- One word per concept. If two candidates exist, pick one here and never use the other.
- Singular everywhere: the term names one thing; collections are implied by context.
- Prefer the short canonical form (`org`, not `organization`) and record the long form in
  the Meaning column.
- Keep this file aligned with `.claude/rules/naming.md`.
