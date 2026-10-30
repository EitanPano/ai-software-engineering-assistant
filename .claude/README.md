# Harness manual

How the dev harness works in this project: the loop, the guardrails and how to recover from them,
the running environment, the optional integrations, and how to update the harness. The rules every
agent follows are in `AGENTS.md` and `.claude/rules/`. This file ships with the harness and is
replaced on an update.

## How work moves

1. A task is one line in `.plan/000-backlog.md`.
2. The orchestrator drafts the plan into `.orchestrate/<slug>/plan.md`, with a `UX` line per
   route (pattern, primary action, states, tone). You approve the draft; the driver then cuts the
   task's branch and promotes it to `.plan/NNN-YYYY-MM-DD-<slug>.md`. Once a task's implementers
   are running, the orchestrator plans the next backlog line in the background.
3. The backend agent implements the plan's Contract and regenerates the server's contract (the
   contract stage); then the backend and frontend agents work in parallel, the frontend
   regenerating its types and implementing the feature. Both test first. After e2e has captured
   the screens, the frontend agent runs a UI pass: it reads three screenshots per route (phone
   light, phone dark, desktop light) against the `ui-design` rubric and fixes what fails.
4. `node scripts/verify.mjs --plan <plan> --reuse` runs the gates and writes
   `.orchestrate/<slug>/verify.json` (run in the background; it can outlive a foreground
   timeout). When the data-layer task adds `testDb` and `migrate`, the driver records them in
   `.fullstack/catalog.yaml` from the backend's `Commands:` line first.
5. One reviewer (plus a security reviewer when `verify.json` says `security.triggered`) and QA
   run in parallel. P0 and P1 findings go back to the implementer, at most two fix rounds, each
   re-reviewed on its own diff. QA adds adversarial tests, runs a UX pass over the same
   screenshots (a rubric failure is a P2; a broken journey or a WCAG AA failure is a P1), and
   checks each acceptance criterion with evidence.
6. The driver writes the change log, updates the root `README.md` (Features, and the
   Configuration block with `node scripts/readme.mjs --configuration`), runs `verify` once more
   on the final tree, and checks that `git write-tree` equals the verified tree. Then you decide
   whether to commit. Role agents never commit, merge, push or rewrite history; the driver commits
   only on your yes.

The whole procedure is in `.claude/skills/dev-loop/SKILL.md`.

## Guardrails and recovery

The hooks in `.claude/hooks/` fail closed: a hook that crashes, times out or cannot start blocks
the tool call. If `node` is missing from Claude Code's `PATH`, every tool call (Read and Edit
included) is blocked until that is fixed. To recover, put `{ "disableAllHooks": true }` in
`.claude/settings.local.json` (git-ignored) or edit `.claude/settings.json` by hand, then restore
the hooks once `node` resolves. On a Claude Code older than 2.1.295 the hooks run but fail open,
so upgrade before relying on them.

Check that the hooks run: ask Claude to run `cat ./no-such-dir/.netrc` and expect a refusal that
names the guardrail. The path does not exist, so the check exposes nothing if the hooks are dead. A
refusal of `.env` alone proves nothing: the permission rules can refuse it with dead hooks.

Lanes stop accidents; they are not a sandbox. Use Claude Code's sandbox or a container.

## Rules and permissions

- Do not edit harness files: put project rules in `.doc/conventions.md` (every session loads it
  and harness updates never change it), and project-wide permissions in the `permissions.allow`
  and `permissions.deny` lists of `.claude/settings.json`, where they survive updates.
- Any other `settings.json` key (project hooks, `env`, MCP enablement, `permissions.ask`) counts
  as a local edit and is lost under `--overwrite`. Keep those, and personal permissions, in
  `.claude/settings.local.json`.
- `/code-review` runs this project's `code-review` skill, which replaces Claude Code's built-in
  command of that name. The built-in cloud review stays reachable as `/ultrareview`.

## Running environment

- Bun, Node and git must be on the `PATH` that Claude Code sees. On Windows, Git Bash backs the Bash
  tool.
- On Linux, the frontend package's `AGENTS.md › Tests` names the browser install.
- Until you accept the workspace trust dialog, Claude Code ignores the `permissions.allow` list in
  `.claude/settings.json` (the hooks still run), so a headless `claude -p` run in a fresh clone
  falls back to its permission mode for every command.
- A headless `claude -p` run stops background agents after ten minutes unless
  `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` is set in its environment.

## Optional integrations

- **Linear**: set `tracker: linear` in the backlog header and add the Linear MCP server to a
  `.mcp.json`; the loop falls back to local ticket files when the tool is absent.
- **Figma**: add a `figma:<url>` marker to a backlog line and the Figma MCP server; the frontend
  agent reads the frame when the tool is present.

## Frontend choice

React (the single-page app) is the default frontend. The dev loop has exercised it less than the
Next.js frontend, so report any gap you meet. Next is for products whose public pages must be
found by search engines or show a rich preview when shared.

## Updating the harness

```
node scripts/harness-update.mjs --version <tag|commit>
node scripts/harness-update.mjs --from <path>
```

`--from` takes a local checkout of the harness. `--overwrite` proceeds past local edits. The
release is cached in `~/.cache/fullstack-dev-harness/<version>/`; `FULLSTACK_HARNESS_CACHE`
overrides that directory. The command rewrites the guardrails, so Claude Code asks for your
permission before it runs (`permissions.ask`).

- **What it replaces:** only the files `.claude/harness.json` lists as `harness`, plus the
  `.gitignore` harness block. It deletes harness files a release dropped, and never touches
  project files.
- **It refuses** when:
  - the working tree is dirty;
  - the release's `minCatalog` is newer than the project's `catalog.lock`; it names the newest
    release the project can take;
  - a harness file has local edits, unless `--overwrite` is given.
- **Safety:** it sends each hook three benign calls (a Read, a `git status`, an Edit) after
  writing, and restores the previous files if one fails. It also refuses a release or a record
  whose `format` it does not know.
- **Leftovers:** the backup goes to the OS temp directory and release clones to the cache path
  above. Neither is cleaned automatically; the backup path is printed on every run.
- **Merges:** in `.claude/settings.json` it keeps the project's own `permissions.allow` and
  `permissions.deny` entries.
- **Advice:** it prints the upstream diff of seeded project files (such as the product-definition
  form) as advice, and never applies it.
- **Version record:** `.fullstack/harness.json` records the installed harness version.

A lock bump changes only what the next bootstrap generates. A generated project keeps its packages
and their `AGENTS.md`, so an older frontend cannot be upgraded in place.

### Manual update

A project with no `.fullstack/harness.json` predates the version record, and the command refuses
it. Copy the files the release's `.claude/harness.json` lists under `harness` over your own, add
your entries back to the `permissions` lists of `.claude/settings.json`, and review the diff. That
path leaves no record, and the full `verify` fails until the project's `README.md` has the two
Configuration markers. Add them around a Configuration section:

```
<!-- configuration:start -->
<!-- configuration:end -->
```

then run `node scripts/readme.mjs --configuration` to fill it.

### Older projects

The harness points at sections of the catalog version the lock pinned when the project was
generated, so some projects stay on an older harness:

- No `.fullstack/catalog.yaml`: the project predates the catalog and its `backend/AGENTS.md` lacks
  the sections the agents point at. It stays on harness commit `7ca23af`.
- A 1.x frontend recorded in `.fullstack/catalog.yaml`: the harness names the frontend foundation
  of catalog v1.4.0. The project stays on harness commit `b8019b8`.

A project updated past either commit ticks the boxes of `## Ready to plan` in
`.doc/product-definition.md` that hold and fills its `Design` section before the next loop; the
dev loop refuses to start otherwise.
