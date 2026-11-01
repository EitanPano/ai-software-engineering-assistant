import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { expect, type Page } from '@playwright/test'

import { uniqueToken } from './source-support'

// A server name the journey owns: `github` and `fixture` are shared by parallel journeys, so a
// journey that changes a server makes its own. The name rule is `[A-Za-z0-9_-]+` with no `__`.
export const uniqueServerName = () => `e2e-${uniqueToken()}`

// Seeds a disabled third-party server whose pin is older than its listing, with `note` at `ask`
// (backend/tests/seed_changed_server.py). It writes only to `databaseUrl`, which the caller has
// checked ends in `_e2e` (the same guard as `grantAdmin`), and never to the development database.
export function seedChangedServer(databaseUrl: string, name: string): void {
  execFileSync('uv', ['run', 'python', '-m', 'tests.seed_changed_server', name], {
    cwd: fileURLToPath(new URL('../../../backend', import.meta.url)),
    env: { ...process.env, E2E_DATABASE_URL: databaseUrl },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
}

// Opens a server's page from the list, as an admin does, and returns once the detail page is up:
// the list rows carry the same badges, so a caller's assertion must not run on the list.
export async function openServer(page: Page, name: string) {
  await page.goto('/mcp-server')
  await page.getByRole('link', { name, exact: true }).click()
  await expect(page).toHaveURL(/\/mcp-server\/[^/]+$/)
  await expect(page.getByRole('heading', { level: 1, name: 'MCP server' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name })).toBeVisible()
}
