# Product Definition

Fill every `<!-- FILL: … -->` marker before the first plan. The `bootstrap-project` skill
walks this file with you; the orchestrator refuses to plan against a section that still
holds a marker. Delete a marker only by replacing it with a decision.

## Purpose

<!-- FILL: one paragraph. What this product does and for whom, in plain words. -->

## Problem Statement

<!-- FILL: the situation that exists today and why it is worth changing. -->

## Value Proposition

<!-- FILL: the one thing a user gets here that they do not get elsewhere. -->

## Target Users

- Primary users: <!-- FILL: who they are and what they are trying to do -->
- Secondary users: <!-- FILL: or "none" -->

## Product Scope

- In scope (v1):
  <!-- FILL: three to seven capabilities, each one line, each testable -->
- Out of scope (v1):
  <!-- FILL: what is deliberately not built now -->

## Auth and Tenancy

- Authentication: <!-- FILL: none | email+password | magic link | OAuth (which providers) -->
- Authorization: <!-- FILL: roles and what each may do, or "every signed-in user is equal" -->
- Tenancy: <!-- FILL: single tenant | multi-tenant (which entity owns data, e.g. `org`) -->

## Non-functional Requirements

- Accessibility: WCAG 2.2 AA <!-- FILL: confirm or change -->
- Browsers: last two versions of Chrome, Firefox, Safari, Edge <!-- FILL: confirm or change -->
- Performance: <!-- FILL: e.g. first page under 2 s on a 4G connection -->
- Locale: <!-- FILL: single language (which) | multiple (which) -->
- Search and sharing: <!-- FILL: yes | no. Do any public pages need to be found by search engines or show a rich preview when shared? -->
- Data retention and privacy: <!-- FILL: anything the product must or must not keep -->

## Design

The brief every frontend task follows (`.claude/rules/ui-and-styling.md`); a `figma:<url>`
backlog marker overrides it for one task. The bootstrap passes the display name, colours,
radius, type, density and default theme to the frontend generator as flags.

- Tone: <!-- FILL: two or three adjectives, e.g. calm, dense, playful -->
- Reference apps: <!-- FILL: one to three products whose look is the target, or "none" -->
- Display name: <!-- FILL: the product name shown in the header and the page title -->
- Primary colour: <!-- FILL: one hex value, e.g. #1d4ed8 -->
- Neutral colour: <!-- FILL: one hex value, e.g. #64748b -->
- Radius: <!-- FILL: sm | md | lg -->
- Type: <!-- FILL: system | inter -->
- Density: <!-- FILL: comfortable | compact -->
- Primary viewport: <!-- FILL: phone first | desktop first; the breakpoints that matter -->
- Default theme: <!-- FILL: system | light | dark; the theme toggle always ships -->

## Acceptance Criteria

Each criterion must be provable by a test or a command. Keep the numbering stable; QA
reports against it.

- AC01 — Quality gates: every package's `check` command is green, and the
  e2e suite passes.
- AC02 — <!-- FILL: the first user-visible capability, phrased as a provable statement -->
- AC03 — <!-- FILL -->

## Ready to plan

- [ ] No `FILL` marker remains in Purpose, Target Users, Product Scope, Auth and Tenancy, Design or
      Acceptance Criteria, nor in the Search and sharing line.
- [ ] `.doc/architecture.md` has its data model and API sections filled.
- [ ] `.doc/glossary.md` names every entity used above.
