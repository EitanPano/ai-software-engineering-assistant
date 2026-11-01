import { expect, test } from '@playwright/test'

import { MARKER, sendMessage, uniqueToken } from './conversation-support'
import { REPOSITORY, connectRepository, signInAsAdmin, sourceRow } from './source-support'
import { expectNoSeriousViolations } from './support'

// The journey needs the knowledge server, the Voyage and Anthropic fakes and a database to promote
// an admin in, which only the suite's own servers provide (playwright.config.ts), so a run against
// a Compose stack (E2E_BASE_URL) leaves it out when the tests are collected.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())

if (!EXTERNAL) {
  defineJourneys()
}

function defineJourneys() {
  test.describe('knowledge', () => {
    test('searches twice and cites the file and line', async ({ page }) => {
      test.setTimeout(120_000)
      await signInAsAdmin(page)
      const repository = REPOSITORY.fixture(uniqueToken())
      await connectRepository(page, repository)
      await expect(page).toHaveURL(/\/source$/)
      await expect(sourceRow(page, repository).getByText('Ready')).toBeVisible({ timeout: 30_000 })

      await page.goto('/conversation')
      await page.getByRole('button', { name: 'Start conversation' }).click()
      await expect(page).toHaveURL(/\/conversation\/[^/]+$/)
      await sendMessage(page, `Where is it handled? ${MARKER.research}`)

      const log = page.getByRole('log')
      // Two tool rows, each with its result, in place before the answer.
      await expect(log.getByText('knowledge__search', { exact: true })).toHaveCount(2, {
        timeout: 30_000,
      })
      await expect(log.getByText('Succeeded')).toHaveCount(2)
      await expect(log.getByRole('group', { name: /Output of knowledge__search/ })).toHaveCount(2)
      // The answer cites a path with its lines.
      await expect(log.getByText(/\S+:\d+-\d+/).last()).toBeVisible()
      await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled()
      await expectNoSeriousViolations(page)
    })
  })
}
