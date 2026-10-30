---
name: ui-design
description: Turn a brief into page decisions and judge a screen against a rubric. Use when planning a route's UX section, when the frontend agent composes a page or runs its UI pass, or when QA reads screenshots. Covers page decisions, page patterns, copy rules and the ten-check rubric.
---

# UI design

Composition only. Tokens, sizing, primitives, status badges and the pattern components'
props are in the package's `frontend/AGENTS.md › Styling`; read it, do not restate it here.
`figma:<url>` on a backlog line overrides the brief.

## Inputs

- `.doc/product-definition.md › Design`: Tone, Reference apps, Primary viewport, Density.
- The plan's `UX` section, one line per route:
  `- /<route> — <pattern> — <primary action> — states: loading <…> · empty <…> · error <…> — tone: <…> — phone: <…>`
- `.doc/glossary.md` for every noun and action on screen.

## Page decisions

- One primary action per view: one filled button, the rest outline or ghost.
- Hierarchy from the type scale: one `h1` per page, always through `PageHeader`; `Section`
  titles are `h2`.
- Spacing rhythm: `gap-2` inside a control group, `gap-4` between fields, `gap-6` or `gap-8`
  between sections. `Page` already sets `gap-6`.
- Container width by pattern: form `max-w-xl`, list `max-w-3xl`, dashboard full width.
- Status by `Badge` tone, always with its text label; never colour alone.
- Density from the brief: a dense brief tightens rows, never the touch targets.

## Page patterns

Pattern components: `Page`, `PageHeader`, `Section`, `EmptyState`, `ErrorState`,
`ListSkeleton`, `CardSkeleton`, `AuthCard`, `FormActions`, `ConfirmDialog` (both frontends ship
all ten in `shared/ui/pattern/`). Use one before writing a layout by hand.

- **list**: `Page` > `PageHeader` (title, the create action) > `Section` with the rows in a
  `max-w-3xl` column. Row: name, a status `Badge`, secondary text muted, row actions at the
  end. Empty: `EmptyState` with the next step. Loading: `ListSkeleton` of the row count.
  Error: `ErrorState` with retry.
- **detail**: `Page` > `PageHeader` (the entity's name, edit as the primary action, delete as
  a ghost or outline button that opens a `ConfirmDialog`) > `Section`s titled by meaning
  (facts, history). Loading: `CardSkeleton` per section.
- **form**: `Page` > `PageHeader` > one `max-w-xl` form of the `shared/ui/form` bindings,
  `gap-4` between fields, fields grouped in `Section`s when over six, `FormActions` last
  (submit primary, cancel outline). Field errors sit under the field; a submit failure is an
  `ErrorState` or an alert above `FormActions`, in the user's words.
- **auth**: `AuthCard` alone in the page, no `PageHeader`; its title is the `h1`. One primary
  action; the switch to the other auth route is a link beneath.
- **dashboard** (a dashboard or a table view): `Page` > `PageHeader` > `Section`s at full
  width; summary cards in a responsive grid (`grid gap-4 sm:grid-cols-2 lg:grid-cols-4`), a
  table under them. The table scrolls inside its own container on phones; the page never does.
  Loading: `CardSkeleton` per card, `ListSkeleton` for the table.
- **landing** (a home or content page): `Page` > `PageHeader` (the product's name, the one
  primary action) > `Section`s of content, each titled by meaning, in a `max-w-3xl` column. No
  form beside the primary action; a signed-out home links to `auth`. Empty and loading follow
  the section's own pattern.
- **confirm** (a destructive confirm): `ConfirmDialog` only. The title names the thing, the
  body states the consequence, the confirm button is destructive and says the verb ("Delete
  plant"), the cancel is the default focus.
- **Empty, loading, error** are states of a pattern, not patterns. Each is designed: an
  `EmptyState` says what is missing and offers the one next step; a skeleton matches the
  shape it replaces; an `ErrorState` says what failed and offers retry.

## Copy rules

- Concise and action-oriented: a verb for a button ("Save plant", not "Submit"), a noun
  phrase for a title.
- Use the glossary's terms, never a synonym.
- No server text: never render an API message, status code or id. Map an error `code` to copy
  the frontend owns (`error-handling`).
- Sentence case. No exclamation marks, no filler ("Please", "Oops").

## Rubric

Ten checks applied to three screenshots per route: `frontend/test-results/screens/<route>-phone-light.png`,
`<route>-phone-dark.png` and `<route>-desktop-light.png` (`home` for `/`; a nested route is
slugged, `/staff/class` is `staff-class`). Machine-checked ones are enforced by the screens spec
and `verify`; the passes judge only the judged ones.

1. One obvious primary action. Judged.
2. A clear `h1` and visible grouping. Machine-checked: exactly one `h1`. Judged: the grouping.
3. A consistent spacing rhythm. Judged.
4. The brand accent used only for action and emphasis: one accent on calm neutrals. Judged.
5. Status readable without colour. Judged.
6. Empty, loading and error states designed, not left as defaults. Judged.
7. A phone header that neither wraps nor cramps. Machine-checked: no horizontal overflow.
   Judged: the header's wrap and crowding.
8. Dark mode legible. Machine-checked: the WCAG AA contrast scan in both themes. Judged:
   surfaces, borders and images still read.
9. Copy concise and action-oriented. Judged.
10. Nothing looks like a default browser control. Judged.

## Severity

A rubric failure is a P2. A broken journey or a WCAG AA failure is a P1. The frontend agent
fixes what it finds once per route; what is still open goes to `Handoff`, so the pass does
not loop on taste. QA reports against the same numbers.
