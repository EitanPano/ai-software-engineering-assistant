import { expect, test } from '@playwright/test'

import { registerThroughUi } from './auth-support'
import {
  OWNER,
  REPOSITORY,
  connectRepository,
  releaseEmbedding,
  signInAsAdmin,
  sourceRow,
  uniqueToken,
} from './source-support'
import { expectNoSeriousViolations } from './support'

// The journeys need the GitHub and Voyage fakes and a database to promote an admin in, which only
// the suite's own servers provide (playwright.config.ts), so a run against a Compose stack
// (E2E_BASE_URL) leaves them out when the tests are collected.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())
const INDEXED = { timeout: 30_000 } // the list refreshes every 3 s until a row settles

if (!EXTERNAL) {
  defineJourneys()
}

function defineJourneys() {
  test.describe('source', () => {
    test('an admin connects a repository and watches it become ready', async ({ page }) => {
      test.setTimeout(90_000)
      const repository = REPOSITORY.fixture(uniqueToken())
      await signInAsAdmin(page)

      await page.goto('/source')
      await expect(page.getByRole('heading', { level: 1, name: 'Sources' })).toBeVisible()
      await expectNoSeriousViolations(page)

      await page.getByRole('link', { name: 'Connect repository' }).click()
      await expect(page).toHaveURL(/\/source\/connect$/)
      await expect(page.getByLabel('Repository URL')).toBeVisible()
      await expectNoSeriousViolations(page)

      await page.getByLabel('Repository URL').fill(`https://github.com/${OWNER}/${repository}`)
      await page.getByRole('button', { name: 'Connect repository' }).click()

      await expect(page).toHaveURL(/\/source$/)
      const row = sourceRow(page, repository)
      await expect(row).toBeVisible()
      await expect(row.getByText('Ready')).toBeVisible(INDEXED)
      await expect(row.getByText(/\d+ documents?/)).toBeVisible()
      await expect(row.getByText(/\d+ chunks?/)).toBeVisible()
      await expectNoSeriousViolations(page)
    })

    test('a missing repository is an error on the url field', async ({ page }) => {
      test.setTimeout(60_000)
      await signInAsAdmin(page)

      await connectRepository(page, REPOSITORY.missing(uniqueToken()))

      const url = page.getByLabel('Repository URL')
      await expect(url).toHaveAttribute('aria-invalid', 'true')
      await expect(page.getByText(/couldn't find a public repository/i)).toBeVisible()
      await expect(page.getByRole('button', { name: 'Connect repository' })).toBeEnabled()
      await expect(page).toHaveURL(/\/source\/connect$/)
      await expectNoSeriousViolations(page)
    })

    test('a malformed url is refused on the field before any call', async ({ page }) => {
      test.setTimeout(60_000)
      await signInAsAdmin(page)

      await page.goto('/source/connect')
      await page.getByLabel('Repository URL').fill('http://github.com/e2e/not-https')
      await page.getByRole('button', { name: 'Connect repository' }).click()

      await expect(page.getByText(/Enter the repository as/)).toBeVisible()
      await expect(page.getByRole('button', { name: 'Connect repository' })).toBeEnabled()
      await expectNoSeriousViolations(page)
    })

    test('a failed source shows its reason and a retry recovers it', async ({ page, request }) => {
      test.setTimeout(120_000)
      const key = uniqueToken()
      const repository = REPOSITORY.embedFail(key)
      await signInAsAdmin(page)

      await connectRepository(page, repository)

      await expect(page).toHaveURL(/\/source$/)
      const row = sourceRow(page, repository)
      await expect(row.getByText('Failed')).toBeVisible(INDEXED)
      await expect(row.getByText(/embedding service/i)).toBeVisible()
      await expect(row.getByRole('button', { name: /^Retry indexing/ })).toBeEnabled()
      await expectNoSeriousViolations(page)

      await releaseEmbedding(request, key)
      await row.getByRole('button', { name: /^Retry indexing/ }).click()

      await expect(row.getByText('Ready')).toBeVisible(INDEXED)
      await expect(row.getByRole('button', { name: /^Retry indexing/ })).toHaveCount(0)
      await expectNoSeriousViolations(page)
    })

    test('a user is sent to /forbidden and sees no Sources entry', async ({ page }) => {
      test.setTimeout(60_000)
      await registerThroughUi(page)

      await expect(page.getByRole('link', { name: 'Sources' })).toHaveCount(0)
      await page.goto('/source')

      await expect(page).toHaveURL(/\/forbidden$/)
      await expect(page.getByRole('link', { name: 'Sources' })).toHaveCount(0)
      await expectNoSeriousViolations(page)
    })
  })
}
