import { defineConfig, devices } from '@playwright/test'

import { e2eDatabaseUrl } from './scripts/e2e-database-url'

// Two modes. By default Playwright starts the API and the production build of this app
// (`vite build`, then `vite preview` on the template's port, which forwards /api to the API), so
// a journey exercises the real contract on the bundle the image serves. With E2E_BASE_URL set
// (the catalog's case runner does, against the Compose stack) it starts nothing and targets that
// origin.
// A blank value (a CI variable exported empty) counts as unset.
const external = process.env.E2E_BASE_URL?.trim() || undefined
const origin = external ?? 'http://127.0.0.1:5173'
// The browser-test database (app_e2e), never the development one. E2E_DATABASE_URL overrides it,
// and anything that is not a *_e2e database is refused when the config loads. Container mode
// starts no API, so it neither reads nor checks the variable.
const databaseUrl = external
  ? ''
  : e2eDatabaseUrl(process.env.E2E_DATABASE_URL, 'postgres://app:app@127.0.0.1:5432/app_e2e')

const FAKE_PORT = 8101
const GITHUB_FAKE_PORT = 8102
const VOYAGE_FAKE_PORT = 8103
const KNOWLEDGE_PORT = 8104
// A placeholder both sides share; it signs nothing and protects only this suite's own processes.
const KNOWLEDGE_TOKEN = 'e2e-placeholder-knowledge-token-not-a-secret'
// The value the fake GitHub MCP server falls back to when it reads no `GITHUB_MCP_TOKEN` itself.
const GITHUB_MCP_PLACEHOLDER = 'dev-only-github-mcp-token-not-real-0123456789'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: true,
  retries: 0,
  // In this order: `web-server-tail` prints after `list`'s summary, where `verify` keeps it.
  reporter: [['list'], ['./scripts/web-server-tail.ts']],
  use: {
    baseURL: origin,
    trace: 'retain-on-failure',
  },
  projects: [
    // A test tagged @phone or @desktop belongs to one project; the other project's filter
    // leaves it out, so nothing skips at run time (a skip hides a test from the count).
    // Every journey, with its axe scan, on a touch phone.
    { name: 'phone', use: { ...devices['Pixel 7'] }, grepInvert: /@desktop/ },
    // The shell's desktop densities and the desktop screens.
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'] },
      testMatch: ['**/shell.spec.ts', '**/screens.spec.ts'],
      grepInvert: /@phone/,
    },
  ],
  webServer: external
    ? undefined
    : [
        {
          // The scripted Anthropic fake (backend/tests/fake_anthropic.py): an ASGI app speaking the
          // Messages API's SSE wire format, so the SDK's real stream handling runs in e2e with no
          // network and no key. It listens before the API starts; a journey picks its script by
          // markers in the message it sends.
          name: 'anthropic',
          command: 'uv run python -m tests.fake_anthropic',
          cwd: '../backend',
          url: `http://127.0.0.1:${FAKE_PORT}/health`,
          reuseExistingServer: false,
          timeout: 120_000,
        },
        {
          // The GitHub fake (backend/tests/fake_github.py): the fixture repository as a tarball
          // behind a 302, the repository name picking the script. Listens before the API.
          name: 'github',
          command: 'uv run python -m tests.fake_github',
          cwd: '../backend',
          url: `http://127.0.0.1:${GITHUB_FAKE_PORT}/health`,
          reuseExistingServer: false,
          timeout: 120_000,
        },
        {
          // The Voyage fake (backend/tests/fake_voyage.py): deterministic unit vectors, and a
          // marker that fails the call until released.
          name: 'voyage',
          command: 'uv run python -m tests.fake_voyage',
          cwd: '../backend',
          url: `http://127.0.0.1:${VOYAGE_FAKE_PORT}/health`,
          reuseExistingServer: false,
          timeout: 120_000,
        },
        {
          // A fresh API every run (never a leftover one with someone's data), with its limits
          // scaled so the suite does not trip them. Playwright starts web servers before its
          // global setup, so the browser-test database is prepared in the same command, before
          // the API connects to it. The seed comes after `e2e-db`, whose restore deletes the last
          // run's `fixture` MCP server row: it registers the `fixture` server (served by the
          // Anthropic fake's process) with its `note` tool at `ask`, for the approval journeys.
          name: 'api',
          command:
            'uv run poe e2e-db && uv run python -m tests.seed_ask_tool && uv run python -m app.main',
          cwd: '../backend',
          url: 'http://127.0.0.1:8000/api/health',
          reuseExistingServer: false,
          timeout: 120_000,
          env: {
            RATE_LIMIT_SCALE: '100',
            // The SDK talks to the fake; the key is a placeholder it never checks (and is not
            // shaped like a real one).
            ANTHROPIC_BASE_URL: `http://127.0.0.1:${FAKE_PORT}`,
            ANTHROPIC_API_KEY: 'e2e-placeholder-not-a-key',
            GITHUB_BASE_URL: `http://127.0.0.1:${GITHUB_FAKE_PORT}`,
            VOYAGE_BASE_URL: `http://127.0.0.1:${VOYAGE_FAKE_PORT}`,
            VOYAGE_API_KEY: 'e2e-placeholder-not-a-key',
            E2E_DATABASE_URL: databaseUrl,
            DATABASE_URL: databaseUrl,
            KNOWLEDGE_MCP_URL: `http://127.0.0.1:${KNOWLEDGE_PORT}/mcp`,
            KNOWLEDGE_MCP_TOKEN: KNOWLEDGE_TOKEN,
            // The fake GitHub MCP server, served from the Anthropic fake's process. The token is a
            // placeholder it checks; the PAT is the gateway's alone and is not set here.
            GITHUB_MCP_URL: `http://127.0.0.1:${FAKE_PORT}/github/mcp`,
            GITHUB_MCP_TOKEN: GITHUB_MCP_PLACEHOLDER,
          },
        },
        {
          // Our `knowledge` MCP server, the process the agent's search tool calls. It starts after
          // the API because the API's command prepares the database (a second `e2e-db` would
          // empty its tables) and it connects postgres alone. Voyage is the fake. `stdout` stays
          // at Playwright's default (ignored), as on the API but for another reason: it sends no
          // one-time code, its warnings, errors and tracebacks arrive on stderr, and its info
          // lines would crowd the 12-line tail.
          name: 'knowledge',
          command: 'uv run python -m app.knowledge_main',
          cwd: '../backend',
          url: `http://127.0.0.1:${KNOWLEDGE_PORT}/health`,
          reuseExistingServer: false,
          timeout: 120_000,
          env: {
            APP_PROCESS: 'knowledge',
            PORT: String(KNOWLEDGE_PORT),
            DATABASE_URL: databaseUrl,
            VOYAGE_BASE_URL: `http://127.0.0.1:${VOYAGE_FAKE_PORT}`,
            VOYAGE_API_KEY: 'e2e-placeholder-not-a-key',
            KNOWLEDGE_MCP_TOKEN: KNOWLEDGE_TOKEN,
          },
        },
        {
          // The production bundle behind `vite preview`, which proxies /api to the API above
          // (vite.config.ts). The build runs first, so a broken bundle fails here.
          name: 'preview',
          command: 'bun run build && bun run preview',
          url: origin,
          stdout: 'pipe',
          reuseExistingServer: false,
          timeout: 300_000,
        },
      ],
})
