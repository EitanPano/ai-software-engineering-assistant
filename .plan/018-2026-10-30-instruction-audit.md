# Instruction audit: every Markdown file judged as agent context

Status: done
Owner: Eitan
Last updated: 2026-10-30
Approval: delegated (2026-10-30, Eitan: "plan improvements, and implement where it would be better")
Branch: docs/instruction-audit
Base: bbdc7f4
Stages: harness only. The driver edits the text; Sonnet agents run the wording evals; one Opus agent
reviews the whole change. No commit until Eitan's yes.

## Goal

Every instruction an agent loads is correct, has one home, and costs no more context than it earns.
The evaluation of all 51 tracked Markdown files is in `## As built`. This plan fixes what the
evaluation found and adds a test so the same defects cannot return unnoticed.

## Scope

- In: the `.md` files, plus one new test (`scripts/docs.test.mjs`) and the manifest-covered supporting
  file it needs (`.claude/skills/database/data-layer-task.md`).
- Out: `.claude/hooks/` and every script's behaviour; the catalog repository; the archived plans
  001–017 beyond plan 012's wrong `Status:`; rewording text that loop proofs have already exercised
  and that has no defect, duplicate or cost finding.
- Out, proposed for later:
  - `- [ ] bootstrap: a recovery path for a brand that passes the generator and fails a gate`
  - `- [ ] verify: fail a swallowed expect(...).catch(...) on a test path`

## Assumptions

- A role's startup prompt is `AGENTS.md`, its rules, its agent body and its preloaded `skills:`, and
  it is re-read as cached context on every turn; plan 012's P1 and plan 014's P1b measured driver and
  subagent context as the main cost.
- Proven text stays: plans 012–017 ran it through real loops. A change needs a defect, a duplicate
  or a measured cost behind it.
- `AGENTS.md` keeps the 1,200-word limit plan 012 set (V08).
- Only the driver and the eval read the archived plans; setup removes them from every project.

## Open Questions

None. The one decision that belongs to Eitan, committing, waits at the end.

## Steps

### D1 Defects: text that is wrong or contradicts itself

1. `bootstrap-project`: remove the catalog read that contradicts section 2's three-file rule (plan 017
   follow-up); state how much of the forms to fill before the summary and which markers may stay
   (plan 017 and plan 011 follow-ups); remove the internal labels `P1` and `P3a`.
2. `deployment`, `bootstrap-project`, `.doc/architecture.md`: a missing `deploy:` means a lone package,
   not "a catalog before v1.2.0" (generator `resolveDeploy`).
3. `database`: the e2e chain sentence no longer names v1.4.0. `deployment`: drop the branch for
   catalogs older than `minCatalog`.
4. `.doc/architecture.md`: the Client model marker no longer says the template cannot forward the
   client address (`CLIENT_IP_HEADER` ships); the Data Flow list is one list.
5. `qa.md`: procedure order matches execution (format and test run after the adversarial tests, UX
   pass before any test run).
6. `frontend.md`: a driver instruction stops being addressed to the frontend.
7. `.claude/README.md`: the update section's bullets leave `### Older projects`, the two manual-update
   passages become one, and "this change" gets a referent.
8. `.plan/012`: `Status: done`. `.plan/000-backlog.md`: `stack:backend` no longer implies every
   data-layer line (parked in plan 015). `git-workflow.md` and `AGENTS.md`: push needs approval too.

### D2 One home per fact

1. Security trigger list: delete both glob copies (`dev-loop`, `code-review`); `verify` computes the
   answer and `scripts/verify/security.mjs` holds the list.
2. `reviewer.md`: drop the reading rules the preloaded `code-review` already holds.
3. Screenshot names: `ui-design › Rubric` is the home; `frontend.md` and `qa.md` point at it.
4. `writing-tests`: drop the gate paragraph each role's agent file already holds.
5. Refusals: one line in `AGENTS.md › Guardrails`, for every role, in place of `backend.md`'s.
6. `orchestrator.md`: drop the sizing numbers its preloaded `writing-plans` holds.

### D3 Context cost

1. `database`: move the once-per-project data-layer task into a supporting file read on demand.
2. Skill and agent descriptions: triggers only, no workflow; a size budget.
3. `cutting-a-release`: drop what any model knows; keep what is specific to this project.

### D4 Gaps the loop showed

1. `code-review`: a security reviewer's route for a non-security defect (plan 014 follow-up).
2. `dev-loop`: what the driver does when an agent ends with no report (plan 012 P1, run 1).

### D5 Keep it fixed

1. `scripts/docs.test.mjs`, written first and watched red on the real tree: description budget, the
   startup budget per role, `AGENTS.md`'s limit, pointers to paths, skills, sections and headings, and
   no catalog version older than `minCatalog`, no internal proof label.
2. `CONTRIBUTING.md`: the rules for changing an instruction file.

## Validation

- V01 — The new test failed on the unedited tree for the defects above — proof: red run in `## As built`.
- V02 — Both suites pass — proof: `node --test ".claude/hooks/test/*.test.mjs"`,
  `node --test "scripts/**/*.test.mjs"`.
- V03 — New descriptions select the right skill at least as often as the old ones, over a fixed prompt
  set with look-alike distractors — proof: the eval table in `## As built`.
- V04 — The data-layer task is reached when it applies and left alone when it does not, and QA's
  order is right — proof: micro-test results in `## As built`.
- V05 — The skill description listing shrinks by at least 40% and the backend's startup prompt by at
  least 1,000 tokens — proof: the before and after of `measure.mjs` in `## As built`.
- V06 — No instruction was lost: every removed sentence has a new home or a stated reason — proof:
  the Opus review of `git diff bbdc7f4`.
- V07 — `AGENTS.md` ≤ 1,200 words — proof: `scripts/docs.test.mjs`.

## Risks

- A shorter description stops a skill firing — V03 measures it before anything is kept.
- A role no longer reads a moved procedure — every pointer is conditional on an observable fact and
  V04 tests the main one.
- A fix to a false "dead" branch breaks a live case — each was checked against the generator first
  (the `deploy:` key is why D1.2 changes the meaning instead of deleting the line).

## Changes during the task

- **D3.2 reversed by measurement (V03, V05).** The first descriptions dropped every topic clause to
  reach V05's 40%. A forced-choice eval scored them 55/55, the same as the old text. Real `claude -p`
  sessions then showed they had stopped firing on knowledge questions (table in `## As built`), so
  "triggers only" was wrong: the guidance is against narrated steps, not topic words. Topic clauses
  went back on nine skills; workflow narration stayed out. V05's 40% is dropped, since it was a guess
  and the cut that met it was the cut that failed. The rule is now no loss of firing.
- **V03 is measured in real sessions.** Forced choice cannot show a loss.
- **The old `deploy:` rule was wrong, not dead (D1.2).** At catalog v1.5.0 and later a two-package
  stack always records `deploy:`, and a missing key means a lone package, so "n/a", not "split".
- **`/code-review` (decided).** The skill keeps its name. The docs say a project skill replaces the
  built-in command, and running the repository's own review there is the useful default.
  `.claude/README.md` says so and names `/ultrareview` as the way to the cloud review.
- **Compaction.** A re-attached skill keeps its first 5,000 tokens. `dev-loop` runs in long sessions,
  so it gets a word cap in `scripts/docs.test.mjs` and a line in `CONTRIBUTING.md`.
  `bootstrap-project` is longer and rarely compacts, so it gets one conditional line instead of a
  rewrite of proven text.
- **Changes no step named, each with its reason:**
  - `dev-loop` section 0 now points at `## Ready to plan` (a second list of the same sections);
  - `dev-loop` drops `--reuse` details the driver never acts on (`scripts/verify.mjs` computes them);
  - `AGENTS.md`'s `.doc/` row names the driver, which writes there (a wrong fact);
  - `bootstrap-project` section 5 is a numbered list (plans 011 and 017 asked what it requires);
  - `cutting-a-release` names `verify` in place of "every critical validation step" (vague).
- **Final review (Opus): 3 P1, 10 P2, all in text written for this plan; no instruction lost.** Its
  re-review passed with all 13 resolved and two new P2 text fixes, both applied.
  - `cutting-a-release`'s `verify` step could not pass in this repository: now conditional.
  - The new list of markers that may stay open was false with no provider, and leaving `Local
    service` open would have stopped the first task: section 5 writes `none yet: the data-layer task
    writes it`, and that task's item 8 fills it.
  - "Decide later" had become a valid answer for any marker, which removes a real guard: it is now
    the Data store engine's alone.
  - A breaking-change list in `cutting-a-release` was a new rule nobody asked for: removed.
  - The test's startup check, version pattern, arrow check and heading check were tightened or
    renamed to what they prove. Two limits stay: a bare version with no word `catalog` is missed, and
    later pointer segments are not checked.

## As built

2026-10-30, on `docs/instruction-audit` (Base bbdc7f4). Evidence, eval scripts and raw results:
`.superpowers/sdd/018-2026-10-30-instruction-audit/` (git-ignored).

### Validation

| Item | Result | Evidence |
| --- | --- | --- |
| V01 | Holds | `scripts/docs.test.mjs` on the unedited tree: 13 tests, 8 failed, on the defects above |
| V02 | Holds | hooks 1702/1702, scripts 275/275 (262 before, plus 13) |
| V03 | Holds as restated | Real sessions below: no loss on action prompts, none on Sonnet; on Haiku knowledge questions fire 58% against 69% |
| V04 | Holds | Data-layer pointer right on all 4 cases on Sonnet and on Haiku, including `providers: {}` with an unrelated task. QA order right on the new text on both models. Not a behaviour fix: the old text was right too on Haiku; the Sonnet control was lost to an API safeguard error and not retried |
| V05 | Partly, as restated | Backend startup −1,179 tokens (target ≥ 1,000). Listing −25%, not 40% (the target was dropped, see Changes) |
| V06 | Holds | The Opus review: every removed sentence has a home or was truly dead |
| V07 | Holds | `AGENTS.md` 1,198 words |

### Skill firing in real sessions

`claude -p` on two disposable clones with no remote, `--max-turns 3`, counting `Skill` calls with the
right name: 55 prompts, 39 action and 16 knowledge questions whose only keyword sat in a removed
`Covers` clause.

| Skill fired | All | Action | Knowledge |
| --- | --- | --- | --- |
| Haiku, old (3 reps) | 137/165 (83%) | 104/117 (89%) | 33/48 (69%) |
| Haiku, trimmed (2 reps) | 79/110 (72%) | 71/78 (91%) | 8/32 (25%) |
| Haiku, topic words (3 reps) | 135/165 (82%) | 107/117 (91%) | 28/48 (58%) |
| Sonnet, old (1 rep) | 48/55 | 37/39 | 11/16 |
| Sonnet, trimmed (1 rep) | 44/55 | 38/39 | 6/16 |
| Sonnet, topic words (1 rep) | 48/55 | 37/39 | 11/16 |

- Noise is large: the old text alone ranges 44 to 52 of 55 across its four Haiku runs. The first
  single run, old 52 against trimmed 41, overstated the gap; the repeats confirmed its direction.
- Forced choice (8 runs, old and trimmed, Sonnet and Haiku) scored 55/55 every time, including on the
  text real sessions showed to be worse.
- The topic-word text was measured on Haiku before its `bootstrap-project` clause was added; Sonnet
  saw the final text. The repository's descriptions equal the measured clone's.
- Limit: single-turn prompts in a fresh session. It measures whether a skill is invoked, not whether
  the session then does better work. The role agents preload their skills, so it does not touch them.
- Reported spend: $21.87, of which $19.18 was the Sonnet run (estimated at $3).

### Size

| Measure, estimated at 4 characters a token | Before | After |
| --- | --- | --- |
| Skill listing, every session | 4,969 chars | 3,713 chars (−25%) |
| Agent descriptions, every session | 1,814 chars | 1,246 chars (−31%) |
| Backend startup | 12,728 tok | 11,549 tok (−9%) |
| Reviewer startup | 5,021 tok | 4,686 tok (−7%) |
| Frontend startup | 8,622 tok | 8,429 tok |
| QA startup | 6,728 tok | 6,536 tok |
| Orchestrator startup | 6,416 tok | 6,415 tok |
| Driver (`dev-loop`) | 6,877 tok | 6,656 tok |

### Evaluation

Each file scored 0 to 5 on accuracy (checked against code, the pinned catalog and Claude Code's
docs), actionability (order, observable conditions, no contradiction), one home (no fact to drift),
context economy (cost against how often it loads) and discoverability (description, pointers,
headings). Rank 1 needs the most work; a tie goes to the file loaded more often. In each row the first
solution is the one selected.

| Rank | File | Score | Reason | Solutions, best first |
| --- | --- | --- | --- | --- |
| 1 | `.claude/skills/database/SKILL.md` | 14 → 21 | A once-a-project procedure preloaded into every backend run; a stale catalog version; the longest description | Move the task to an on-demand file · drop the skill from the backend's preload (agents would miss its rules) · leave it |
| 2 | `.claude/skills/bootstrap-project/SKILL.md` | 14 → 20 | Contradicted its own catalog rule (plan 017); internal labels; section 5 was one paragraph of eight duties; wrong `deploy:` meaning | Fix the defects, number section 5, keep proven text · split into files (rewrites a proven flow) · rewrite |
| 3 | `.claude/skills/dev-loop/SKILL.md` | 15 → 22 | A security glob list copied from a script; no path for an agent that ends with no report; pipeline in the description | Delete the mirror, add the path · generate the list from `security.mjs` (tooling for a fact no reader uses) · split by stage (more reads in long sessions) |
| 4 | `.doc/architecture.md` | 15 → 20 | A marker claimed the template cannot forward the client address; wrong `deploy:` fallback; a split list | Fix the markers · split out the auth model (no evidence it helps) |
| 5 | `.claude/skills/code-review/SKILL.md` | 16 → 22 | A second copy of the trigger list; no route for a non-security defect (plan 014) | One pointer to `security.paths`, add the route · a sync test (keeps the duplicate) · rename the skill (churn; the override is useful) |
| 6 | `.claude/agents/reviewer.md` | 16 → 24 | Repeated its own preloaded skill | Cut to role, inputs and lane · cut the skill instead (ad-hoc reviews lose it) |
| 7 | `.claude/README.md` | 16 → 21 | Update bullets stranded under `Older projects`; manual update told twice; "this change" with no referent | Reorder and merge · a separate update guide (more to find) |
| 8 | `.claude/skills/deployment/SKILL.md` | 17 → 21 | Wrong meaning of a missing `deploy:`; a branch for catalogs `minCatalog` refuses | Fix the two facts · move sections 2 and 3 out (on demand already, no gain) |
| 9 | `.claude/agents/qa.md` | 17 → 21 | Steps listed out of run order; screenshot names repeated | List steps in run order, point at the rubric (clarity: the control was right too) · leave the order |
| 10 | `.claude/agents/frontend.md` | 17 → 20 | Told the frontend to do the driver's job; screenshot names repeated | Reword for its role, point at the rubric · leave it |
| 11 | `.claude/skills/writing-tests/SKILL.md` | 17 → 21 | Restated what each agent file holds | Keep the rule, drop the procedure · drop the agent copies (those are the proven ones) |
| 12 | `.claude/skills/cutting-a-release/SKILL.md` | 17 → 23 | Mostly SemVer any model knows; "every critical validation step" names nothing | Keep what is specific, name the gate · keep as is · add a breaking-change policy (a rule nobody decided) |
| 13 | `.plan/012-2026-10-26-lean-loop.md` | 18 → 23 | `Status: active` on shipped work | Mark it `done` · leave it |
| 14 | `.claude/agents/backend.md` | 18 → 20 | Sole holder of a rule every role needs | Move the refusal line to `AGENTS.md` · copy it into each agent |
| 15 | `AGENTS.md` | 19 → 22 | Two wrong facts (who writes `.doc/`, push approval); partial-run detail only implementers use | Small fixes within 1,200 words · a deeper cut (proven at this size) |
| 16 | `.claude/skills/ui-design/SKILL.md` | 19 → 22 | No single home for the screenshot names | Make the Rubric the home · a new shared file |
| 17 | `.claude/agents/orchestrator.md` | 20 → 22 | Repeated the sizing numbers; could not reach the data-layer task | Drop the numbers, add the pointer · preload `database` (cost for one task a project) |
| 18 | `.claude/skills/api-design/SKILL.md` | 20 → 21 | Sound; long description | Tighten the description · split out auth (no evidence) |
| 19 | `.plan/016-2026-10-29-visual-loop.md` | 20 → 20 | Accurate, but its V09–V11 were never measured, so the visual loop has no proof | Leave it: the closing note is honest · re-run the proof (a separate decision) |
| 20 | `.claude/skills/error-handling/SKILL.md` | 21 → 22 | Sound; long description | Tighten the description · leave it |
| 21 | `.claude/skills/writing-plans/SKILL.md` | 21 → 22 | Sound; long description | Tighten the description · leave it |
| 22–28 | `.plan/001` to `007` | 21 → 21 | Done, with stale notes such as "uncommitted, awaiting review" in `Status:`; no reader, setup removes them | Leave the archive · rewrite the status lines |
| 29 | `.plan/000-backlog.md` | 22 → 24 | `stack:backend` implied every data-layer line (parked in plan 015) | Correct the line · leave it |
| 30 | `.claude/rules/git-workflow.md` | 23 → 24 | "push a tag" left pushing a branch unstated | Say push or tag · leave it |
| 31 | `CONTRIBUTING.md` | 23 → 24 | Sound; no rules for changing a prompt | Add them, with the evidence · leave it |
| 32 | `.claude/rules/ui-and-styling.md` | 23 → 23 | Some overlap with `ui-design`, but path-scoped, and each holds a different kind of rule | Leave it · merge them (loses the path scoping) |
| 33–40 | `.plan/008`–`011`, `013`–`015`, `017` | 23 → 23 | Accurate records; never loaded | Leave the archive · compress them |
| 41 | `.orchestrate/README.md` | 24 → 24 | Accurate, compact | Leave it |
| 42 | `.claude/rules/naming.md` | 24 → 24 | Accurate, compact | Leave it |
| 43 | `.doc/glossary.md` | 24 → 24 | Working form | Leave it |
| 44 | `.doc/product-definition.md` | 24 → 24 | Working form; its `Ready to plan` is now the one list | Leave it |
| 45 | `.claude/skills/writing-plans/template.md` | 24 → 24 | Matches its skill | Leave it |
| 46 | `README.md` | 24 → 24 | Plain, accurate, rewritten days ago | Leave it |
| 47 | `.claude/rules/code-style.md` | 25 → 25 | Short and path-scoped | Leave it |
| 48 | `CLAUDE.md` | 25 → 25 | A loader, as it should be | Leave it |
| 49 | `.doc/conventions.md` | 25 → 25 | Empty by design | Leave it |
| 50 | `.github/copilot-instructions.md` | 25 → 25 | A pointer, as it should be | Leave it |
| 51 | `.claude/skills/bootstrap-project/readme-template.md` | 25 → 25 | A template the script fills | Leave it |

Every catalog identifier and path these docs name exists in the pinned v1.5.1. The new supporting file
`.claude/skills/database/data-layer-task.md` holds the moved text, its header and item 8's two new
lines.

### Not done, with the reason

- The agents' `effort:` field: no evidence for any setting.
- Live proof in a loop: the text changed, the loop did not run. The next product task is the proof.
- The follow-ups under `Out` stay proposed, not queued.
