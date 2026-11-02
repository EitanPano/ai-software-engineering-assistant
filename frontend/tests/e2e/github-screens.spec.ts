import { mkdirSync } from 'node:fs'

import { expect, test, type Page } from '@playwright/test'

import { MARKER, TEXT, startAndSend } from './conversation-support'
import { screenProblems } from './support'

// QA capture of the waiting GitHub row with a body past a screen, then the adversarial journey: a
// rapid double click on Approve decides the call once. The row needs the scripted fakes, which only
// the suite's own servers provide, so a Compose stack leaves it out.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())
const DIRECTORY = 'test-results/qa-github'
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
    test(`github waiting row with a long body, ${theme} @phone`, async ({ page }) => {
      test.setTimeout(90_000)
      await page.addInitScript((value) => {
        localStorage.setItem('theme', value)
      }, theme)
      await startAndSend(page, `Comment on the issue ${MARKER.githubComment}`)
      const log = page.getByRole('log')
      await expect(log.getByText('Needs approval')).toBeVisible()
      await expect(
        log.getByRole('group', { name: `Arguments of ${TEXT.githubTool}` }),
      ).toContainText(TEXT.githubLastLine)

      const problems = await shoot(page, 'waiting', theme)

      await page.setViewportSize(WIDTHS.phone)
      await page.getByRole('button', { name: 'Approve call' }).click()
      await expect(log.getByText('Succeeded')).toBeVisible()
      problems.push(...(await shoot(page, 'decided', theme)))
      expect(problems).toEqual([])
    })
  }

  test('a rapid double click on Approve decides the GitHub call once @phone', async ({ page }) => {
    test.setTimeout(90_000)
    await startAndSend(page, `Comment on the issue ${MARKER.githubComment}`)
    const log = page.getByRole('log')
    await expect(log.getByText('Needs approval')).toBeVisible()

    const approve = page.getByRole('button', { name: 'Approve call' })
    await approve.dblclick({ noWaitAfter: true }).catch(() => undefined)

    await expect(log.getByText('Succeeded')).toBeVisible()
    await expect(log.getByText(TEXT.toolDone)).toBeVisible()
    await expect(log.getByText('Succeeded')).toHaveCount(1)
    await expect(log.getByText('Needs approval')).toHaveCount(0)
    await expect(page.getByRole('alert')).toHaveCount(0)
  })
}
