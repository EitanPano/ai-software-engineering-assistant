---
name: writing-plans
description: Create, revise, or supersede an implementation plan in .plan/. Use whenever the user asks for a plan, an approach, or a design doc for a task, when revising an existing plan after feedback, or when the dev loop asks the orchestrator for a plan. Covers the .plan/ lifecycle, the filename, required metadata and sections, and sizing.
---

# Writing Plans

`.plan/` at the repository root is the source of truth for plans. `000-backlog.md` is
the task queue; every other file is a plan. Copy `template.md` from this directory and
fill it; do not invent a different shape.

## Before writing anything

1. Read the change log of `.doc/architecture.md` and the plans it cites for the areas the task
   touches, not every plan. A new plan builds on decisions already made.
2. Read `.doc/product-definition.md` (acceptance criteria, scope, auth and tenancy),
   `.doc/architecture.md` (data store, data model, API) and `.doc/glossary.md` (names).
3. If any section you depend on still holds a `<!-- FILL: … -->` marker, do not plan.
   Write a one-line plan whose only content is `Status: blocked` plus the marker you need
   answered, to the draft path `.orchestrate/<slug>/plan.md`, and say so.

## Filename

`NNN-YYYY-MM-DD-<topic>.md` with a sequential numeric prefix: `001`, `002`, `003`.
Example: `.plan/003-2026-08-03-comment-thread.md`.

## Required metadata

```
Status: draft | active | done | superseded | blocked
Owner:
Last updated: YYYY-MM-DD
Branch: feat/<slug>   (the driver writes it at promotion)
Base: <commit>   (the driver writes it at promotion: the commit the branch was cut from)
Stages: backend, frontend, qa   (omit backend for a stack:frontend task, frontend for a stack:backend task)
Retired: `<exact name or path>`, … | none   (product tasks; see below)
```

`Retired:` lists, in backticks and comma-separated, the exact names and paths the task renames or
removes (a role value, a route, a file, an identifier); `none` when it retires nothing. `verify`'s
`retired-terms` check fails when a listed string remains in the tree, so list a term only when no
legitimate use of it should survive. Retire a role value in literal form (`'admin'`,
`UserRole.admin`), never as a bare word an entity or a path also uses (`user`). Harness plans omit
the line.

The orchestrator writes the plan as a draft to `.orchestrate/<slug>/plan.md` (git-ignored). The
driver promotes it to `.plan/NNN-YYYY-MM-DD-<slug>.md`, with the next free number, and writes
`Base:` when it cuts the task's branch. Use the `Base:` placeholder until then.

New plans start as `Status: draft`. Only the human flips a plan to `active`, by editing
the file. The review and QA stages run in parallel after the implementation stages and are not
listed.
Implementers and QA read the task's change as `git diff <Base>`, reviewers the review
package (`dev-loop` section 4): on a branch that already carries
earlier committed tasks, `git diff main` would show those too. When the user delegates
approval, the driver adds `Approval: delegated (<date>, <the user's words>)`.

## Required sections

In this order, with these exact headings:

`Goal` · `Scope` · `Assumptions` · `Open Questions` · `Contract` (when the API changes) ·
`UX` (when there is a frontend stage) · `Steps` · `Validation` · `Risks` ·
`Changes during the task`

- `Rollback` follows `Risks` only when a migration or a data change ships.
- `Contract`: each endpoint as `METHOD /api/<entity>[/{id}]`, its request fields, its response
  fields, and the error codes it can return. The backend agent implements exactly that list;
  the frontend agent consumes the generated types.
- `UX`: one line per route, in this form (patterns and tones: the `ui-design` skill). No copy
  strings.

  `- /<route> — <pattern> — <primary action> — states: loading <…> · empty <…> · error <…> — tone: <…> — phone: <…>`

  The pattern is one of `list`, `detail`, `form`, `auth`, `dashboard` (a dashboard or a table
  view), `confirm` (a destructive confirm), `landing` (a home or content page). Empty, loading and error are states, not patterns.
- `Steps`: per package, one line per module or feature.
- `Changes during the task` is empty at the start; the driver writes it.

## Content rules

- Repository-relative paths only.
- Name files to create or change per package, following the layout in `AGENTS.md`,
  `backend/AGENTS.md` and `frontend/AGENTS.md › Where does X go`
  (`backend/src/api/<name>/…`, `backend/src/models/<name>/…`,
  `frontend/src/entity/<noun>/`, `feature/<action>/`, `widget/<section>/`,
  `app/(group)/<route>/`). A plan that puts logic in the routing layer, a fetch call
  in a UI component, or a query in a route handler is wrong.
- Every `Validation` item has the form `- V01 — <statement> (AC<n>) — proof: <test name | command>`.
  QA runs the list as its checklist; "the code looks right" is not a proof.
- Every `Open Questions` item ends with `Recommended: <answer>`.
- The approver's answer goes directly under its question as blockquote lines (`> <answer>`). The
  size caps count the plan without them: `grep -vc '^[[:space:]]*> ' <plan>`.
- Generated artifacts belong in `.orchestrate/`. Never create a `docs/` directory.
- Respect the task's markers: a `stack:frontend` task plans no backend work; a `stack:backend` task plans no frontend work.

## Sizing a product task

- A product task is one backlog line and its plan is sized for it. A plan whose `Stages:`
  names no role agent (a harness plan) is exempt.
- The scope is the backlog line and the acceptance criteria it names. Pagination, rate limits,
  caching and other hardening an AC does not ask for go under `Out` as a proposed backlog line
  (`- [ ] <title>`); the driver adds it to the backlog on the user's yes.
- At most 6 `Assumptions` of one line each, at most 8 `Validation` items (each naming its AC)
  and at most 3 `Open Questions` of at most 5 lines each. A question with a conventional
  default is an Assumption, not a question.
- `Steps` name files, one line each, with no copy strings and no code beyond the Contract
  table; rationale is one line under Assumptions.
- Target 80 lines, cap 120 (`grep -vc '^[[:space:]]*> ' <plan>`: answer lines do not count); the driver counts Validation items with
  `grep -c '^- V[0-9]'`. Above the cap, plan the first half and propose the rest
  as backlog lines under `Out`, and say so in the response, above the plan-path line (the
  last line stays the path). Harness plans stay exempt.

## Superseding a plan

Set the old plan to `Status: superseded` with a link to the replacing plan, and say in
the new plan which decisions it keeps.
