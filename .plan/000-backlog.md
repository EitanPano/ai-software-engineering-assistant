# Prioritized Backlog

tracker: none

One task per line, highest priority first. The dev loop takes the first unchecked line.

Grammar:

- `- [ ] <title>` — a full-stack task (backend, frontend, qa stages; the plan may drop
  the backend stage when nothing touches the API or the database)
- `- [ ] <title> | stack:frontend` — frontend-only; no backend stage is planned
- `- [ ] <title> | stack:backend` — backend-only (a migration, or the data layer when the stack has
  no frontend); no frontend stage is planned
- `- [ ] <title> | figma:<url>` — design reference for the frontend agent
- `tracker: none | linear` above — where tickets are recorded

Example: `- [ ] user can sign in with email`

## Queue

<!-- empty: the bootstrap-project skill adds the first task here -->

## DONE

<!-- moved here by the dev loop with the date and the plan number -->
