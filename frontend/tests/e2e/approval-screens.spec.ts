import { mkdirSync } from 'node:fs'

import { expect, test, type Page } from '@playwright/test'

import { MARKER, TEXT, startAndSend } from './conversation-support'
import { screenProblems } from './support'

// QA capture of the approval row: waiting and each decided outcome, phone and desktop widths, both
// themes, with the screens checks (axe, no sideways scroll, one h1) on every shot. The row only
// exists on a call at `ask`, which the suite's own servers seed, so a Compose stack leaves it out.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())
const DIRECTORY = 'test-results/qa-approval'
const WIDTHS = { phone: { width: 412, height: 915 }, desktop: { width: 1280, height: 800 } }

async function shoot(page: Page, name: string, theme: string): Promise<string[]> {
  const problems: string[] = []
  for (const [label, size] of Object.entries(WIDTHS)) {
    await page.setViewportSize(size)
    await page.waitForLoadState('networkidle')
    mkdirSync(DIRECTORY, { recursive: true })
    await page.screenshot({ path: `${DIRECTORY}/${name}-${label}-${theme}.png`, fullPage: true })
    for (const problem of await screenProblems(page)) problems.push(`${name} ${label}: ${problem}`)
  }
  return problems
}

if (!EXTERNAL) {
  for (const theme of ['light', 'dark'] as const) {
    for (const outcome of ['approved', 'rejected'] as const) {
      test(`approval row, ${outcome}, ${theme} @phone`, async ({ page }) => {
        test.setTimeout(90_000)
        await page.addInitScript((value) => {
          localStorage.setItem('theme', value)
        }, theme)
        await startAndSend(page, `Write this down ${MARKER.tool(TEXT.askTool)}`)
        const log = page.getByRole('log')
        await expect(log.getByText('Needs approval')).toBeVisible()
        await expect(page.locator('html')).toHaveClass(theme === 'dark' ? /dark/ : /^(?!.*dark)/)

        const problems = await shoot(page, `waiting-${outcome}`, theme)

        await page.setViewportSize(WIDTHS.phone)
        const button = outcome === 'approved' ? 'Approve call' : 'Reject call'
        await page.getByRole('button', { name: button }).click()
        await expect(log.getByText(outcome === 'approved' ? 'Succeeded' : 'Denied')).toBeVisible()
        await expect(log.getByText(TEXT.toolDone)).toBeVisible()
        await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled()

        problems.push(...(await shoot(page, `decided-${outcome}`, theme)))
        expect(problems).toEqual([])
      })
    }
  }
}
