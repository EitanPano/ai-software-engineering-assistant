---
paths: ["frontend/**"]
---

# UI and styling

Applies to every frontend package.

- Design tokens are semantic CSS variables (a colour set that includes success, warning and
  info; spacing on a 4 px base; type; radius), generated from the brand. The package's
  `AGENTS.md › Styling` names the file and the utilities that expose them. A component uses
  those utilities only, never a literal colour or size.
- One toast library and one icon set per package, concise action-oriented toasts, the same
  icon for the same concept everywhere.
- No inline styles and no ad-hoc stylesheets beyond the package's token file.
- Semantic HTML, labelled controls, keyboard reachability. Every route has a loading and an
  error state, its own or its group's; every widget has a skeleton.
- Status is shown by a Badge chosen by meaning, with words or an icon, never by colour alone.
  A toast comes from a handler, not an effect.
- The accessibility scan in the e2e suite passes.
- Mobile first: the package's base styles are the phone layout and its breakpoints widen it
  (named in `AGENTS.md › Styling`). A new route is checked on the phone viewport first (the
  package's e2e `phone` project). No horizontal overflow at any viewport.
- Touch targets: 44 px on touch only (`pointer-coarse:`); on a fine pointer the WCAG 2.2
  minimum of 24 px holds. The shell spec asserts it on the `@phone` tests.
- `shared/ui` is the one place for a control; a raw control elsewhere fails the lint.
- The shell is `shared/ui/pattern/AppShell`: `<header>`, `<nav aria-label>`, the one `<main>`
  with a skip link, and `<footer>`, plus the theme toggle in the `UserMenu`. A feature adds its
  nav entry and renders inside `main`, never a second landmark set.
- The brief is `.doc/product-definition.md › Design`; a `figma:<url>` backlog marker overrides
  it for that task. The generator applies the brand values at the bootstrap; changing them
  later edits the tokens, by plan only.
