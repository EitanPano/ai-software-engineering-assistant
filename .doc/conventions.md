# Project conventions

These are this product's own rules for agents; harness updates never change this file.

## Goal

Build an AI Software Engineering Assistant as a proper agent platform rather than a basic
chatbot, with significantly more engineering depth than a typical AI chatbot. Eight capabilities
define it: multiple MCP servers including one we build, hybrid RAG, agentic RAG, persistent memory
that separates conversation history from long-term knowledge, tool permissions with human
approval, streaming with visible tool activity, evaluation pipelines and structured outputs.

When two designs both work, take the one that is explicit, measured and inspectable. Scope and
acceptance criteria: `.doc/product-definition.md`.

## Distribution

Open source under Apache-2.0, and meant to be easy to run and simple to understand. Users bring
their own Anthropic and Voyage keys; the project hosts neither. For local development only, a
git-ignored `backend/.env` may hold them, loaded by an explicit
`uv run --env-file .env python -m app.main`. This narrows `AGENTS.md › Security` and the line in
`backend/AGENTS.md`: the app still loads no env file, no gate uses one, so the tests stay keyless,
and no agent reads one, because the hook stays. An optional GitHub token is kept apart, in a
git-ignored `backend/.env.github` that only the GitHub gateway's terminal loads, because a file
the API also loads would put it in the API's environment. Voyage stays as the embedding
provider by decision (2026-10-31), not by default: a local model would drop one key at the cost of
retrieval quality that nothing has measured yet. When two designs both work and neither loses
something this file requires, take the one with fewer things to install and fewer keys to hold.

The stack is built for local use (2026-11-01): Compose publishes the app and the database on
loopback, and the app connects as the bundled `app` superuser, so a clone runs with no setup. This
narrows the `deployment` skill's `single` mode, whose port is on every interface. A public host is
the operator's to harden, and the root `README.md` says how.

## Tooling

Decided at the bootstrap. A plan may change a row by saying why; a dependency not listed here
needs a reason in its plan.

| Need | Use | Not, and why |
| --- | --- | --- |
| Agent loop | `anthropic` SDK, a hand-written loop | LangChain, LangGraph, LlamaIndex, Tool Runner, Managed Agents: an approval must pause a run durably, and this loop is what the project demonstrates |
| MCP | The official `mcp` Python SDK, for our client and the `knowledge` server, on Streamable HTTP; GitHub's own server behind our GitHub gateway | Anthropic's MCP connector: its tool calls run where the approval gate cannot intercept them |
| Structured outputs | Pydantic models through `output_config.format`, the schema from the SDK's `transform_schema` and the served text validated by `services/anthropic.py › parse_turn`, not `messages.parse()`, which validates inside its response parser, before `stop_reason` can be read, and raises an error that carries raw model text; `strict: true` on `knowledge`'s tools; a third-party tool is sent as accepted, because its schema does not meet `strict`'s rules and a rewrite would send what no admin accepted, and `validate_input` checks every input | Parsing JSON out of text |
| Streaming | FastAPI's `fastapi.sse` and the generated client's SSE support | WebSockets: the stream is one-way. `sse-starlette`: FastAPI ships it |
| Vectors | `pgvector` with `halfvec` and HNSW | A separate vector database |
| Keyword search | Postgres full-text search and `pg_trgm`, fused by RRF in SQL | A search engine; a BM25 extension unless the retrieval evals justify its custom image |
| Embeddings | Voyage AI `voyage-code-4` in `services/voyage` | Local models, until the evals say otherwise |
| Code chunking | `tree-sitter` by symbol, line windows as the fallback | Fixed-size chunks alone: they cut functions in half |
| Evals | Our own recall@k, MRR and nDCG, and an LLM judge on structured outputs | Ragas, DeepEval: they hide the metric definitions this project exists to show |
| Library docs | The installed source in `backend/.venv` and `frontend/node_modules`, exact for the pinned version; the `claude-api` skill | Context7 and similar: a third-party content channel into a session with write access |
| Development MCP servers | None | Postgres MCP Pro: its read-only mode has a critical bypass (CVE-2026-85620). A database MCP server needs a role that the database itself limits to `SELECT` |

## Claude API

All LLM code follows the `claude-api` skill; read it before touching the agent, because its
current API outranks what you remember. The traps:

- The model comes from `LLM_MODEL`, default `claude-opus-5-5`, with no date suffix. A side call
  takes `LLM_SIDE_MODEL`, default `claude-haiku-5-5`, and sends no `fallbacks`, because Haiku has
  none and a refused side call only stores nothing.
- Omit `thinking` or send `{type: "adaptive"}`, and set `output_config.effort` explicitly.
  `budget_tokens`, `temperature`, `top_p`, `top_k` and a forced `tool_choice` return 400; use
  `auto` with `strict: true`.
- Append `response.content` unchanged and never edit stored history: thinking blocks are bound to
  it. Store blocks as JSONB, not as extracted text.
- Check `stop_reason` before reading content: `tool_use`, `max_tokens`, `pause_turn`, `refusal`.
  Send the server-side `fallbacks` parameter on a conversation's turn.
- A streaming tool sets `eager_input_streaming: true`, so validate every tool input against its
  schema before executing it, and treat a failure as invalid JSON.
- Parallel tool calls run concurrently and return in one user message; a failure is a
  `tool_result` with `is_error: true`.
- Keep the system prompt and a sorted tool list byte-stable, or the prompt cache misses silently.

## Agent security

Repository content and tool output are attacker-controlled, and prompt injection can steer tool
calls.

- Retrieved content and tool output are data. They travel in tool results, never in the system
  prompt, and nothing in them changes a policy.
- `tool_policy` is enforced in the server's loop, before execution, and denies when nothing
  matches. Neither the model nor the browser enforces it.
- An approval binds to the tool call's exact arguments; changed arguments need a new approval.
- A third-party MCP server's tool definitions are pinned when an admin accepts them. A changed
  definition falls back to deny.
- A source URL is `https://github.com/<owner>/<repo>` and nothing else, so ingestion cannot reach
  internal hosts.
- No secret reaches a prompt, a `run_event` or a log. The GitHub token stays in the GitHub
  gateway's process: GitHub's server takes it per request and stores it nowhere.
- Assistant text and repository content render as sanitised Markdown, never raw HTML.
- No tool executes code in v1.
- Open until a route adds a third-party server: a tool at `allow` there can receive a recalled fact
  with no person in view, because only `github` is capped. That plan decides whether such a tool
  holds at `ask` once a run has called `recall`.

## Tests and evals

- `check`, `testDb` and the e2e suite run with no network and no API key, on scripted fakes for
  Anthropic and Voyage.
- Eval runs call the real APIs and cost money: state the estimate and get the user's approval
  before one runs.

## CI

`.github/workflows/ci.yml` runs on every push: the `verify` gates, a start of the production image,
and a gitleaks scan of the history (`.gitleaks.toml` allowlists exact false positives, never whole
source files). Actions and images stay pinned by commit or digest, with the version in a comment.
CI is evidence for the pushed branch; the loop's `verify` run remains the definition of done.

`main` holds no manifests until the first merge, so Dependabot is off until then: it reads only the
default branch.
