# Product Definition

Fill every `<!-- FILL: … -->` marker before the first plan. The `bootstrap-project` skill
walks this file with you; the orchestrator refuses to plan against a section that still
holds a marker. Delete a marker only by replacing it with a decision.

## Purpose

An AI Software Engineering Assistant, built as a proper agent platform rather than a basic
chatbot. Engineers connect GitHub repositories, ask the agent about that code and get answers
cited to file and line. Anything the agent wants to change on GitHub needs their approval.

## Problem Statement

A typical AI chatbot does not know a team's codebase, forgets between chats, cannot show how
good its answers are and cannot be trusted to act. Engineers paste code into a chat window
and check every answer by hand.

## Value Proposition

An agent with significantly more engineering depth than a typical AI chatbot: its retrieval
and answers are measured, its memory can be inspected, and its sensitive actions wait for a
human.

## Target Users

- Primary users: software engineers who want answers about a codebase and help planning and
  making changes to it.
- Secondary users: admins who manage sources, MCP servers, tool policy and evals.

## Product Scope

- In scope (v1):
  1. Multiple MCP servers: the agent uses our own `knowledge` MCP server and GitHub's official
     MCP server.
  2. Hybrid RAG: combining semantic and keyword search over connected GitHub repositories.
  3. Agentic RAG: the agent decides when to retrieve more information.
  4. Persistent agent memory: conversation history is distinct from long-term knowledge.
  5. Tool execution permissions: human approval for sensitive actions.
  6. Streaming responses: showing intermediate tool activity.
  7. Evaluation pipelines: measuring retrieval quality and answer correctness.
  8. Structured outputs: using schemas to validate results.
- Out of scope (v1): code or shell execution, organisations and multi-tenancy, hosts other than
  GitHub, IDE plugins, scheduled agents.

## Auth and Tenancy

- Authentication: email+password.
- Authorization: roles `user` and `admin`. A `user` chats, searches the knowledge base and
  decides approvals in their own conversations. An `admin` also manages sources, MCP servers,
  tool policy and evals.
- Tenancy: single tenant. The knowledge base is shared; conversations and memories are private
  to the owning user.

## Non-functional Requirements

- Accessibility: WCAG 2.2 AA.
- Browsers: last two versions of Chrome, Firefox, Safari, Edge.
- Performance: first page under 2 s on a 4G connection; first streamed event under 1 s after
  a message is sent.
- Locale: single language, English.
- Search and sharing: no. The product sits behind sign-in, so no public page needs search
  engines or a share preview.
- Data retention and privacy: conversations and memories are kept until the user deletes them.
  API keys are never stored in messages, memories or run events. Prompts and retrieved code are
  sent to Anthropic, and connected code to Voyage AI for embedding.

## Design

The brief every frontend task follows (`.claude/rules/ui-and-styling.md`); a `figma:<url>`
backlog marker overrides it for one task. The bootstrap passes the display name, colours,
radius, type, density and default theme to the frontend generator as flags.

- Tone: calm, dense, precise.
- Reference apps: Linear, GitHub.
- Display name: AI Software Engineering Assistant
- Primary colour: #0f766e
- Neutral colour: #64748b
- Radius: md
- Type: inter
- Density: compact
- Primary viewport: desktop first; 1280 px is the target and 768 px stays usable.
- Default theme: system.

## Acceptance Criteria

Each criterion must be provable by a test or a command. Keep the numbering stable; QA
reports against it.

- AC01 — Quality gates: every package's `check` command is green, and the
  e2e suite passes.
- AC02 — Streaming: a signed-in user sends a message and sees text and each tool call's start
  and result as they happen; a client that reconnects receives the events it missed, in order
  and once each.
- AC03 — Hybrid RAG: on the fixture repository, a query only keyword search can match (an exact
  identifier) and a query only semantic search can match (a paraphrase) both return the
  expected chunk in the top 5.
- AC04 — Agentic RAG: when a first search does not answer the question the agent searches
  again, each search is recorded as a tool call, and every claim in the answer cites a file and
  line. When the knowledge base holds no answer, the agent says so.
- AC05 — MCP: the agent discovers and calls tools from both the `knowledge` MCP server and
  GitHub's MCP server; when one is down the run reports it and continues with the other.
- AC06 — Permissions: a tool call that needs approval does not execute until a human approves
  it with its exact arguments in view; a rejection reaches the agent as a denied result; a
  pending approval survives a server restart; a tool with no policy is denied.
- AC07 — Memory: a fact stated in one conversation is used in a new conversation by the same
  user and never for another user; a user can list and delete their memories, and a deleted
  memory is not used again.
- AC08 — Evals: an eval run reports recall@k, MRR and nDCG for retrieval and a correctness
  score per case, is stored, and an admin can read it; a non-admin cannot.
- AC09 — Structured outputs: every result of a declared type validates against its schema; a
  response that fails validation is retried or surfaced as an error, never shown as valid.

## Ready to plan

- [x] No `FILL` marker remains in Purpose, Target Users, Product Scope, Auth and Tenancy, Design or
      Acceptance Criteria, nor in the Search and sharing line.
- [x] `.doc/architecture.md` has its data model and API sections filled.
- [x] `.doc/glossary.md` names every entity used above.
