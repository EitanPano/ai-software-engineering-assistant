---
name: bootstrap-project
description: Turn a fresh clone of this harness into a running project. Use when .fullstack/catalog.yaml does not exist yet, when .doc/ still holds FILL markers, when the user pastes a product brief, or when the user asks to start, set up, create or bootstrap the project. Covers the product forms, the stack choice, the scaffold and the first backlog lines.
---

# Bootstrap a project

Runs once per project, in the interactive session (no role agent). The harness owns no
templates: `catalog.lock` pins a release of the template catalog, and the bootstrap runs
that catalog's generator. This skill supplies the product, the stack choice and the
database decision, and proves the result works. Prerequisites: Bun 1.4+, Node 24+, git, and
each chosen template's own tools.

After a context compaction, Read this file again: a re-attached skill keeps only its first 5,000
tokens, and this one is longer. Its last sections are the commit gate.

## 0. Preflight

- A git repository: run `git rev-parse --show-toplevel`. When it fails, offer `git init` and
  say that the harness becomes the root commit (next item). `scripts/bootstrap.mjs` refuses to
  run outside a git work tree (`--fetch` writes no project and skips the check).
- A repository with no commit: run `git rev-parse --verify HEAD`, also in a repository that
  already existed. When it fails, ask the user to approve committing the
  untouched harness as the root commit before the scaffold (`chore: import the harness`).
  Say why: `--finish` needs a HEAD to tell the harness's files from the project's changes, and
  refuses without one. Commit only on their yes.
- The tools: Bun 1.4+, Node 24+, git, and each chosen template's `tools` (section 2 checks
  those once the stack is chosen).

## 1. Decide the product with the user

### With a pasted brief (one-shot intake)

A user may paste a brief that answers the forms (purpose, scope, authentication and roles,
design, data store, data model, glossary, stack, flags, deploy mode, tracker, backlog lines).
Then:

1. Fill every form from it, in the user's words: `.doc/product-definition.md` (Design
   included), `.doc/architecture.md` and `.doc/glossary.md`, the same markers the walk below
   asks about, and leave the ones section 5 writes. Map each stack, flag, capability,
   deploy-mode and brand answer to its scaffold flag (sections 2 and 3), with the mappings that
   section 3 states.
2. Collect every gap: a marker from step 1 the brief does not answer, a value the catalog cannot
   take, a clash with the glossary. Ask about all of them in one message, each with the skill's
   default or recommendation. Do not walk the sections.
   Infer the Search and sharing answer (do public pages need to be found by search engines or
   show a rich preview when shared?) from the brief; ask it in the gap message only when the
   brief is silent. It is written into the product definition and decides the frontend
   (section 2).
3. Compare the brief with the template gaps below.
4. Show one summary to confirm: the forms, the stack and its flags, the database capability,
   the deploy mode, the brand (every flag with its value, the display name included), the
   template gaps and the first backlog lines. Scaffold only after a yes.

Template gaps. Every server template ships the same auth defaults: the entity `user`, the roles
`user` and `admin`, and a password of 8 to 128 characters. Compare the brief's entity names,
roles and password rule with those. Each difference is a gap:

- Record it in the summary and in `.doc/architecture.md › Auth` as a decision for the first
  task that needs it (for example "roles `member` and `staff` replace `user` and `admin`;
  decided in the task that adds the first gate"). The skill changes no template code.
- That task's plan carries `Retired:` with the template's old terms (`writing-plans`), role
  values in literal form (`'admin'`, `UserRole.admin`), never a bare word the entity or a path
  shares (`user`). Without it the rename arrives unannounced, inside a later task's plan.
- After section 3, confirm those defaults in the generated package: the entity and gates in its
  `AGENTS.md › Authentication`, the password bounds in `models/user/constants`
  (`USER_LIMITS.password`). Add any gap they show.

### With no brief (section by section)

Open `.doc/product-definition.md`. For each `<!-- FILL: … -->` marker, in order, ask the
user one question at a time and replace the marker with their answer. Keep answers in
their words; suggest a default only when they ask. Ask the Search and sharing line (Non-functional
Requirements) with the form; the answer decides the frontend in section 2. The `Design` section is part of this walk;
a product with no frontend answers it "n/a", and answers Search and sharing "n/a" too (which resolves that FILL marker). Its brand fields become scaffold flags in
section 3. Do the same for `.doc/architecture.md`
(other components, other data flows, Data store, Data Model, Data migrations, API versioning,
Auth, External Dependencies, Deployment, except the Data store's `Local service` and the
`Deploy mode` and `TRUST_PROXY` lines, which section 5 fills once the stack is chosen) and
`.doc/glossary.md` (one row per entity named in the scope).

The Data store question is the `database` skill's: engine, client library, or decide
later. Record the answer as given (the engine the user names, or "decide later", plus the
client library); whether the server template lists a provider is a separate fact, settled
in section 2. When the engine the user names is one the template lists, section 2 passes it
and the generator wires it; the Data store section is then filled from what was generated
(see section 5).

The Auth question decides a flag: a product with no accounts (Auth: none) is scaffolded
with `--flag auth=false`; any other answer keeps the server template's authentication (its
`auth` flag on, the default). The Auth section of `.doc/architecture.md` carries `auth`
markers that the scaffold resolves (section 3): under `none` it keeps the "Auth: none" text
and drops the shipped default and the roles marker, which describe code that will not
exist. For `none`, leave the marked text alone and do not answer the FILL markers inside an
`<!-- auth-start -->` block. The glossary's marked auth rows (`session`, `caller`, `OTP`,
`target`) are removed by the scaffold under `none` and kept otherwise, so do not edit them.

The frontend kind is known only after section 2, so section 5 replaces the Client model
marker in the Auth section with the line for the chosen frontend:

- Server-rendered (Next): the frontend's server is the backend's client (no browser
  fetch). CORS is off unless `CORS_ORIGINS` is set. Rate limits key on the client
  address. The opt-in `CLIENT_IP_HEADER` makes the frontend forward the visitor's address
  (the `deployment` skill, section 6); without it all visitors share one rate-limit bucket,
  about 30 active signed-in visitors per 15 minutes.
- Single-page app (React): the browser calls `/api` on the page's own origin (the
  server in `single`, the frontend image's proxy in `split`), so there is no CORS and no
  API URL in the bundle. Rate limits key on the client address, so `TRUST_PROXY` is the
  hop count in front of the server (`false` in `single` locally, `1` in `split`).

Stop when the "Ready to plan" checklist in the product definition is satisfied. Do not
start the scaffold while a marker remains in a section the checklist names.

## 2. Choose the stack

```bash
node scripts/bootstrap.mjs --fetch
```

It prints `catalog: <path>` and then `index.yaml`. Do not present the whole `stacks:` list.
Read each stack's `<catalog>/stacks/<id>/stack.yaml` (its `packages:` list: a `template` path
and a `dir` each) and each package's `<catalog>/<template path>/template.yaml`. Narrow by the
Search and sharing answer, deciding by the `static` declaration and never by a stack id:

- "yes": keep the stacks whose frontend does not declare `static` (server-rendered, Next today).
- "no": keep the stacks whose frontend declares `static` (a single-page app, React today).
- A stack with no frontend skips this question.

Ask only the remaining choice (the server today). Show the chosen stack with its reason (for
example "single-page app: no public page needs search or sharing") and accept an override. Ask
every flag the templates declare (show its
`summary` and `default`) and every capability that lists providers. Map the answers to
`--flag <name>=<true|false>` and `--capability <kind>=<provider>`.

Ask the deploy mode only when the chosen stack has a server and its frontend's
`template.yaml` declares `static` (a single-page app such as React). Put the tradeoff in
two lines and map the answer to `--deploy <single|split>`:

- `single` (the default): one container and one port; the server serves the built
  frontend and the API, so there is no CORS and no frontend container. Needs the Docker
  Compose floor the `deployment` skill states (section 1); name it to the user.
- `split`: a static-server image per frontend that proxies `/api` to the server, for
  separate scaling or hosting of the frontend.

A frontend without `static` (Next) is always `split`: do not ask and pass no `--deploy`.
The `deployment` skill moves the project between modes later. Ask the database
provider here when the template lists one (`capabilities.database.providers`). When the
user named an engine in section 1 that the template lists, the provider fixes the client
library (the package's `AGENTS.md › Adding the data layer` names it): tell the user and
confirm. On a yes, pass `--capability database=<id>`; the data-layer backlog line is then
NOT written, because the generator wired the engine. On a no, pass no capability and write
the data-layer backlog line.

Before accepting `single`, run `docker compose version` against that floor. When the
client is older, say so and offer `split` or an upgrade; do not scaffold `single`.

Before scaffolding, check each chosen template's `tools` (name and minimum version, from
its `template.yaml`) against the machine, for example `uv --version` for a Python backend.
Name any missing or old tool, the version found and the minimum, then stop; do not
scaffold. The generator runs the same check as its preflight, so this is the early, friendly
one.

These three files are the only things this skill reads under the catalog path. Never Glob,
Grep, list or explore the catalog cache and never dispatch an Explore agent into it; it is
outside the working tree on purpose.

## 3. Scaffold

```bash
node scripts/bootstrap.mjs --stack <id> --name <project-name> \
  [--flag k=v]… [--capability k=v]… [--deploy single|split] [brand flags]…
```

The brand flags come from the `Design` form; pass only the fields that hold a value:

| Design field | Flag |
| --- | --- |
| `Display name` | `--display-name` |
| `Primary colour` (hex) | `--brand-primary` |
| `Neutral colour` (hex) | `--brand-neutral` |
| `Radius` | `--radius sm\|md\|lg` |
| `Type` | `--font system\|inter` |
| `Default theme` | `--theme system\|light\|dark` |
| `Density` | `--density comfortable\|compact` |

- Quote every hex value on the command line (`--brand-primary '#2f6f4e'`): an unquoted `#`
  starts a shell comment.
- An empty `Display name` omits the flag; the generator title-cases the project name. A given
  name is 1 to 60 characters of letters, digits, spaces and `. , : ! ? _ -`, starting with a
  letter or digit, with no two underscores in a row.
- A named colour (for example "a cool neutral grey") is converted to a hex by this skill,
  which writes the hex into the Design form. A free-text answer to an enumerated field maps
  to the nearest allowed value (Type "Roboto" becomes `system` or `inter`); state the mapping
  to the user. Show every brand value to the user together with the stack and deploy mode
  (section 2) before scaffolding, so an unattended run does not stall.
- When the generator rejects a brand value (an invalid hex, enum or name, or a colour pair it
  cannot make pass contrast) it names the flag: report it, ask for another value, then
  re-run.
- `Tone`, `Reference apps` and `Primary viewport` stay in the form and have no flag.
- `node scripts/bootstrap.mjs --help` prints the usage and every flag.

Once the generator has run, `bootstrap.mjs` writes the root `README.md` from a template: the
mechanical sections are filled, and two placeholder lines remain (`<!-- readme:about -->`,
`<!-- readme:features -->`) for section 5.

It creates the packages the stack lists, under the directories the stack names; a merged
`docker-compose.yml` and `.gitignore`; `.editorconfig` when absent; and
`.fullstack/catalog.yaml`, the provenance file (per package: template, version, flags,
capabilities, commands and ports; and the top-level `providers` map, which is empty when
none was chosen). When a provider was chosen it also adds the provider's service to `docker-compose.yml`,
`db/` with the database init script, and the connection variable in the server's
`.env.example`. It installs each package and runs its `contract` and `format`
commands. It refuses to run twice. A failure before the move leaves nothing to clean: the
generator stages the output and moves it into place all or nothing (a failed move is rolled
back). The clearing step runs after the move, so a failure there leaves the scaffold in place
and the message names the recovery (`node scripts/history.mjs <root> [--auth=false]`).

## 4. Verify

Open `.fullstack/catalog.yaml`. With a provider (a non-empty `providers` map, e.g.
`providers: { database: <id> }`; `providers: {}` means none), first run
`docker compose up -d --wait <service>` (the provider's service, named in
`docker-compose.yml`). Then, once:

```bash
cd <frontend dir>
bun x playwright install chromium   # add --with-deps on Linux
cd ..
node scripts/verify.mjs --out .orchestrate/bootstrap
```

The browser install runs from the frontend package directory, so the package's pinned
Playwright installs its own browser revision (the catalog's `tools/lib/browsers.ts` does the
same). `verify` can outlive the Bash tool's timeout: run it with `run_in_background: true`
and wait for the completion notification.
While `verify` runs, nothing edits the working tree (no form edits, no file writes): `verify`
hashes the tree, and a concurrent edit fails or invalidates the run.

`verify` runs the gates of every package in `.fullstack/catalog.yaml` and replaces the
hand-run list. It is run without a base because the scaffold is not committed yet. It must
exit 0. If it fails, fix the cause (not the gate), re-run it, and tell the user what was wrong.
A failing gate on a fresh scaffold is a catalog bug: say so explicitly, name the template and
version from the provenance file, and record it in the final message.

Then start each package's `dev` command (an SPA's server first, as the frontend's
`AGENTS.md` says) and open the frontend's `http.health` path on its
`http.port` (a Next frontend on its port; an SPA's dev server on its `http.port`, which
proxies `/api` to the server): the page must reach the server (the `HealthBadge` in
`widget/system-status` proves the typed client reaches it).

Stop the dev servers by port. On Windows a `--reload` server leaves its child holding the port
after the parent is stopped, and the port's owner is then the dead reloader, so stop the owner
and its children (replace 8000 with the package's port):

```powershell
$o = (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess | Select-Object -Unique; Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in $o -or $_.ParentProcessId -in $o } | ForEach-Object { Stop-Process -Id $_.ProcessId }
```

On Linux and macOS: `lsof -ti :<port> | xargs -r kill`. Confirm the port is free before the app
check: `Get-NetTCPConnection -LocalPort <port> -State Listen -ErrorAction SilentlyContinue`
(Windows) or `lsof -i :<port> -sTCP:LISTEN` (Linux, macOS) prints nothing.

For the app check, first export in the shell a throwaway value for every secret the server's
`.env.example` lists, and with a provider its `DATABASE_URL` (never in a file): the server
refuses to start in production without them. Use a fresh `-p <name>`, because a reused
project name reuses its volumes. With a provider, run `docker compose stop database` first
(the dev project's service; the app project publishes the same loopback port). Run
`docker compose --profile app up --build --wait` at the root and stop it with
`docker compose --profile app down` (same `-p`). With a provider, the `<dir>-migrate` one-shot
service runs the migrations first. Run `docker compose start database` afterwards, even when
the app check failed. In `single` the check is one container
on the server's port (no frontend container in `docker compose ps -a`): `/` returns the
page and `/api/health` answers there. In `split` it is one container per package, reached
through the frontend's port.

A fresh server package has: health, the commented reference module, and authentication when
the `auth` flag is on. Its store is either the in-memory store (nothing survives a restart
until the data-layer task) or, when a provider was chosen, the wired engine with its
migrations and test database, described in the package's `AGENTS.md › Adding the data
layer`. Production secrets are listed in the package's `.env.example`; development runs
with defaults and warns.

## 5. Finish the forms

Do each item; the dev loop refuses to start until the last one holds.

1. **Backlog.** Follow the grammar at the top of `.plan/000-backlog.md`. When no database
   provider was passed at generation, the first line is `- [ ] add the <engine> data layer` for
   a named engine, or `- [ ] add the data layer` when the answer was "decide later", with
   ` | stack:backend` appended only when the stack has no frontend (the `database` skill says
   what that task delivers, and why the frontend takes part). With a provider, the first line
   is the first in-scope capability from the product definition; without one it is the next
   line. Set `tracker:` in the backlog header to `linear` or `none` as the user prefers.
2. **Stack.** Fill the `Stack` row of the components table in `.doc/architecture.md` from
   `.fullstack/catalog.yaml`: the stack id and, per package, its directory, template and
   version, plus the reason for the frontend choice (the Search and sharing answer).
3. **README.** In `README.md`, replace `<!-- readme:about -->` with About, written from Purpose
   and Problem Statement, and `<!-- readme:features -->` with Features: the in-scope capabilities
   from Product Scope, one line each, written `- <capability> (planned)` (nothing is built yet);
   the dev loop removes the ` (planned)` suffix when a task delivers the capability.
4. **Client model.** Fill the Auth Client model line for the frontend kind (section 1).
5. **Deployment.** Fill `.doc/architecture.md › Operational Concerns`, its Deployment list: the
   deploy mode (the top-level `deploy:` of `.fullstack/catalog.yaml`; "n/a" when the file has no
   `deploy:`, a stack with no frontend or no server) and the local `TRUST_PROXY` default
   (`false` in `single`, 1 in `split`).
6. **Data store.** When a provider was passed, fill the Data store section and the components
   table's `Data store` row from what was generated: engine and version from the provider
   service's image in `docker-compose.yml` (or the package's `AGENTS.md › Adding the data
   layer`), the client library and the local service (the provider's Compose service and its
   connection variable) from the package's `AGENTS.md › Adding the data layer` and
   `.fullstack/catalog.yaml`. With no provider, write `none yet: the data-layer task writes it`
   in the `Local service` line and that row, so the first task is not blocked by them.
7. **Change Log.** Replace its FILL line in `.doc/architecture.md` with
   `- <YYYY-MM-DD>: initial architecture accepted; <stack id>, deploy <mode>, <engine or in-memory store>.`
   Later entries go above it (newest first).
8. **Ready to plan.** Three markers may stay open, each until its own decision: the production
   `TRUST_PROXY` (the user's to decide, the `deployment` skill), the production target, and Data
   migrations when no provider was chosen. Every other marker holds an answer. "Decide later" is
   an answer for the Data store engine alone: a marker the user cannot answer stays, is named in
   the summary, and blocks the first plan that depends on it. Then tick the three boxes of
   `## Ready to plan` in `.doc/product-definition.md`, once each holds.

## 6. Branch, commit gate and hand over

Create `chore/bootstrap` (never commit on `main`) and summarise what exists, including what
the scaffold removed, as the bootstrap printed it: the harness's own plans (`.plan/001–…`;
a product's first plan is `001`) and the auth text (under Auth none). As the last step before
asking to commit, run `node scripts/bootstrap.mjs --finish`. It refuses while a
`<!-- readme:` placeholder remains (fill it and run again); writes `.fullstack/harness.json`,
the harness version record; removes the `.gitignore` dev block and the harness-development
files (tests, setup scripts, this skill); and warns when the git history still holds the
harness's commits. Afterwards this skill's own files are gone: that is expected, and the
commit includes the removals. Then ask the
user whether to commit the scaffold as `chore(bootstrap): scaffold <project-name>`,
including `.fullstack/catalog.yaml`; the dev loop starts only from a clean tree, so the
first task waits for this commit. Commit only on their yes, then point them to `/dev-loop`
for the first task.

## What this skill never does

- Run any scaffolder inside an existing package.
- Browse the catalog cache.
- Edit `scripts/`, `.claude/`, `catalog.lock` or other harness files by hand. The one change it
  makes there is `--finish`, which removes this skill's own files and the harness development
  files through the script, as designed.
- Create a real env file; secrets stay in the shell environment.
- Install a database client or start a database service. The exception: a provider chosen
  at generation was wired by the generator, and its Compose service is started with
  `docker compose up -d --wait <service>`.
