---
name: deployment
description: Choose or change how the project ships. Use when a plan or the user asks to move between the `single` and `split` deploy modes, to set or review `TRUST_PROXY` for a production host, to scale past one replica, to serve the frontend from a static host or CDN, or to put the app on a non-loopback host. Covers the app profile, the proxy hop count, the Compose 2.35.0 floor and what scaling needs.
---

# Deployment

A project with a server and a frontend ships in one of two modes. The mode is chosen at the
bootstrap (`--deploy`) and moved later only through this skill, as a planned change.

| | `single` | `split` |
| --- | --- | --- |
| Images | one: the server's, holding the API and the SPA's `dist/` | one per package |
| Public port | the server's | the frontend's (the server's is loopback only) |
| Browser reaches the API | same origin, same process | same origin, through the frontend image's `/api` proxy |
| `TRUST_PROXY` default | `false` (the server is the edge) | `1` (the frontend's proxy counts) |
| Frontend Compose service | build-only: `target: dist`, `scale: 0`, no ports, no profile | a container: the `serve` target, ports, the `app` profile |

The exact lines for each mode, comments included, are in each package's `AGENTS.md ›
Deployment`, under "The lines of each mode" (`frontend/AGENTS.md`, `backend/AGENTS.md`; the
directories are in `.fullstack/catalog.yaml`). They are fenced blocks, one per mode, copied from
the template's own `compose.yaml` and `Dockerfile`, with the project's directories and ports
filled in (the server's block spells the frontend's directory `<frontend dir>`). A generated
project holds only the lines of its current mode, so the other mode's lines come from those
blocks. This skill names the steps and does not repeat the lines. Read both sections before
editing.

Every `docker compose` command below that inspects or stops the stack (`config`, `ps`, `exec`,
`logs`, `down`) carries the same `-p <name> --profile app` as the `up` that started it. Without
`--profile app` the profiled services are invisible; with another `-p` it is a different stack.

## 1. Choose

- Current mode: `.doc/architecture.md › Operational Concerns › Deployment`. It wins over the
  `deploy:` line in `.fullstack/catalog.yaml`, which records only what was generated and is
  never edited. While the doc line still holds its FILL marker, use the provenance line (`deploy:` in
  `.fullstack/catalog.yaml`). A `.fullstack/catalog.yaml` with no `deploy:` line is a stack with no
  frontend or no server: neither mode applies.
- A server-rendered frontend (Next) is always `split`. Nothing below applies to switching it.
- A single-page app (a frontend whose `template.yaml` declares `static`) starts `single`: one
  container, one port, no CORS, no API URL in the bundle. Move to `split` when the frontend
  needs its own scaling or release cadence, or a second deployable is required. Moving back
  is the same work in reverse.
- The Compose floor, stated here once: `single` needs Docker Compose 2.35.0 or newer. Check
  `docker compose version`; an older client fails with an error that does not name the
  cause. `split` has no floor.

## 2. single to split

1. Plan it (`writing-plans`). A deploy-only plan has no `Contract` and no source change.
   `Stages: backend, qa`: the root `docker-compose.yml` (both services) and
   `backend/Dockerfile` are in the backend agent's lane, and no file under `frontend/`
   changes, so there is no frontend stage. `Validation` is steps 5 to 8 below; `Rollback` is
   reverting those two files. A driver session that makes the change itself still writes the
   plan and edits the same files. The backend stage runs steps 5 to 8 itself, including the
   fresh `-p <name>` stack, the smoke, `testE2e` and the stop at step 8; `qa` re-checks within
   its own rules, on the services the repository defines, and starts no separate Compose project.
2. Frontend service in the root `docker-compose.yml`: replace its `single` lines with the
   `split` block of `<frontend>/AGENTS.md › Deployment`, comments included. It supplies
   `target: serve`, the published port, `API_URL` (`http://<server service>:<server port>`),
   `depends_on` the server and the `app` profile.
3. Server service in the root `docker-compose.yml`: replace its three `single` pieces with the
   `split` ones of `<server>/AGENTS.md › Deployment`: the `build` (no `additional_contexts`),
   the `TRUST_PROXY` default `1` and the loopback port (`127.0.0.1:<port>:<port>`), each with
   its comment. Each comment goes directly above the key it describes, at the key's indent;
   the `# (the other ... stay)` lines in the blocks are annotations, never copied.
4. Server `Dockerfile`: delete the three `single` lines of `<server>/AGENTS.md › Deployment`:
   the comment, the `COPY --from=spa ...` line and the `ENV STATIC_DIR=...` line. The server's
   static code stays; it is inert without `STATIC_DIR`.
5. Check the files: `docker compose -p <name> --profile app config` exits 0 (warnings about
   unset secrets are harmless; export them first to silence them), the frontend service shows
   `profiles: [app]` and no `scale: 0`, and the server service shows no `spa` context, the
   `TRUST_PROXY` default `1` and the loopback port binding.
6. Run the gates: the `check` command of both packages (resolved from
   `.fullstack/catalog.yaml`). No source changed, so this proves nothing regressed, not that
   the switch works. Then run the app profile (Running the app profile) and smoke:
   - through the frontend's port: `/` and a deep link return the page, and `/api/health`
     answers JSON through the proxy;
   - on the server's loopback port: `/api/health` answers and `/` is the JSON 404 (the server
     image holds no SPA);
   - `docker compose -p <name> --profile app exec <frontend service> id -u` prints a
     non-zero uid (101 in the catalog's image).

   `--wait` only proves the containers run (the server image defines no healthcheck, so a
   running server counts as healthy, and a server that crashes seconds later still passes it).
   Wait a few seconds, then confirm the server is still `Up` in `docker compose -p <name>
   --profile app ps -a`; on any failure read `docker compose -p <name> --profile app logs
   <service>`. The `/api/health` request is the proof.
7. With the stack still up, run the frontend's `testE2e` with `E2E_BASE_URL` set to
   `http://localhost:<frontend port>`. It needs the Playwright browser, installed once as
   `<frontend>/AGENTS.md › Tests` says (`bun x playwright install chromium`; `--with-deps`
   on Linux).
8. Stop the stack (Running the app profile says how).
9. Ask the user for the production `TRUST_PROXY` (section 6) and record the change (section 5).

## 3. split to single

1. Plan it as in section 2 step 1 (same stages, validation and rollback). Confirm the machine
   that builds and runs the images, CI included, meets the Compose floor (section 1).
2. Frontend service in the root `docker-compose.yml`: replace its `split` lines with the
   `single` block of `<frontend>/AGENTS.md › Deployment`: the build-only form (`target: dist`,
   `scale: 0`, no ports, no profile, no `depends_on`, no environment). The service must stay:
   the server's build reads it.
3. Server service in the root `docker-compose.yml`: replace its three `split` pieces with the
   `single` ones of `<server>/AGENTS.md › Deployment`: `build` in its long form with
   `additional_contexts: { spa: "service:<frontend dir>" }` (write the frontend's directory
   for `<frontend dir>`), the `TRUST_PROXY` default `false` and the port on every interface
   (`<port>:<port>`, the server is now the public edge), each with its comment above its key
   at the key's indent (the one-line `build: ./<dir>` is removed). The `# (the other ... stay)`
   lines in the blocks are annotations, never copied.
4. Server `Dockerfile`: add the three `single` lines (comment, `COPY --from=spa ...`,
   `ENV STATIC_DIR=...`) where `<server>/AGENTS.md › Deployment` places them.
5. Check the files: `docker compose -p <name> --profile app config` exits 0 (warnings about
   unset secrets are harmless), the frontend service shows `scale: 0` and the build target
   `dist`, and the server service shows the `spa` context, the `TRUST_PROXY` default `false`
   and the port on every interface.
6. Run the gates: the `check` command of both packages. Then run the app profile and smoke on
   the server's port: `/` and a deep link return `index.html`, `/api/health` answers (a
   request, not just `--wait`), `/api/nope` returns the JSON 404 envelope, and
   `docker compose -p <name> --profile app ps -a`, a few seconds after `up`, shows the server
   `Up` and lists no frontend container. If a request is refused, read the server's `logs`.
7. With the stack still up, run the frontend's `testE2e` with `E2E_BASE_URL` set to
   `http://localhost:<server port>`, after the Playwright browser is installed (section 2
   step 7).
8. Stop the stack (Running the app profile says how).
9. Ask the user for the production `TRUST_PROXY` (section 6) and record the change (section 5).

## 4. Running the app profile

- The server runs with `NODE_ENV`/`APP_ENV` production inside the stack and refuses to start
  without its production secrets. Before `docker compose -p <name> --profile app up --build
  --wait`, export in the shell a value for every secret the server's `.env.example` lists and,
  with a database, its `DATABASE_URL`. Never write them to a file. The server refuses the
  `.env.example` placeholders in production (`change-me*`), so generate throwaway random
  values, for example `export JWT_ACCESS_SECRET=$(openssl rand -base64 32)`, or without
  openssl `node -p "require('crypto').randomBytes(32).toString('base64')"`. Read the
  comments in `.env.example` for format rules: `ENCRYPTION_KEY` must be base64 that decodes to
  32 bytes.
- Windows, Git Bash: a value that starts with `/` (base64 can) is rewritten as a path when
  passed to `docker.exe`, and the server then rejects it. Run the Compose commands with
  `MSYS_NO_PATHCONV=1` set, or generate keys that do not start with `/`.
- `docker compose --profile app up --build` at the repository root runs the whole stack from
  each package's Dockerfile: one image in `single`, one per package in `split`.
- With a database, the `<dir>-migrate` one-shot service runs the migrations before the server.
  The `migrate` command stays for local development.
- Reusing a Compose project name reuses its volumes (a database from an earlier run keeps its
  data). Pass a fresh `-p <name>` for a clean proof, and the same one to every later command.
- Stop with `docker compose -p <name> --profile app down`. Without `--profile app` the
  profiled services are invisible to `down` and keep running (`COMPOSE_PROFILES=app` works
  too).

## 5. Recording the change

Three edits in `.doc/architecture.md`, none to `.fullstack/catalog.yaml`:

1. Operational Concerns › Deployment › `Deploy mode`: the new mode.
2. The same list's `TRUST_PROXY hop count` line: the local default becomes `false` in `single`
   and `1` in `split`. The production half is the user's answer (section 6).
3. Change Log (newest first, so the new line goes at the top of the dated list): one line,
   `- YYYY-MM-DD: deploy mode <old> to <new>; local TRUST_PROXY <old> to <new>; plan <NNN>.`
   Write `plan <NNN>` only when a plan exists; with none, write `no plan` (or the user's
   request in a few words).

Who writes them: a driver session applies them itself, in the same change. A role agent
cannot write `.doc/`: it lists the three lines in its report's `Docs:`, and the driver applies
them when the dev loop finishes the task (`dev-loop` section 6).

## 6. TRUST_PROXY

The server keys rate limits on the client address it derives from `X-Forwarded-For`. The
value is the number of proxy hops in front of the server.

- Locally: `false` in `single` (the server is the edge), `1` in `split` (the frontend's
  proxy is the one hop).
- Production: count what sits in front. 1 behind a PaaS edge; 2 behind a CDN and a load
  balancer; in `split`, add the hops in front of the frontend image to the 1.
- The production value is the user's decision, never the agent's. After a mode switch the
  recorded value was counted for the old mode and is wrong for the new one (a PaaS edge in
  front of `split` is 2: the edge and the frontend's nginx). Ask the user for the new count;
  if there is no answer yet, restore the FILL marker in the production half of the doc line
  and list it as open in the report. Do not carry the old number over or pick one.
- A Next frontend is itself the hop in front of the API (its server calls it), so it is not an extra one on top of `split`'s count. Set the opt-in `CLIENT_IP_HEADER` (in
  the shell environment Compose reads) to the header your proxy overwrites with the visitor's
  address (`x-forwarded-for` or `x-real-ip`); the frontend then forwards it and `TRUST_PROXY`
  must count the frontend as a hop. Without it all visitors share one bucket: about 30 active
  signed-in visitors per 15 minutes before refresh and sign-in answer 429. Safe only when
  visitors cannot reach the frontend directly and the proxy overwrites the header; the recipe
  is in the frontend package's `AGENTS.md › Deployment`.
- Too high: a caller chooses its own rate-limit key through `X-Forwarded-For`. Too low: every
  caller is keyed to the nearest proxy, so one caller exhausts the limit for everyone.
- Record the production value in `.doc/architecture.md › Operational Concerns › Deployment` (it
  stays a FILL until decided). The shell environment or the secret manager supplies it; no file in the tree does.

## 7. Production hosts

- TLS. The containers speak HTTP and `Secure` cookies assume HTTPS, so an edge terminates TLS.
  The servers and the split image send helmet's default CSP with `upgrade-insecure-requests`:
  over plain HTTP at any host other than loopback the browser upgrades the script, style and
  `/api` requests to HTTPS and the page is blank. Local checks on `localhost` hide this.
  Put TLS in front, or change the CSP by plan.
- Compression and caching belong to the edge. Hashed `assets/*` are immutable (a CDN may
  cache them for a year); `index.html` is `no-cache`.
- Host-specific manifests (Fly, Render, Railway, Cloud Run, Kubernetes) are not generated;
  add them by plan.

## 8. Scaling

More than one replica of the server needs, first:

- State out of process: the database task (users, sessions, records) and the cache task
  (rate limits, sessions, the event bus). The template runs as one instance until both exist.
- Jobs on exactly one replica: `JOBS_ENABLED` true on one and false on the rest.

A Next frontend scales alone, and each replica has its own `'use cache'` store: `updateTag`
expires only the instance that ran the action. Past one replica, keep `cacheLife` short for data
that must change quickly, or configure a shared cache handler first
(the frontend package's `AGENTS.md › Deployment`).

In `single` the frontend scales with the server. `split` lets the static-server image scale
alone, which is its reason to exist.

## 9. A static host (CDN) for the frontend

Not generated and not a third mode (`deploy` stays `single | split`). It changes the security
model, so it is a planned change with a security review. A frontend served from another origin
than the API needs all of:

1. `CORS_ORIGINS` set to an explicit list of the frontend's origins (never a wildcard) so the
   server answers the preflights, with credentials allowed. Confirm the server's CORS options
   do so (`config/cors.ts` in bun-express, `config/cors.py` in python-fastapi; `AGENTS.md`
   names them) and change them if not.
2. Session cookies that reach the API from the frontend's origin. Keep them host-only: set
   no cookie `domain` (no `COOKIE_DOMAIN`), because a shared parent domain also sends the
   session cookies to every sibling subdomain, and the API's own cookie is already sent on a
   credentialed request to the API. Use `SameSite=None; Secure` only when the frontend's
   site differs from the API's; for a same-site split (`app.example.com` to
   `api.example.com`) `Lax` still sends the cookie and is safer.
3. A CSRF defence, in both cases (sibling subdomains are same-site): a synchroniser token, or
   a double-submit cookie with a custom header the server requires. Add a test that a
   mutation without it is refused.
4. An API base URL in the bundle, read only through `src/shared/config/env.ts`. This gives up
   the "relative `/api`" rule on purpose; the `baseUrl` in `shared/api/client.ts` changes with it, and the
   client sends `credentials: 'include'`, because fetch's same-origin default withholds
   cookies on a cross-origin request.

Why the default is safe without these: in `single` and `split` the browser and the API
share one origin, `SameSite=Lax` withholds the cookie from cross-site mutations, bodies are
JSON only and there is no CORS to answer a preflight. Losing any of the four breaks the
stance.

## Never

- Edit `deploy:` in `.fullstack/catalog.yaml`.
- Switch a server-rendered frontend to `single`.
- Leave the mode change without its `Deploy mode`, local `TRUST_PROXY` and change-log lines in
  `.doc/architecture.md` (section 5).
