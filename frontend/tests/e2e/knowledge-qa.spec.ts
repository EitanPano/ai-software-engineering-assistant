import { mkdirSync } from 'node:fs'

import { expect, test, type Page } from '@playwright/test'

import { MARKER, sendMessage, uniqueToken } from './conversation-support'
import { REPOSITORY, connectRepository, signInAsAdmin, sourceRow } from './source-support'
import { screenProblems } from './support'

// QA's capture of the screen the UI pass could not: /conversation/:id after a research run, with
// its tool rows and bounded output boxes, in both themes and at two widths. The journey itself is
// knowledge.spec.ts; this one adds the screenshots, the machine checks in both themes, and the
// keyboard. A run's tool rows come from the run's events, so each capture is on the live page.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())
const DIRECTORY = 'test-results/knowledge-qa'

async function capture(page: Page, name: string): Promise<string[]> {
  await page.waitForLoadState('networkidle')
  await page.evaluate(() => document.fonts.ready)
  mkdirSync(DIRECTORY, { recursive: true })
  await page.screenshot({ path: `${DIRECTORY}/${name}.png`, fullPage: true })
  return screenProblems(page)
}

async function research(page: Page) {
  await page.goto('/conversation')
  await page.getByRole('button', { name: 'Start conversation' }).click()
  await expect(page).toHaveURL(/\/conversation\/[^/]+$/)
  await sendMessage(page, `Where is it handled? ${MARKER.research}`)
  const log = page.getByRole('log')
  await expect(log.getByText('knowledge__search', { exact: true })).toHaveCount(2, {
    timeout: 30_000,
  })
  await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled()
  return log
}

if (!EXTERNAL) {
  test.describe('knowledge qa', () => {
    test('the research run screen holds in both themes and its outputs are reachable by keyboard', async ({
      page,
    }) => {
      test.setTimeout(240_000)
      await signInAsAdmin(page)
      const repository = REPOSITORY.fixture(uniqueToken())
      await connectRepository(page, repository)
      await expect(sourceRow(page, repository).getByText('Ready')).toBeVisible({ timeout: 30_000 })
      const problems: string[] = []

      const log = await research(page)
      const regions = log.getByRole('group', { name: /Output of knowledge__search/ })
      await expect(regions).toHaveCount(2)
      await regions.first().focus()
      await expect(regions.first()).toBeFocused()
      const box = await regions.first().evaluate((el) => ({
        overflowY: getComputedStyle(el).overflowY,
        tabIndex: el.tabIndex,
      }))
      expect(box.overflowY).toMatch(/auto|scroll/)
      expect(box.tabIndex).toBe(0)
      problems.push(...(await capture(page, 'conversation-run-phone-light')))

      const phone = page.viewportSize()
      await page.setViewportSize({ width: 1280, height: 800 })
      problems.push(...(await capture(page, 'conversation-run-desktop-light')))
      if (phone) await page.setViewportSize(phone)

      await page.evaluate(() => {
        localStorage.setItem('theme', 'dark')
      })
      await page.goto('/conversation')
      await expect(page.locator('html')).toHaveClass(/dark/)
      await research(page)
      problems.push(...(await capture(page, 'conversation-run-phone-dark')))

      expect(problems).toEqual([])
    })
  })
}
