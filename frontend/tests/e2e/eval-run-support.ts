import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { expect, type Page } from '@playwright/test'

import { grantAdmin } from './source-support'

// Stores the fixture repository's eval cases (backend/tests/eval_support.py) in the browser-test
// database, through the backend's free seed script: no network, no key. It writes only to
// `databaseUrl`, which the callers have checked ends in `_e2e` (the same guard as `grantAdmin`),
// and replaces the fixture commit's cases, so running it twice leaves one set.
export function seedEvalCases(databaseUrl: string): void {
  execFileSync('uv', ['run', 'python', '-m', 'tests.seed_eval_fixture'], {
    cwd: fileURLToPath(new URL('../../../backend', import.meta.url)),
    env: { ...process.env, DATABASE_URL: databaseUrl },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
}

// A screens-spec `setup`: promote the account, then give the database its cases.
export async function grantAdminWithCases(account: {
  email: string
  databaseUrl: string
}): Promise<void> {
  await grantAdmin(account)
  seedEvalCases(account.databaseUrl)
}

export async function e2eDatabaseUrl(): Promise<string> {
  const { e2eDatabaseUrl: resolve } = await import('../../scripts/e2e-database-url')
  return resolve(process.env.E2E_DATABASE_URL, 'postgres://app:app@127.0.0.1:5432/app_e2e')
}

export const COMPLETED = { timeout: 60_000 } // the list refreshes every 3 s until a run settles

// A row of the list whose run is completed.
export const completedRun = (page: Page) => page.getByRole('link', { name: /Completed/ }).first()

// Clicks Start eval run. The one active run is global and journeys run in parallel, so the start
// may be refused as a 409 (another journey's run is active): either outcome is a toast, and the
// caller then waits for any completed row.
export async function startRun(page: Page) {
  await page.getByRole('button', { name: 'Start eval run' }).click()
  await expect(page.getByText(/Eval run started|already in progress/)).toBeVisible()
}
