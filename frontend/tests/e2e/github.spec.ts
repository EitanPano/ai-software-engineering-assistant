import { expect, test } from '@playwright/test'

import { MARKER, TEXT, startAndSend } from './conversation-support'
import { expectNoSeriousViolations } from './support'

// The journey needs the scripted Anthropic fake with its GitHub MCP fake (`/github/mcp`) and the
// `github` server accepted by the seed, which only the suite's own servers provide
// (playwright.config.ts), so a run against a Compose stack (E2E_BASE_URL) leaves it out.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())

if (!EXTERNAL) {
  test.describe('github', () => {
    test('a person reads a whole GitHub comment above the decision buttons, approves it and reads the outcome', async ({
      page,
    }) => {
      await startAndSend(page, `Comment on the issue ${MARKER.githubComment}`)
      const log = page.getByRole('log')
      await expect(log.getByText('Needs approval')).toBeVisible()

      const box = log.getByRole('group', { name: `Arguments of ${TEXT.githubTool}` })
      await expect(box).toContainText(TEXT.githubArguments)
      await expect(box).toContainText(TEXT.githubLastLine)
      const approve = page.getByRole('button', { name: 'Approve call' })

      // The body runs past a screen, yet it is not clipped or scrolled: it sits whole above Approve.
      const approveHandle = await approve.elementHandle()
      const metrics = await box.evaluate((element, button) => {
        const rect = element.getBoundingClientRect()
        return {
          scrolls: element.scrollHeight > element.clientHeight + 1 || element.tabIndex >= 0,
          height: rect.height,
          gap: (button as Element).getBoundingClientRect().top - rect.bottom,
        }
      }, approveHandle)
      expect(metrics.scrolls).toBe(false)
      // Past the old 256 px cap.
      expect(metrics.height).toBeGreaterThan(256)
      expect(metrics.gap).toBeGreaterThanOrEqual(0)

      // No horizontal overflow with the long body.
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      )
      expect(overflow).toBe(false)
      await expectNoSeriousViolations(page)

      await approve.click()

      await expect(log.getByText('Succeeded')).toBeVisible()
      await expect(page.getByRole('button', { name: 'Approve call' })).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled()
      await expectNoSeriousViolations(page)
    })
  })
}
