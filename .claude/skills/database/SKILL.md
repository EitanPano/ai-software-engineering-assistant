---
name: database
description: Choose, add or change the data layer or the cache store. Use when choosing a database engine, when a plan introduces an entity, table, collection, index or migration, when writing a data-access file, when a test needs the database or the cache, when adding Redis or Valkey, or when seeding local data. Covers the rules for every engine: the data-model source, store clients and their Resource contract, the test database, migrations, and Postgres and MongoDB naming.
---

# Database

The server template ships an in-memory store behind two file seams, one for the database
and one for the cache; nothing survives a restart. The engine is chosen once, in the
bootstrap, and recorded in `.doc/architecture.md` under Data store. Everything under "Every
engine" holds whatever was chosen. The client library, the files and the scripts are the
package's: `backend/AGENTS.md › Adding the data layer`.

The engine is a catalog provider, chosen at the bootstrap or added later by the data-layer
task below. `docker compose up -d --wait <service>` starts the database service for local
work. `testDb`, `migrate` and `e2eDb` exist once a database does. Commands are always resolved from
`.fullstack/catalog.yaml`: when the bootstrap wired no database, the data-layer task adds the
scripts (`testDb`, `migrate`, `e2eDb`), names them in `AGENTS.md › Adding the data layer` and
in the backend report's `Commands:` line, and the driver writes them to the catalog. The
production `migrate` run in the stack is in the `deployment` skill (section 4).

## Choosing (bootstrap)

Ask the user one question: Postgres, MongoDB, or decide later.

- Postgres when the data is relational (many entities referencing each other),
  transactions span several writes, or reporting queries are expected.
- MongoDB when records are document-shaped (nested, varying fields) and read mostly by
  id or owner.
- Decide later when the first tasks need no persistence; the orchestrator refuses to plan
  a task that stores data until the section is filled. The in-memory store keeps serving
  and the first backlog task adds the engine.

The Data store answer in `.doc/architecture.md` records the engine the user names (or
"decide later") and the client library (for example "Postgres 17 with an ORM" or "MongoDB 8
with the official driver"). Whether the server template lists a provider is a separate
fact. When it lists one for the engine, the bootstrap generates it wired
(`--capability database=<id>`): that is the data-layer task already done, and no such task
is written. The package's `AGENTS.md › Adding the data layer` then describes what exists and
how to change the model, and the rules under "Every engine" and "What the shipped code
assumes of the store" still bind every later change. When it lists none, the
first backlog line is `- [ ] add the <engine> data layer`, with ` | stack:backend` appended
only when the stack has no frontend (on a stack with one it is a full-stack line, see item 7
of the data-layer task); for "decide later" it is the same line with the engine left for the
task to fill (`add the data layer`).

## The data-layer task

Only when the bootstrap wired no provider: `.fullstack/catalog.yaml` has `providers: {}` and the
task is the backlog line `add the <engine> data layer` or `add the data layer`. Its eight
deliverables, the e2e database chain included, are in
`.claude/skills/database/data-layer-task.md`. Read that file before planning or starting the
task; no other task needs it.

A provider wired at the bootstrap is this task already done, except item 8 (the change-log line
and the Data Model section), which still falls to the bootstrap. Skip to "What the shipped code
assumes of the store" and "Every engine" for the rules that keep binding.

### What the shipped code assumes of the store

The auth and user modules were written against the in-memory store; the rewrite keeps these
properties, or a race the memory store hides reaches production:

- **Sessions.** Rotating a session is a conditional update (matching the id, the token
  hash and not revoked, returning the row): exactly one concurrent rotation wins and the
  loser re-reads the record. Revoking every session of a user is one filtered update. The
  grace token is a sealed string column (the code encrypts it).
- **User uniqueness.** Unique indexes on email and on **verified** phone only (a partial
  or sparse index limited to verified rows). An unverified claim does not block others, so
  a plain unique index on phone is wrong.
- **Seed.** The first admin is made by the seed script through the user module's public API.
- **Counters.** An atomic increment sets the TTL on the **first** increment only; an
  increment plus expire on every call makes the window slide, and a non-atomic pair can
  leave a key without a TTL, a permanent lockout.
- **One-time codes.** Single use needs an atomic get-and-delete, so two concurrent
  submissions cannot both succeed. Attempts are incremented before the code is compared.

## Every engine

- **One data-model source.** The entity's stored-record type in `models/<name>/` is the
  declaration. Engines that define models in code keep the storage mapping in the module,
  written so the type checker holds it to that type; engines whose model is the migration
  history keep one schema file and map rows to the type in the data-access file.
  `.doc/architecture.md` Data Model lists the same entities in prose; the code wins on
  conflict.
- **Store access in one place.** The db and cache seams are imported only by a module's
  data-access and storage-mapping files, by shared capabilities and by `infra/`; lint
  enforces it. A script may import storage mappings (index definitions).
- **A store is a Resource.** Every store client exports one and is listed in the
  dependencies. Boot connects with bounded retry (10 attempts, 5 s each), readiness pings
  (2 s), shutdown closes. The client file obeys four rules: no I/O at import (constructing
  the client must not connect, since `check` imports the app without Docker); connecting
  is retry-safe and releases what it allocated when it rejects; the driver's own connect
  timeout is below the attempt timeout and its initial-connect retry is off, so one attempt
  is one attempt; the ping is the cheapest round trip, with a driver-level timeout.
  Reconnecting after a drop is the driver's job. An unreachable store surfaces as
  `upstream_unavailable`.
- **One data-access file per module (the module's `service`).** It holds every query for
  the module, takes and returns plain records, never maps to HTTP or response shapes; the
  controller does the mapping and the domain errors. The collection or table handle is
  obtained per call, never at module scope. It is private to the module: a module that
  needs another module's data calls that module's controller, and each such call is its
  own unit of work.
- **Cache-aside stays in the data-access file.** It may use the cache seam and the logger
  for exactly that; no other module file may.
- **Shape of every record.** A string `id` the controller generates, `createdAt` and
  `updatedAt` set by the controller on every write. Tenanted products store the owner id on
  every record and every query filters by it. Soft delete is a nullable `deletedAt` that
  every read filters out.
- **Indexes.** One for every field a query filters or sorts on, including the
  `(createdAt, id)` pair that cursor pagination sorts by, the owner id, and a unique index
  for every business key.
- **Changes ship with the task.** A data-model change is not done until the task ships what
  makes it real: a migration for SQL, an index definition for MongoDB. Never apply a change
  to a database by hand. Additive first: add the field nullable, backfill, then tighten;
  never remove a field in the same change that stops writing it.
- **Destructive operations are a human's job.** Dropping, truncating or resetting a
  database, or flushing a cache, is never done by an agent; the guardrails refuse the
  commands. Say so in the plan's Rollback section.
- **Transactions.** A transaction belongs to one module's controller, which calls its
  `service` inside it; it never spans modules.
- **Seed data**, when needed, is an idempotent script, never run in production; a script
  may call controllers, never a `service`.

## Test database

Tests never touch the development database. The same local service hosts a second database
named `app_test`. With the in-memory store, store-backed suites run under `check`. Once the
package has a database, `check` skips them and they run only under `testDb`, against a
database whose name marks it as the test database. The diff checks accept the one
skip the template ships (`skipif` with `reason=STORE_SKIP_REASON` in `tests/store.py`); `testDb`
fails on any skipped test. A cache test uses a separate index or
database and flushes only that. A test opts in through the database block the
package's `AGENTS.md › Tests` names, which resets the test database before each test. Never
fake a data-access file with a process-global module mock. In production a human or the
deploy pipeline runs `migrate` before the new image serves traffic; record who in
`.doc/architecture.md`.

## Engines

- SQL (Postgres): snake_case singular tables and columns (`post`, `post_comment`); SQL
  migration files applied in order by `migrate`; an index ships in the migration that needs
  it. Commands that push a schema without a migration are refused by the guardrails. A
  Compose service with a healthcheck, and `db/init.sql` that creates the `app_test`
  database; the test reset empties tables and never drops a database.
- MongoDB: singular camelCase collections and fields; index definitions in code, created
  by `migrate`; a migration script when a stored shape changes. A standalone Compose
  service; the test reset deletes documents and never drops. Transactions need a replica
  set: a plan that needs two atomic writes says so.
- Cache (Redis or Valkey), its own backlog line, never in the bootstrap, only when a plan
  needs one (more than one instance, a hot read path, an expensive computed list,
  idempotency keys): a `cache` Compose service and its URL variable; typed get, set with
  a TTL, del, atomic incr with the TTL set on the first write. Keys are prefixed with the
  module name. A miss is never an error; a failure degrades to the database, logged once
  at `warn`; a write deletes the entry's key.
