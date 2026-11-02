import { expect, test } from '@playwright/test'

import { registerThroughUi } from './auth-support'
import { e2eDatabaseUrl } from './eval-run-support'
import { openServer, seedChangedServer, uniqueServerName } from './mcp-server-support'
import { signInAsAdmin } from './source-support'
import { expectNoSeriousViolations } from './support'

// The journey needs the seed script and a database to write to, which only the suite's own
// servers provide, so a run against a Compose stack (E2E_BASE_URL) leaves it out when the tests
// are collected. Nothing registers under it.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())

if (!EXTERNAL) {
  defineJourneys()
}

function defineJourneys() {
  test.describe('mcp server', () => {
    test('an admin reads a changed listing, accepts it, sets a policy and disables the server', async ({
      page,
    }) => {
      test.setTimeout(90_000)
      const name = uniqueServerName()
      await signInAsAdmin(page)
      seedChangedServer(await e2eDatabaseUrl(), name)

      await page.goto('/mcp-server')
      await expect(page.getByRole('heading', { level: 1, name: 'MCP servers' })).toBeVisible()
      await expect(page.getByRole('link', { name, exact: true })).toBeVisible()
      await expectNoSeriousViolations(page)

      await openServer(page, name)
      await expect(page.getByText('Listing changed')).toBeVisible()
      await expect(page.getByText('Disabled', { exact: true })).toBeVisible()
      await expect(page.getByRole('combobox', { name: 'Policy for note' })).toContainText('Ask')
      await expect(page.getByText(/never gets its tools/)).toBeVisible()
      await expectNoSeriousViolations(page)

      // The review shows both versions whole, and the accept comes after them.
      await page.getByRole('link', { name: 'Review listing' }).click()
      await expect(page.getByRole('heading', { level: 1, name: 'Review listing' })).toBeVisible()
      await expect(page.getByText('Accepted version')).toBeVisible()
      await expect(page.getByText('Live version')).toBeVisible()
      const accept = page.getByRole('button', { name: 'Accept listing' })
      await expect(accept).toBeVisible()
      await expectNoSeriousViolations(page)
      await accept.click()

      await expect(page).toHaveURL(/\/mcp-server\/[^/]+$/)
      await expect(page.getByText('Listing accepted', { exact: true }).first()).toBeVisible()
      await expect(page.getByText('Enabled', { exact: true })).toBeVisible()

      const select = page.getByRole('combobox', { name: 'Policy for note' })
      await select.click()
      await page.getByRole('option', { name: 'Allow' }).click()
      await expect(page.getByText('note set to allow')).toBeVisible()
      await expect(select).toContainText('Allow')

      // Leave the row disabled, as the seed made it.
      await page.getByRole('button', { name: 'Disable server' }).click()
      await expect(page.getByText('Disabled', { exact: true })).toBeVisible()
      await expectNoSeriousViolations(page)
    })

    test('a plain user is sent to /forbidden and sees no nav entry', async ({ page }) => {
      await registerThroughUi(page)
      await expect(page.getByRole('link', { name: 'MCP servers' })).toHaveCount(0)

      await page.goto('/mcp-server')

      await expect(page).toHaveURL(/\/forbidden$/)
    })
  })
}
