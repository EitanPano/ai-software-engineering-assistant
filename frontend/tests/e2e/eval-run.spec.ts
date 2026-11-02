import { expect, test } from '@playwright/test'

import { registerThroughUi } from './auth-support'
import {
  COMPLETED,
  completedRun,
  e2eDatabaseUrl,
  seedEvalCases,
  startRun,
} from './eval-run-support'
import {
  REPOSITORY,
  connectRepository,
  signInAsAdmin,
  sourceRow,
  uniqueToken,
} from './source-support'
import { expectNoSeriousViolations } from './support'

// The journeys need the fakes, a database to promote an admin in and the seed script, which only
// the suite's own servers provide (playwright.config.ts), so a run against a Compose stack
// (E2E_BASE_URL) leaves them out when the tests are collected. Nothing registers under it.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())

if (!EXTERNAL) {
  defineJourneys()
}

function defineJourneys() {
  test.describe('eval run', () => {
    test('an admin starts a run, watches it complete and reads its scores', async ({ page }) => {
      test.setTimeout(150_000)
      const repository = REPOSITORY.fixture(uniqueToken())
      await signInAsAdmin(page)
      seedEvalCases(await e2eDatabaseUrl())
      await connectRepository(page, repository)
      await expect(sourceRow(page, repository).getByText('Ready')).toBeVisible({ timeout: 30_000 })

      await page.goto('/eval-run')
      await expect(page.getByRole('heading', { level: 1, name: 'Eval runs' })).toBeVisible()
      await expectNoSeriousViolations(page)

      await startRun(page)
      await expect(completedRun(page)).toBeVisible(COMPLETED)
      await expectNoSeriousViolations(page)

      await completedRun(page).click()
      await expect(page).toHaveURL(/\/eval-run\/[^/]+$/)
      await expect(page.getByRole('heading', { level: 1, name: 'Eval run' })).toBeVisible()
      await expect(page.getByText('Completed')).toBeVisible()
      await expect(page.getByRole('table', { name: 'Scores by search and kind' })).toBeVisible()
      await expect(page.getByRole('table', { name: 'Cases' })).toBeVisible()
      await expect(page.getByText('Recall@5').first()).toBeVisible()
      await expectNoSeriousViolations(page)
    })

    test('a plain user is sent to /forbidden and sees no nav entry', async ({ page }) => {
      await registerThroughUi(page)
      await expect(page.getByRole('link', { name: 'Eval runs' })).toHaveCount(0)

      await page.goto('/eval-run')

      await expect(page).toHaveURL(/\/forbidden$/)
      await expect(page.getByRole('button', { name: 'Start eval run' })).toHaveCount(0)
    })
  })
}
