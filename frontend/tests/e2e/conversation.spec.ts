import { expect, test } from '@playwright/test'

import { MARKER, TEXT, release, startAndSend, uniqueToken } from './conversation-support'
import { expectNoSeriousViolations } from './support'

// The journeys need the scripted Anthropic fake, which only the suite's own servers start
// (playwright.config.ts), so a run against a Compose stack (E2E_BASE_URL) leaves them out when the
// tests are collected.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())

// Registered only when the suite starts its own servers; nothing skips at run time.
if (!EXTERNAL) {
  defineJourneys()
}

function defineJourneys() {
  test.describe('conversation', () => {
    test('streams the answer as it is written', async ({ page, request }) => {
      const key = uniqueToken()
      await startAndSend(page, `Explain ${MARKER.hold(key)}`)

      // The first part is on screen while the fake still holds the rest: the stream is progressive
      // end to end (fake, API, vite preview proxy, browser).
      const log = page.getByRole('log')
      await expect(log.getByText(TEXT.first)).toBeVisible()
      await expect(log.getByText(TEXT.rest)).toHaveCount(0)
      await expectNoSeriousViolations(page)

      await release(request, key)

      await expect(log.locator('strong', { hasText: TEXT.strong })).toBeVisible()
      await expect(log.getByText(TEXT.first)).toBeVisible()

      await page.reload()
      await expect(page.getByRole('log').locator('strong', { hasText: TEXT.strong })).toBeVisible()
      await expect(page.getByRole('log').getByText(TEXT.first)).toBeVisible()
      // After a reload the form follows the latest run, and Send is enabled once that run is read
      // as finished, which can come after first paint.
      await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled()
      await expectNoSeriousViolations(page)
    })

    test("shows a tool call's start and result", async ({ page }) => {
      await startAndSend(page, `Look it up ${MARKER.tool(TEXT.toolName)}`)

      const log = page.getByRole('log')
      await expect(log.getByText(TEXT.toolName, { exact: true })).toBeVisible()
      await expect(log.getByText('Denied')).toBeVisible()
      await expect(log.getByText(TEXT.toolDone)).toBeVisible()
      // The run has ended once Send is enabled again; its fade from disabled starts only then.
      await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled()
      await expectNoSeriousViolations(page)
    })

    test('catches up after a reload mid-run', async ({ page, request }) => {
      const key = uniqueToken()
      await startAndSend(page, `Explain ${MARKER.hold(key)}`)
      await expect(page.getByRole('log').getByText(TEXT.first)).toBeVisible()

      await page.reload()

      await expect(page.getByRole('log').getByText(TEXT.first)).toBeVisible()
      await release(request, key)
      await expect(page.getByRole('log').locator('strong', { hasText: TEXT.strong })).toBeVisible()
      // Each part once, though the stream was reopened.
      await expect(page.getByRole('log').getByText(TEXT.first)).toHaveCount(1)
    })

    test('reports a failed run and keeps the form enabled', async ({ page }) => {
      await startAndSend(page, `Say something ${MARKER.refuse}`)

      await expect(page.getByRole('alert').filter({ hasText: /declined/i })).toBeVisible()
      await expect(page.getByLabel('Message')).toBeEnabled()
      await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled()
      await expectNoSeriousViolations(page)
    })
  })
}
