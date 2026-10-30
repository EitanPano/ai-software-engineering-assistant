# Glossary

Canonical domain terms and their approved short forms. Code, routes, tables, plans and
docs use these words and no synonyms. Add a term here before using it anywhere else.

## Core Terms

| Term | Meaning | Used as |
| --- | --- | --- |
| session | A refresh-token record: hashed token, rotation state, expiry | table `session`, model `session` <!-- auth --> |
| caller | The authenticated principal on a request: `{ id, role, sessionId }` | the resolved caller <!-- auth --> |
| OTP | A six-digit one-time code sent to a target; valid 10 min, 5 attempts | module `auth` <!-- auth --> |
| target | An email or phone a message or OTP is sent to: `{ type, value }` | OTP endpoints, the user entity's public type (`ContactTarget`); the communicate layer calls the address `to` <!-- auth --> |
| module (reference) | The shipped CRUD module `api/module/` that a developer copies | `api/module/`, `models/module/` |
| <!-- FILL: term --> | <!-- FILL: one-line definition --> | <!-- FILL: table `x`, route `/api/x`, module `x` --> |

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
