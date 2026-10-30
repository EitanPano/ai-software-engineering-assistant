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
| module (reference) | The shipped CRUD module `api/module/` that a developer copies | `api/module/`, `models/module/` |
| user | A person with an account, role `user` or `admin` | table `user`, route `/api/user`, module `user` |
| conversation | One chat thread owned by a user; never called a session, which is a refresh-token record | table `conversation`, route `/api/conversation`, module `conversation` |
| message | One turn in a conversation; together they are its conversation history | table `message` |
| agent | The loop that reads a conversation, calls tools and writes the answer | module `agent` |
| run | One execution of the agent for one user message | table `run`, route `/api/run`, module `run` |
| run event | One persisted step of a run, streamed over SSE and replayed on reconnect | table `run_event` |
| tool call | One request by the agent to execute a tool, with its arguments and result | table `tool_call` |
| approval | A human's decision on a tool call | table `approval`, route `/api/approval`, module `approval` |
| tool policy | The rule that allows, asks about or denies a tool | table `tool_policy`, route `/api/tool-policy`, module `tool_policy` |
| MCP server | A Model Context Protocol server the agent's tools come from | table `mcp_server`, route `/api/mcp-server`, module `mcp_server` |
| knowledge base | Every chunk from every source, searched by the agent | MCP server `knowledge` |
| source | A connected GitHub repository at a ref | table `source`, route `/api/source`, module `source` |
| document | One file from a source | table `document` |
| chunk | A searchable slice of a document, with its line range, keyword index and embedding | table `chunk` |
| hybrid search | Semantic and keyword search fused with reciprocal rank fusion (RRF) | module `search`, route `/api/search` |
| memory | Long-term knowledge about a user, distinct from conversation history | table `memory`, route `/api/memory`, module `memory` |
| eval case | One question with its expected chunks and expected answer | table `eval_case` |
| eval run | One execution of the eval cases, with its scores | table `eval_run`, route `/api/eval-run`, module `eval` |
| approve | Allow a pending tool call to execute | `feature/approve` |
| reject | Refuse a pending tool call; the agent receives a denied result | `feature/reject` |
| connect | Add a source and index it | `feature/connect` |

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
