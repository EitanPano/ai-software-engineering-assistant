# Adopt catalog v1.4.0: the harness speaks the frontend foundation

Status: done
Owner: Eitan
Last updated: 2026-10-28
Approval: delegated (2026-10-28, Eitan: "go"), confirming OQ1–OQ4 as recommended.
Decided (2026-10-28, Eitan: "yes catalog target, go with the 015/016 split"): Phase 3 splits into
this plan (adoption and the lock bump) and plan 016 (the visual loop and the speed levers). An
existing project's architecture refactor targets the catalog's architecture (Phase 5).
Input: `.superpowers/phase3/survey.md` (§2 items, §3 risks R1–R21), plan 013 (Out, Risks "Phase 3
drift"), the design spec's Phase 3.
Scope ruling (2026-10-26): only this repository and the catalog; the catalog is read only here.
Branch: harness `feat/frontend-foundation-adopt`, from `dev`.
Base: cc9fb1f
Stages: harness only. Sonnet implementers, a Sonnet review per task, and an Opus final review.
The plan ends in one PR into `dev`, then proof P3a.

## Goal

Catalog v1.4.0 (5b04a32) restructured both frontends:

- five layers;
- a shadcn design system;
- brand inputs to the generator;
- e2e on the production build;
- the `start` and `e2eDb` commands.

The harness still pins v1.3.0, and its text describes v1.3.0. A lock bump alone fails or
misleads (survey §3):

| Risk | What breaks |
| --- | --- |
| R1, R2 | `bootstrap.mjs` rejects every brand option, so the Design colour silently falls back to the generator default. This has been open since plan 012 (friction 3), and P1b's QA flagged it again. |
| R4, R5 | Plans and agents name `feature/<noun>/`, `lib/api/` and `src/env.ts`. The boundaries lint rejects files placed there. |
| R3, R6 | The rules forbid the one allowed scaffolder (`bunx shadcn@4.21.4 add`), demand 44 px on every pointer and ask for per-segment loading and error files. |
| R7, R8 | `writing-tests` and `error-handling` describe APIs v1.4.0 removed: actions passed as props, `{ reachable: false }` loaders, `ActionResult`. |
| R9, R10 | `deployment` omits `CLIENT_IP_HEADER` and Next's per-instance cache. |

After this plan:

- `catalog.lock` pins v1.4.0;
- every harness text names the v1.4.0 layout, or points at the package's `AGENTS.md`;
- a Design answer reaches the generator as brand inputs;
- a fresh bootstrap of each frontend passes `verify` with the brief's colour;
- one loop task lands its files in the right layers.

Where this sits:

| Plan | Phase | Content |
| --- | --- | --- |
| 015 (this one) | 3 | Adoption and the lock bump |
| 016 | 3 | The visual loop (B1–B4: `ui-design`, the frontend UI pass, the QA UX pass, the plan UX section, the one-shot intake) and the speed levers |
| P2 | 4 | The proof, at 60 min for three tasks |
| — | 5 | Existing projects, refactored to the catalog's architecture |

## Scope

**In** (this repository):

- `catalog.lock`: v1.4.0, `5b04a32da22951735780584cd4a2aa1f13a6ec5e`.
- `AGENTS.md`:
  - the frontend architecture bullets;
  - the typed client;
  - the shadcn exception;
  - the command table (`start`, `e2eDb`);
  - ending at 1,200 words or fewer (it is 1,211).
- `.claude/rules/naming.md`, `.claude/rules/ui-and-styling.md`.
- `.claude/agents/frontend.md`.
- These skills:
  - `writing-plans` (`SKILL.md` and `template.md`, the step paths only);
  - `bootstrap-project`, `writing-tests`, `api-design`, `error-handling`, `code-review`;
  - `deployment`, `database`, `dev-loop`.
- `.doc/product-definition.md` (the Design form), `.doc/glossary.md` (action terms).
- `scripts/bootstrap.mjs`, `scripts/verify/security.mjs`, `scripts/verify/review.mjs`, each with
  tests. A `provenance.test.mjs` fixture for `answers.brand` and `e2eDb`.
- `README.md`: the v1.4.0 frontend, the brand inputs, and no in-place upgrade for projects on
  1.x frontends.
- Proof P3a, in a disposable clone (Validation).

**Out:**

- Plan 016:
  - B1–B4 and C11's one-shot intake. With no `ui-design` skill yet, DoD item 6 and
    `code-review` keep citing the package's `AGENTS.md › Styling` (still present at v1.4.0) and
    the lint.
  - `qa.md`'s UX pass (R11, harmless until then).
  - `orchestrator.md`'s skill preload.
  - The speed levers: pipelined planning, review checks moved into `verify`, the per-task
    reviewer model.
  - The redundant dev `migrate` before e2e (R15).
  - Plan 014's follow-ups: `**/auth/ui/**` out of the security trigger, and the mechanized
    swallowed-`expect` check.
- Hook changes. No frontend path is hard-coded in a hook (survey item 40, R18).
- Upgrading an existing v1.3.0 project in place (R21): Phase 5.
- Proposed backlog lines, not queued:
  - `- [ ] server: a script that sets a user's role (first staff account)`
  - `- [ ] Servers key the refresh rate limit on the refresh token`

## Assumptions

- **The survey still holds.**
  - Catalog: its facts were read at v1.4.0.
  - Harness: `git diff --stat 668e9de cc9fb1f` touches only `scripts/verify*` and plan 014, none
    of the text files it surveyed.
  - Items marked "I" (inferred) get a test or a proof step, not trust.
- **The template decides, the harness points.** The package's `AGENTS.md` (from
  `frontend/<next|react>/base/AGENTS.md`) is the authority on the layout. Harness text repeats
  only what an agent needs before opening it, then points there (spec C9). Implementers read the
  catalog at the tag (`git -C ../fullstack-templates show v1.4.0:<path>`), not the survey.
- **The scaffolder is already allowed.** Hooks and `.claude/settings.json` allow
  `bunx shadcn@4.21.4 add` (item 40, verified for settings, inferred for behaviour; P3a checks
  it).
- **The schema check passes.** `schemaVersion` is still 1, so `bootstrap.mjs`'s check accepts
  v1.4.0 (inferred; P3a checks it).
- **Renaming `Features:` is safe.** Nothing parses the frontend report's `Features:` line: a grep
  of `.claude/` and `scripts/` finds only `frontend.md:56`.
- **Eitan's rules hold:**
  - Sonnet implementers and reviews, and an Opus final review;
  - no commit without his yes;
  - no hook edits;
  - only this repository and the catalog.

## Open Questions

1. **How do brand values reach the generator?** Recommended: pass-through. `bootstrap.mjs`
   forwards `--display-name`, `--brand-primary`, `--brand-neutral`, `--radius`, `--font`,
   `--theme` and `--density` unchanged; the generator validates them and checks contrast.
   Tradeoff: about 25 lines plus tests, against an answers file the skill would write into the
   working tree. Pass-through is explicit and leaves no stray file.
2. **Where does the brand come from?** Recommended: `.doc/product-definition.md › Design` stays
   the single source, with fields in the generator's vocabulary:
   - Display name;
   - Primary and Neutral as hex;
   - Radius `sm|md|lg`, Type `system|inter`, Density `comfortable|compact`;
   - Default theme `system|light|dark`.

   Tone, Reference apps and Primary viewport stay; plan 016's `ui-design` reads them.

   A named colour ("a cool neutral grey") is converted by the skill to a hex. The skill writes
   the hex into the form and shows it in the stack confirmation, so an unattended run does not
   stall. When the generator refuses a brand value (a malformed hex, a display-name character it
   does not allow), it names the flag, and the skill asks again. The generator itself adjusts
   lightness until every contrast pair passes.
3. **What happens to `e2eDb` on the "decide later" database path (R12)?** Recommended: keep the
   in-memory e2e as it is.
   - The data-layer task records `e2eDb` only when `server:database` was chosen at bootstrap.
   - The `database` skill says that adding a database later is a plan-level task, which wires
     the e2e database by hand. Otherwise e2e would write into the dev database.
4. **Does P3a run a loop task?** Recommended: yes, one task on `next-bun-express`. A bootstrap
   proves the generator and the brand; only an agent writing code proves the text (R4, R5). The
   run also gives plan 016 per-stage timings on v1.4.0 to aim the speed levers. Use brief line 2
   ("staff can publish a class and anyone can see the schedule"): the template already ships
   line 1's auth screens, and line 2 touches an entity, a feature, a widget and the contract.
   Cost: about 30–40 min and about 26M subagent tokens (P1b's per-task average; an estimate).

## Steps

### Decisions

- **D1, the lock ships with the text** (plan 013, Risks "Phase 3 drift"). `catalog.lock` changes
  in the branch's last commit, after H1–H4 are reviewed. Reverting the PR restores the pin and
  the text together.
- **D2, the frontend vocabulary.** Every harness text uses the same words:
  - **The layers:**
    - `app/` routes only, with route groups `(site)` and `(auth)`;
    - `widget/<section>/`;
    - `feature/<action>/`, an action from the glossary;
    - `entity/<noun>/`, a noun from the glossary;
    - `shared/`.

    Imports point down that list only, and the boundaries lint enforces it.
  - **The typed client:** `shared/api/generated/`, imported only by a slice's `server/` (Next)
    or `api/` (SPA) segment and by `shared/auth`. Implementers confirm this rule against the
    template at the tag.
  - **Loading and errors:** loading and error states per route group, and a skeleton per
    widget.
  - **Sizing:** 44 px on coarse pointers only (`pointer-coarse:`).
  - **The env module:** `shared/config/env.ts`.
- **D3, the brand flow** (OQ1, OQ2):
  - The Design form gives the brand values.
  - `bootstrap-project` maps them to flags, and `bootstrap.mjs` passes the flags through.
  - The generator validates them and records them in the provenance (`answers.brand`).
- **D4, the `AGENTS.md` budget.**
  - The frontend bullets shrink to the layer list plus a pointer.
  - `start` gets its own row. `e2eDb` joins the `testDb` row.
  - The scaffolder sentence gains the one exception.
  - Other lines are trimmed to end at 1,200 words or fewer.
- **D5, the frontend report.**
  - `Features:` becomes `Slices: <entity/, feature/, widget/ directories touched>`.
  - The screenshots are named by the template's pattern,
    `test-results/screens/<route>-<viewport>-<theme>.png`.
  - The "where the package has a `phone` project" hedge goes.
- **D6, old projects keep working.** `review.mjs` keeps `**/lib/api/schema.d.ts` for 1.x
  projects. The new generated path is covered by the existing `**/api/generated/**` glob, and a
  test proves it. The `security.mjs` comment and `dev-loop`'s trigger list name
  `shared/config/env.ts`; the behaviour is unchanged.

### Tasks

H1–H4 work on disjoint files in parallel. A Sonnet review follows each one.

| Task | Content | Files |
| --- | --- | --- |
| H1, scripts | D3's flags; D6 | `scripts/bootstrap.mjs`, `scripts/bootstrap.test.mjs`; `scripts/verify/review.mjs`, `scripts/verify/security.mjs` and their tests in `scripts/verify.test.mjs` and `scripts/verify/helpers.test.mjs` (new-path fixtures next to the 1.x ones); the `scripts/provenance.test.mjs` fixture |
| H2, always-loaded text | D2, D4; survey items 2–12, 39, 41 | `AGENTS.md`, `.claude/rules/naming.md`, `.claude/rules/ui-and-styling.md`, `.doc/product-definition.md` (Design form, OQ2), `.doc/glossary.md`, `README.md` |
| H3, plan and code skills | D2, D5; survey items 15–17, 21 (paths only), 22, 33–36 | `.claude/agents/frontend.md`; `writing-plans` (`SKILL.md`, `template.md`); `writing-tests`, `api-design`, `error-handling`, `code-review` |
| H4, operating skills | D3's mapping, OQ3; survey items 23 (the brand mapping only), 24, 25, 30–32, 38 | `bootstrap-project`, `deployment`, `database`, `dev-loop` |
| H5, the lock (the driver, after the reviews) | D1; survey item 1 | `catalog.lock`, then the V03 sweep |

Then an Opus final review of the branch and a fix wave.

### Proof P3a

P3a runs in a disposable sibling clone, `C:/Dev/Playground/AI/fullstack-dev-harness-proof-015`,
made from the branch head. It uses an Opus driver and P1's brief (`proof-prompt.md` in plan 012's
ledger), with the backlog reduced to brief line 2 (OQ4). It runs when no other project holds
ports 3000, 4000, 5173, 8000 or 5432; the session checks and asks.

Every hex in a P3a command is quoted (`'#ea580c'`), because an unquoted `#` starts a shell
comment.

1. Bootstrap `next-bun-express` with postgres from the brief. Its Design says `#ea580c` and "a
   cool neutral grey".
2. In a second clone folder, bootstrap `react-python-fastapi` with brand flags that differ from
   the defaults: `--font inter`, `--theme dark`, `--density compact`, `--radius lg`.
3. Run a bootstrap with `--brand-primary '#ggg'`. It must fail before generating, naming
   `--brand-primary`. No valid hex fails on contrast from the CLI: the generator adjusts
   lightness until every pair passes (catalog `tools/tests/theme.test.ts`).
4. Run the dev loop once, on brief line 2, in the `next-bun-express` clone. Measure it with
   `loop-stats`.

## Validation

- V01 — `bootstrap.mjs` forwards the seven brand options and still rejects an unknown argument.
  Proof: `node --test scripts/bootstrap.test.mjs`.
- V02 — The review package excludes `frontend/src/shared/api/generated/**` and still excludes
  1.x's `schema.d.ts`. The security trigger fires on `frontend/src/shared/config/env.ts`.
  Proof: `node --test scripts/verify.test.mjs scripts/verify/helpers.test.mjs`.
- V03 — No harness text names a v1.3.0 frontend path or rule. Proof: this grep over
  `AGENTS.md`, `README.md`, `.claude/` and `.doc/` returns no line:
  `lib/api|src/env\.ts|feature/<name>|feature/post|route segment|ActionResult|schema\.d\.ts|44 × 44`.
  In `scripts/`, only the 1.x fixtures and D6's exclusion may match.
- V04 — `AGENTS.md` is at 1,200 words or fewer. Proof: the word count in the ledger.
- V05 — P3a, both stacks: `bootstrap.mjs` accepts the v1.4.0 lock, and the bootstrap's
  `verify` exits 0: `check` per package, e2e on `phone` and `desktop`, and the screens spec.
  Proof: each clone's `verify.json`.
- V06 — P3a, the brand:
  - `.fullstack/catalog.yaml`'s provenance records `answers.brand.primary: "#ea580c"`;
  - the `--primary` token in `globals.css` (written in OKLCH) has orange's hue, about 41°
    (`#ea580c` is `oklch(0.646 0.194 41.1)`), not the default blue's, about 264°;
  - `home-phone-light.png` shows the orange;
  - step 3 fails, naming `--brand-primary`.

  Proof: the provenance, the `--primary` line of `globals.css`, the screenshot, the bootstrap
  output.
- V07 — P3a, the loop task:
  - committed after one fix round or none;
  - every new frontend file sits in an `entity/`, `feature/`, `widget/` or `app/` path that
    the template's map allows;
  - the lint is green;
  - per-stage minutes are recorded for plan 016.

  Proof: `verify.json`, `git diff --stat <Base>`, `loop-stats`.
- V08 — Each H task got a Sonnet review, and the branch an Opus final review, with no open P0
  or P1. Proof: the ledger `.superpowers/sdd/015-2026-10-28-frontend-foundation-adopt/progress.md`.

## Risks

- **An inferred survey fact is wrong.** Examples: the glob semantics, the shadcn hook behaviour,
  the schema check. Mitigation: each one has a test (V01, V02) or a proof step (V05), and the
  implementers read the template at the tag.
- **The word budget cuts guidance agents need.** Mitigation: point at the package's `AGENTS.md`
  instead of repeating it. P3a's loop task (V07) shows whether the pointers suffice.
- **The text drifts again at the next catalog release.** Mitigation: fewer repeated facts mean
  less to drift. V03's grep becomes the lock-bump checklist in `README.md`.
- **A converted colour is a guess.** Mitigation: the hex is shown in the stack confirmation, and
  the generator adjusts it until every contrast pair passes.
- **P2 compares poorly with P1 and P1b.** On v1.4.0, brief line 1's auth screens ship with the
  template. Mitigation: plan 016 states how P2 compares with P1/P1b (the same brief, so less
  work), or picks a replacement line 1.
- **Windows socket exhaustion** (`ERR_NO_BUFFER_SPACE`, plan 013). Mitigation: one re-run, noted.

## Rollout Order

1. G1: Eitan sets `Status: active`.
2. H1 ∥ H2 ∥ H3 ∥ H4, each followed by its review.
3. H5: the lock bump and the V03 sweep.
4. The Opus final review and a fix wave.
5. P3a, then the As built section, then the PR into `dev` on Eitan's yes.

## Rollback

One branch, merged with a merge commit. Reverting it restores the v1.3.0 pin and its text
together. P3a runs in disposable clones.

## Changes during the task

- OQ3 corrected. The data-layer task exists only when the bootstrap wired no database, so it
  also adds `e2eDb` (named in the backend report's `Commands:` line). Its plan carries a
  frontend step that wires the e2e start chain as the template's `server:database` variant
  does. `.claude/agents/backend.md` joins H4 for that line.
- Survey item 21 (the UX template line) moves to plan 016 with B4. H3 does item 22 only.
- No commits until Eitan's yes. Task reviews read working-tree diffs per task file set.
- Final review (Opus) found four Important issues; one fix wave addressed them:
  - On a stack with a frontend, the data-layer line is full-stack, not `stack:backend`. Its
    frontend stage wires the e2e chain from template files the driver hands over in the
    dispatch.
  - `AGENTS.md` lets a `model.ts` import its types and the `zod.gen` schemas.
  - P3a step 3 now uses a malformed hex, since no valid hex fails on contrast. V06 compares the
    OKLCH hue.
  - The README keeps 1.x projects on the earlier harness.
- After P3a (Eitan, 2026-10-28: "Patch v1.4.1 first"):
  - This plan writes the catalog for one patch, v1.4.1, which fixes C1–C3 (As built) and adds a
    case per frontend with non-default brand values.
  - C3's fix moves the primary's lightness, keeping its hue, until it passes as text on the
    background, cards and popovers. The move is not capped (ledger R17).
  - The lock moves to v1.4.1 on this branch, and P3a's bootstrap steps 1–3 re-run on it, without
    the loop.
  - PR #26 stays a draft until then.

## As built

2026-10-28, on `feat/frontend-foundation-adopt` (Base cc9fb1f):

- Commits: 7b408e2 (the plan), b8019b8 (scripts), 77965c0 (text), d6e490b (the lock at v1.4.0),
  e2e1571 (this section), 042e266 (the lock at v1.4.1), then the v1.4.1 results.
- Process:
  - H1 ∥ H2 ∥ H3 ∥ H4 had Sonnet implementers and a Sonnet review each; H3 and H4 needed one
    fix round each.
  - The Opus final review found 4 Important and 15 Minor findings. One fix wave followed and its
    re-review closed them all.
- Gates on d6e490b, re-run after P3a: scripts 142/142, hooks 1680/1680, `AGENTS.md` 1,195 words.

**P3a** ran in two disposable clones of d6e490b, from an empty catalog cache:

| Step | Result |
| --- | --- |
| 1. `next-bun-express` with postgres, Opus driver, P1's brief | The skill mapped the Design to seven flags, turning "a cool neutral grey" into `#64748b`. Bootstrap took 11 min. Its first `verify` was red on catalog defect C3; the driver darkened the light `--primary` by hand, and the second run was green. |
| 2. `react-python-fastapi`, `--font inter --theme dark --density compact --radius lg` | The flags were recorded and applied. `verify` was red on C1 and then C2; nothing else failed. |
| 3. `--brand-primary '#ggg'` | Refused before generating: `--brand-primary: "#ggg" is not a hex colour`. The clone was untouched, and step 2 then ran in it. |
| 4. The dev loop on brief line 2, in clone 1 | 32.7 min. Committed after one fix round; the commit tree equals `verify.json`'s tree. |

Three catalog defects at v1.4.0. None is in the harness, and P3a found nothing else:

- **C1:** react 2.0.0 `tests/unit/theme-provider.test.tsx:155` uses `'__THEME_DEFAULT__'` as its
  "anything else" value. The generator substitutes it, so `--theme light|dark` fails `check`.
- **C2:** in next and react 2.0.0, `tests/e2e/shell.spec.ts`'s desktop density test expects
  36 px. `--density compact` renders 32 px and fails `testE2e`.
- **C3:** `tools/lib/theme.ts` has no text pair for the primary on the background, card or
  popover, yet shadcn's `link` variant uses exactly that. `#ea580c` passes the generator and
  then fails the axe scan at 3.55:1. So the claim (OQ2, Risks, `bootstrap-project`) that the
  generator adjusts the colour until every contrast pair passes is untrue for this pair.

**Catalog v1.4.1** fixes all three. It shipped through catalog PR #14 into `dev` (d11f25a, CI
30/30) and release PR #15 into `main` (6a81924, CI 60/60), tagged v1.4.1. It contains:

- `frontend/next` and `frontend/react` 2.0.1;
- the primary moved, with its hue kept, until it passes as text on all three surfaces (R17);
- a `note:` line whenever the generator moves the primary;
- an optional `brand` on a test case, and one brand case per frontend, which `validate`
  requires;
- two Next e2e timing flakes, fixed.

The work had a Sonnet implementer, an Opus review (0 Critical, 0 Important, 8 Minor) and one fix
round with a clean re-review.

**The P3a bootstraps on v1.4.1** ran in fresh clones of 042e266, from an empty cache, with no
hand edits:

| Step | Result |
| --- | --- |
| 1. `next-bun-express` with postgres, the flags the P3a driver chose | The generator noted `#ea580c ships as oklch(0.571 0.175 41.1) in light mode`. `verify` passed: `check`, `testDb` and e2e 36/36. |
| 2. `react-python-fastapi`, `--font inter --theme dark --density compact --radius lg` | `verify` passed: `check` 927 and 252, e2e 38/38. |
| 3. `--brand-primary '#ggg'` | Refused, naming the flag; the tree was untouched. |

The loop task, measured with `loop-stats`:

| Stage | Minutes |
| --- | --- |
| Plan (orchestrator, Opus) | 6.2 |
| Delegated approval, then the backend contract | 1.6, then 1.4 |
| Backend ∥ frontend, to the first full `verify` | 9.5 |
| General and security reviews (Opus) ∥ QA (Sonnet) | 5.4 (QA: 1.1) |
| Fix round 1, with its re-review | 7.3 |
| Total, first plan dispatch to commit | 32.7 |

- Subagent context was 20.0M (once per message); driver context was 17.9M; the driver cost
  $19.03.
- P1b averaged 31.5 min and 10.7M per task, on a smaller diff. This task renamed the template's
  roles and removed its reference module: 83 files, +2,324/−1,470.

Validation:

| Item | Result | Evidence |
| --- | --- | --- |
| V01 | Holds | `bootstrap.test.mjs`; 142/142 |
| V02 | Holds | The verify and helpers tests; 142/142 |
| V03 | Holds | Only `dev-loop:151` matches, and it is exempt (R6) |
| V04 | Holds | 1,195 words |
| V05 | Holds on v1.4.1 | Both stacks' bootstrap `verify` passes with no hand edit: `check` per package, e2e on `phone` and `desktop`, and the screens spec. On v1.4.0 it failed (C1, C2, C3). |
| V06 | Holds on v1.4.1 | `answers.brand.primary: "#ea580c"`. The generated light `--primary` is `oklch(0.571 0.175 41.1)`, orange's 41° hue, moved for contrast (C3). Step 3 is refused, naming the flag. `home-phone-light.png` has no primary element, so the evidence is `sign-in-phone-light.png`, which shows the generated orange. |
| V07 | Holds | Every new frontend file sits in `app/(site)/(staff)/`, `widget/schedule`, `widget/publish-class`, `feature/publish-class` or `entity/class`. The lint is green, and the stage minutes are above. |
| V08 | Holds | The ledger |

Follow-ups (proposed, not queued):

- **Catalog docs:**
  - ADR 0005 does not describe the uncapped primary move;
  - compact density leaves the Account menu icon button at 36 px.
- **`bootstrap-project`:**
  - a recovery path for a brand the generator accepted that then fails a gate (the generator
    refuses a second run);
  - "keep the tree still while `verify` runs" (P1b reported it too);
  - compare the product's roles and auth criteria with what the template ships.
- **For plan 016, from the driver's notes:**
  - a contract change made after the contract stage cost relays both ways;
  - role agents' shell writes were refused (4 true positives) and went unreported;
  - the security trigger misses role gates in a module and the seed script.
- **Catalog `AGENTS.md`:**
  - `server/bun-express` says to drop the reference module, then keeps pointing at it, and its
    only `withTransaction` example goes with it;
  - the Auth sections assume `user`/`admin`.
- Left for Eitan:
  - the clones `C:/Dev/Playground/AI/fullstack-dev-harness-proof-015`, `…-proof-015-react`,
    `…-proof-015b` and `…-proof-015b-react`;
  - the volumes `proof-studio-015_database-data`, `proof-studio-015-appcheck_database-data`
    and `proof-studio-015b_database-data`;
  - the images `proof-studio-015-appcheck-{frontend,backend,backend-migrate}`.
