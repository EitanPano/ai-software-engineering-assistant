# Contributing to the harness

For changes to the harness itself. To build a product with it, start from the
[README](README.md). Setup removes this file from every project.

## Tests

Run both suites before a change merges. The harness has no build, type-check or lint step.

```
node --test ".claude/hooks/test/*.test.mjs"
node --test "scripts/**/*.test.mjs"
```

## Adding a file

Every tracked file belongs to one group in `.claude/harness.json`: `harness` files ship and update
with the harness, `project` files belong to the product after setup, and `dev` files are removed at
setup. A `harness` file may name a `dev` file only through the manifest's `references` list.

## Changing the instruction files

`AGENTS.md`, `.claude/agents/`, `.claude/skills/` and `.claude/rules/` are prompts: an agent
re-reads them on every turn, and loop runs have proved most of their sentences. Change one only
for a defect, a duplicate or a measured cost.

- One home per fact. A fact a script computes lives in the script; a doc says where to read the
  result. An agent's preloaded skill is not repeated in the agent's body.
- A skill's description says when to use it and the topics it covers, never its steps. An agent
  follows a narrated workflow instead of the body; a session with no topic words greps instead of
  invoking.
- Measure a description change in real sessions: run each prompt through `claude -p` on both trees
  and count `Skill` calls. Asking a model to pick from the list scores far higher than a session
  deciding for itself, so it cannot show a loss.
- A procedure one task in a project needs goes in a supporting file beside the `SKILL.md`, named
  from it with the condition that sends a reader there.
- Name a current fact, not its history. Text for older catalogs goes when `minCatalog` passes them.
- `dev-loop` stays under 5,000 tokens: its sessions are long, and after a compaction a re-attached
  skill keeps only its first 5,000 tokens. Its commit gate is at the end.
- The skill listing shares a budget with every plugin the user has, about 8,000 characters by
  default; past it, descriptions drop from the least-invoked skills first.

`scripts/docs.test.mjs` holds the budgets and checks the pointers. A budget moves only with a
reason in the plan that moves it.

## Changing the hooks

Any change to `.claude/hooks/` must pass the hooks suite before it merges. A broken hook blocks
every tool call, so make the change in a worktree, not in the live checkout.

## Bumping the catalog

`catalog.lock` pins the template catalog. After bumping it, before merging:

1. Grep the harness text (`AGENTS.md`, `README.md`, `.claude/`, `.doc/`, `scripts/`) for the
   old version's paths, rule names and command names.
2. Update every hit to the new template's `AGENTS.md`, or record why it stays.
3. Run the hooks suite and `node scripts/verify.mjs` on a project generated from the new lock.

To try an unreleased catalog, use `--templates <path>` or `FULLSTACK_TEMPLATES_DIR`. Otherwise the
bootstrap clones the pinned catalog into `~/.cache/fullstack-templates/<version>/`;
`FULLSTACK_TEMPLATES_CACHE` overrides that directory.

## What setup leaves in a project

The bootstrap's finish step (`node scripts/bootstrap.mjs --finish`) turns the clone into a product
repository. It leaves a generated product `README.md`, no harness tests or setup scripts, and the
harness version in `.fullstack/harness.json`. `.claude/README.md`, the harness manual, ships to
every project.

## Releasing the harness

1. Run both test suites.
2. Set `version` in `.claude/harness.json` in the release commit; between releases it reads
   `unreleased`.
3. Tag `vMAJOR.MINOR.PATCH` on `main` through the `cutting-a-release` skill.
