# Move the database to Postgres 18 with pgvector and add grant_admin

Status: done
Approval: delegated (2026-10-30, "Approve, refuse unverified")
Owner:
Last updated: 2026-10-30
Branch: chore/move-database-postgres-18
Base: 92c14d4fe5a3148427e5105044b1b2c4bc010c95
Stages: backend, qa
Retired: none

## Goal

The `database` service runs Postgres 18 with `pgvector`, and a person with shell access can make the first admin. Users see no change and AC01 stays green. `admin can connect a GitHub repository to the knowledge base` needs both, and `.doc/architecture.md`'s engine line stops assigning this move to that task.

## Scope

- In:
  - The Compose image, pinned by digest, on a new volume at `/var/lib/postgresql`.
  - `vector` enabled by a migration, with `TestTheEngine` proving the engine.
  - `grant_admin` with its tests, and the docs that name the engine.
- Out:
  - `source`, `document`, `chunk`, Voyage, GitHub and `tree-sitter`: `admin can connect a GitHub repository to the knowledge base` owns them.
  - `pg_trgm` and the search indexes: the search task owns them.
  - Moving local data off the Postgres 17 volume: `.doc/architecture.md` decided on a new volume.
  - Demoting an admin: the user declined a backlog line for it on 2026-10-30.

## Assumptions

- `pgvector/pgvector:0.8.7-pg18` at the digest below is Postgres 18.6 with `PGDATA=/var/lib/postgresql/18/docker` and `VOLUME /var/lib/postgresql`, read from its image config on 2026-10-30: the confirmation `.doc/architecture.md` asks of this task.
- A new volume starts empty: `db/init.sql` creates `app_test` on first start, `e2eDb` creates `app_e2e`, and only `docker-compose.yml` names the volume.
- `create extension if not exists vector`: the bundled `app` role is a superuser, and `if not exists` lets a managed database's privileged role create it first.
- `grant_admin` proves ownership through auth's `verify_credentials`, which reads the hash itself and returns the public shape: `register` takes any address, and a verified email proves the mailbox, not the password.
- `refresh` re-reads the role, so `grant_admin` revokes the account's sessions before promoting it, and the promoted account signs in again.
- Both images report the collation `en_US.utf8`, but musl compares bytes where glibc applies the locale. No query orders by text except the `id` tie-break, which compares with the collation it sorts by, so paging holds.

## Open Questions

None.

## Steps

### Backend

1. `backend/tests/db/test_postgres.py` — `TestTheEngine`, red on the running Postgres 17: `server_version_num` at least 180000, `vector` in `pg_extension`, and in a temporary table a `halfvec(1024)` value that round trips as text cast in the statement and takes an HNSW index with `halfvec_cosine_ops`.
2. `docker-compose.yml` — `database` on `pgvector/pgvector:0.8.7-pg18@sha256:2358fcba361ed2233a5ed81b5fe4ca779ccb304120ce531a3bf51c0ed7e2bc11` with the version in a comment; a new named volume `database-pg18` mounted at `/var/lib/postgresql` replaces `database-data`; the `db/init.sql` mount, the credentials and the healthcheck stay.
3. `backend/src/app/infra/migrations/0004-vector-extension.sql` — `create extension if not exists vector`, after `0003-drop-module.sql`.
4. `backend/src/app/api/auth/controller.py`, `backend/tests/db/test_grant_admin.py`, `backend/src/app/infra/scripts/grant_admin.py` — red first: `main(argv)` on the selector loop, shaped like `migrate.py`; one email argument, the password from a prompt or one line of stdin and never argv; `_verify_credentials` becomes the exported `verify_credentials`, then `revoke_all_sessions` and `set_user_role`; exit 1 for a wrong argument, an unknown email, a wrong password or a blocked account; logs the user id only.
5. `backend/AGENTS.md` — the layer map's `scripts/` line, `Where does X go`, and `Authentication`'s admin bootstrap and `Renaming the roles` name `grant_admin`, register-yourself-first, its local and Compose commands, its stdin form and the fresh sign-in; `Local service` says Postgres 18 with `pgvector` and how the old volume is left.

### Driver

1. `.doc/architecture.md` — the engine line says what now runs (Postgres 18 with `pgvector`, the digest-pinned tag, the volume path, the old volume a human's to remove) and no longer assigns the move to the task that connects the first source; a change-log line for the engine, `vector` and `grant_admin`.
2. `.gitignore` — `*.stackdump`: a crashed Git Bash tool left one at the root twice, and `verify` hashes untracked files.

## Validation

- V01 — `database` is Postgres 18, the shipped migrations enable `vector` and record `0004-vector-extension.sql`, and a `halfvec(1024)` value round trips and takes an HNSW index (AC01) — proof: `backend/tests/db/test_postgres.py::TestTheEngine`, red on Postgres 17 in the report's `Tests first:`
- V02 — The image is pinned by digest and the data sits in the named volume, with `data_directory` at `/var/lib/postgresql/18/docker` under the mount at `/var/lib/postgresql` (AC01) — proof: `docker compose config --images`, `docker compose exec database psql -U app -d app -Atc "show data_directory"`, `docker inspect` of the service's container for its one mount there
- V03 — `grant_admin` promotes an account by its email and password, ends its earlier sessions, and its next sign-in reaches `GET /api/user`; a second run changes nothing; an account pre-registered with another password stays unpromoted even once its email is verified; an unknown email, a wrong password, a blocked account or a wrong argument, including a password on argv, exits 1 and writes nothing; neither the password, the hash nor the email reaches the log (AC01) — proof: `backend/tests/db/test_grant_admin.py`
- V04 — Every gate and the e2e suite pass from an empty volume on the new engine, the contract is unchanged, and the docs no longer name the old engine as current (AC01) — proof: `node scripts/verify.mjs --plan <plan> --reuse`, `git diff --exit-code <Base> -- backend/openapi.json`, `git grep -n "Postgres 17" -- backend/AGENTS.md` finding nothing

## Risks

- Local conversations stay behind in the old volume at the next `docker compose up`, which the first `verify` runs — that volume is untouched, so reverting brings them back, and removing it is a human's job.
- `verify` never starts the production image — CI's `image` job proves `backend-migrate` applies `0004-vector-extension.sql`, so read it on the pushed branch before merge.
- `create extension` needs a privileged role — the bundled `app` role is one; a managed database is checked when `.doc/architecture.md` names the production target.
- A digest pin takes no upstream fix until a task bumps it — accepted: `.doc/conventions.md` asks for the pin.
- `grant_admin` proves the password, not the address: a login code needs only the mailbox and signs in with the account's role, so once a mail provider ships, whoever reads an admin's address is an admin — production delivers no code today, and the task that adds a provider re-checks admin addresses and decides whether to refuse an unverified email; no code branch is added for a provider that does not exist.
- The proof holds only while `create_user` is the sole writer of `password_hash` — `user can reset their password` must keep ownership safe when it ships.

## Rollback

Revert the branch: Compose returns to Postgres 17 on its old volume, which never saw `0004-vector-extension.sql`. What was written on the Postgres 18 volume does not move back to 17, and removing that volume is a human's job. No production database exists yet.

## Changes during the task

- Backend: `grant_admin.main` takes an optional keyword `logger`, like `migrate()`, so its tests can record log lines; there is no poe task for it, because the plan asked for none.
- Backend: a second run on an existing admin exits 0 without calling `set_user_role`, so `updated_at` does not change. The unverified refusal comes before that check, so an unverified admin without the flag still exits 1.
- Driver: `.plan/000-backlog.md` gained `starting a conversation is rate limited`, and `.gitignore` gained `*.stackdump`, on the user's yes.
- Plan amended on the user's decision (2026-10-30, "Prove the password"), after both reviews raised a P1: refusing an unverified email could not pass on a stack with no working mail, so `--allow-unverified` would have been routine, and a verified email keeps a pre-registered password. Step 4, Step 5, V03 and two Assumptions changed; the flag is gone.
- Driver: `.plan/000-backlog.md` gained `user can reset their password`, the remedy `.doc/architecture.md` names, on the user's yes.
- Backend, fix round 1: `grant_admin.main` takes keyword-only `logger` and `read_password` so its tests can inject them, and imports `revoke_all_sessions` from `services/session.py`, which the import contracts allow.
- Backend, fix round 1: the documented Compose command was run against the local stack: a wrong password exits 1, the right one promotes, a second run is a no-op, and the account then reaches `GET /api/user`. The TTY prompt has only a unit test. The trial account `grant-trial@example.com` stays in the development database as an admin.
- Backend, fix round 2, docs and docstrings only: `backend/AGENTS.md` says the address must be one only you control, how to supply the password safely, and that the task adding a mail provider re-checks admin addresses; `Credentials` and `verify_credentials` no longer imply HTTP-only callers. The driver read this diff; no reviewer re-read it, because it closes no P0 or P1.
- QA: V03 re-judged after the amendment, PASS, adding `test_leaves_another_accounts_sessions_alone`.
