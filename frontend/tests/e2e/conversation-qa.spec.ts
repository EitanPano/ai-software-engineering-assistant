import { mkdirSync } from 'node:fs'

import { expect, test, type Page } from '@playwright/test'

import { registerThroughUi } from './auth-support'
import {
  MARKER,
  TEXT,
  release,
  sendMessage,
  startAndSend,
  uniqueToken,
} from './conversation-support'
import { expectNoSeriousViolations, screenProblems } from './support'

// QA's adversarial journeys and the extra screens (populated, streaming, failed, long history).
// Like the product journeys they need the scripted fake, which only the suite's own servers start.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())
const DIRECTORY = 'test-results/qa-screens'

async function snap(page: Page, name: string, theme: 'light' | 'dark') {
  await page.evaluate((value) => {
    localStorage.setItem('theme', value)
  }, theme)
  await page.reload()
  await expect(page.locator('html')).toHaveClass(theme === 'dark' ? /dark/ : /^(?!.*dark)/)
  await page.waitForLoadState('networkidle')
  mkdirSync(DIRECTORY, { recursive: true })
  await page.screenshot({ path: `${DIRECTORY}/${name}-${theme}.png`, fullPage: false })
  await page.screenshot({ path: `${DIRECTORY}/${name}-${theme}-full.png`, fullPage: true })
  expect(await screenProblems(page), `${name} ${theme}`).toEqual([])
}

if (!EXTERNAL) {
  test.describe('conversation QA', () => {
    test('a populated, long history keeps the send form reachable and the page free of overflow', async ({
      page,
    }) => {
      test.setTimeout(120_000)
      await startAndSend(page, 'First question about the repository')
      const log = page.getByRole('log')
      await expect(log.getByText(TEXT.strong.length ? 'scripted' : '')).toBeVisible()
      for (let index = 2; index <= 6; index++) {
        // The previous answer must be finished (button enabled) before the next send.
        await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled()
        await sendMessage(
          page,
          `Question number ${String(index)} with a rather longer body `.repeat(3),
        )
        await expect(log.getByText(`Question number ${String(index)}`).first()).toBeVisible()
        await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled()
      }
      await page.reload()
      await expect(page.getByRole('log')).toBeVisible()
      await snap(page, 'detail-long-history', 'light')
      await snap(page, 'detail-long-history', 'dark')

      // The form is stuck to the bottom of the viewport on the phone while the history is taller.
      await page.evaluate(() => {
        window.scrollTo(0, 0)
      })
      const form = page.getByRole('button', { name: 'Send message' })
      const box = await form.boundingBox()
      const viewport = page.viewportSize()
      if (!box || !viewport) throw new Error('the send button or the viewport has no size')
      expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 1)
      expect(box.y).toBeGreaterThan(0)
      await expectNoSeriousViolations(page)
    })

    test('a streaming run and a failed run render and the list shows the conversation', async ({
      page,
      request,
    }) => {
      test.setTimeout(120_000)
      const key = uniqueToken()
      await startAndSend(page, `Explain ${MARKER.hold(key)}`)
      await expect(page.getByRole('log').getByText(TEXT.first)).toBeVisible()
      // Captured in place: a reload would wait for the held stream to end (networkidle).
      mkdirSync(DIRECTORY, { recursive: true })
      await page.screenshot({ path: `${DIRECTORY}/detail-streaming-live.png` })
      await expect(page.getByRole('log').getByText(TEXT.first)).toBeVisible()
      await release(request, key)
      await expect(page.getByRole('log').locator('strong', { hasText: TEXT.strong })).toBeVisible()
      await page.goto('/conversation')
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await snap(page, 'list-populated', 'light')
      await snap(page, 'list-populated', 'dark')

      await page
        .getByRole('link')
        .filter({ hasText: /Explain|conversation/i })
        .first()
        .click()
      await expect(page).toHaveURL(/\/conversation\/[^/]+$/)
      await sendMessage(page, `Now fail ${MARKER.refuse}`)
      await expect(page.getByRole('alert').filter({ hasText: /declined/i })).toBeVisible()
      await snap(page, 'detail-failed', 'light')
      await snap(page, 'detail-failed', 'dark')
    })

    test('a tool call row renders in both themes', async ({ page }) => {
      await startAndSend(page, `Look it up ${MARKER.tool(TEXT.toolName)}`)
      await expect(page.getByRole('log').getByText(TEXT.toolDone)).toBeVisible()
      await snap(page, 'detail-tool', 'light')
      await snap(page, 'detail-tool', 'dark')
    })

    test('an empty message is refused in the form and nothing is sent', async ({ page }) => {
      await registerThroughUi(page)
      await page.goto('/conversation')
      await page.getByRole('button', { name: 'Start conversation' }).click()
      await expect(page).toHaveURL(/\/conversation\/[^/]+$/)
      await page.getByLabel('Message').fill('   ')
      await page.getByRole('button', { name: 'Send message' }).click()
      await expect(page.getByText('Enter a message')).toBeVisible()
      await expect(page.getByRole('log').getByText('Hello')).toHaveCount(0)
    })

    test('a message over 32000 characters is refused in the form', async ({ page }) => {
      await registerThroughUi(page)
      await page.goto('/conversation')
      await page.getByRole('button', { name: 'Start conversation' }).click()
      await expect(page).toHaveURL(/\/conversation\/[^/]+$/)
      await page.getByLabel('Message').fill('a'.repeat(32_001))
      await page.getByRole('button', { name: 'Send message' }).click()
      await expect(page.getByLabel('Message')).toHaveAttribute('aria-invalid', 'true')
      await expect(page.getByLabel('Message')).toHaveValue('a'.repeat(32_001))
    })

    test('a send by keyboard during an active run is refused and keeps the text', async ({
      page,
      request,
    }) => {
      const key = uniqueToken()
      await startAndSend(page, `Explain ${MARKER.hold(key)}`)
      await expect(page.getByRole('log').getByText(TEXT.first)).toBeVisible()

      const box = page.getByLabel('Message')
      await box.fill('second message while writing')
      await box.press('Control+Enter')
      // The 409 is worded by the copy table, and the text stays for another try.
      await expect(page.getByText(/still writing/i).first()).toBeVisible()
      await expect(box).toHaveValue('second message while writing')

      await release(request, key)
      await expect(page.getByRole('log').locator('strong', { hasText: TEXT.strong })).toBeVisible()
      await expect(page.getByRole('log').getByText('second message while writing')).toHaveCount(0)
    })

    test('another account cannot open a conversation by its address', async ({ page, browser }) => {
      await startAndSend(page, 'private words 7f3a')
      const path = new URL(page.url()).pathname

      const context = await browser.newContext()
      const other = await context.newPage()
      await registerThroughUi(other)
      await other.goto(path)
      // Another account's conversation is a 404: an alert, never the owner's text.
      await expect(other.getByRole('alert')).toBeVisible()
      await expect(other.getByText('private words 7f3a')).toHaveCount(0)
      await expect(other.getByRole('log')).toHaveCount(0)
      await expectNoSeriousViolations(other)
      await context.close()
    })

    test('a signed-out visit to a conversation goes to sign in', async ({ page }) => {
      await page.goto('/conversation')
      await expect(page).toHaveURL(/sign-in/)
      await page.goto('/conversation/00000000-0000-0000-0000-000000000000')
      await expect(page).toHaveURL(/sign-in/)
    })

    test('an unknown conversation id shows an error state, not a blank page', async ({ page }) => {
      await registerThroughUi(page)
      await page.goto('/conversation/00000000-0000-0000-0000-000000000000')
      await expect(page.getByRole('alert')).toBeVisible()
      await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
      await expect(page.getByRole('log')).toHaveCount(0)
      await expectNoSeriousViolations(page)
    })
  })
}
