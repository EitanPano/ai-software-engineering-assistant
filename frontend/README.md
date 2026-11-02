# Frontend

Vite, React 19 and React Router 8 in data mode, with TanStack Query for server state and a
Tailwind design system. How to run the whole project is in the [root README](../README.md). The
layer map, styling rules and test rules are in [`AGENTS.md`](AGENTS.md).

## Commands

| Command             | What it does                                                                                         |
| ------------------- | ---------------------------------------------------------------------------------------------------- |
| `bun install`       | Install from the lockfile                                                                            |
| `bun run dev`       | Start the dev server on port 5173, proxying `/api` to the API on port 8000                           |
| `bun run check`     | Types, lint, format and unit tests                                                                   |
| `bun run test`      | Unit tests only                                                                                      |
| `bun run test:e2e`  | Playwright on a phone and a desktop project against the production build, with an accessibility scan |
| `bun run build`     | Write the static app to `dist/`                                                                      |
| `bun run preview`   | Serve `dist/` on the same port with the same proxy; the e2e suite runs it                            |
| `bun run api:types` | Regenerate `src/shared/api/generated/` from `../backend/openapi.json`                                |
| `bun run format`    | Rewrite the files                                                                                    |

In production there is no frontend server: the API's image serves the built files.

## Where things live

Imports only point down this list, and lint enforces it.

| Layer                   | What it holds                             | Example                                   |
| ----------------------- | ----------------------------------------- | ----------------------------------------- |
| `src/app/`              | Routes only                               | `routes.tsx`                              |
| `src/widget/<section>/` | A section of a screen                     | `widget/conversation-history`             |
| `src/feature/<action>/` | One thing a user does                     | `feature/approve`, `feature/send-message` |
| `src/entity/<noun>/`    | One domain noun                           | `entity/conversation`, `entity/run`       |
| `src/shared/`           | UI kit, auth and the generated API client | `shared/ui`, `shared/api/generated`       |

Types come from the backend's OpenAPI contract, never by hand. Controls come from `shared/ui`, and
colours and sizes from the design tokens, so a raw `button` or a literal colour fails lint.
