import { expect, test, type Page } from '@playwright/test'

import { MARKER, TEXT, startAndSend } from './conversation-support'
import { expectNoSeriousViolations } from './support'

// The journeys need the scripted Anthropic fake and the `fixture` MCP server seeded at `ask`, which
// only the suite's own servers provide (playwright.config.ts), so a run against a Compose stack
// (E2E_BASE_URL) leaves them out when the tests are collected.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())

if (!EXTERNAL) {
  defineJourneys()
}

// Sends the message that makes the fake ask for the `ask` tool, and waits for the question.
async function askForTheTool(page: Page) {
  await startAndSend(page, `Write this down ${MARKER.tool(TEXT.askTool)}`)
  const log = page.getByRole('log')
  await expect(log.getByText('Needs approval')).toBeVisible()
  return log
}

function defineJourneys() {
  test.describe('approval', () => {
    test('a call that needs approval shows its arguments, survives a reload and runs once approved', async ({
      page,
    }) => {
      const log = await askForTheTool(page)

      // The whole arguments, before any decision; send is off until the last one.
      const box = log.getByRole('group', { name: `Arguments of ${TEXT.askTool}` })
      await expect(box).toContainText(TEXT.askArguments)
      await expect(page.getByRole('button', { name: 'Send message' })).toBeDisabled()
      await expect(page.getByRole('status')).toContainText('waiting for your approval')
      await expectNoSeriousViolations(page)

      // Nothing was decided by looking: the question is still there after a reload.
      await page.reload()
      await expect(log.getByText('Needs approval')).toBeVisible()
      await expect(box).toContainText(TEXT.askArguments)
      await expect(page.getByRole('button', { name: 'Send message' })).toBeDisabled()

      await page.getByRole('button', { name: 'Approve call' }).click()

      await expect(log.getByText('Succeeded')).toBeVisible()
      await expect(log.getByText(TEXT.toolDone)).toBeVisible()
      await expect(page.getByRole('button', { name: 'Approve call' })).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled()
      await expectNoSeriousViolations(page)
    })

    test('a rejected call reaches the agent as denied', async ({ page }) => {
      const log = await askForTheTool(page)

      await page.getByRole('button', { name: 'Reject call' }).click()

      await expect(log.getByText('Denied')).toBeVisible()
      // The run goes on to its answer.
      await expect(log.getByText(TEXT.toolDone)).toBeVisible()
      await expect(page.getByRole('button', { name: 'Reject call' })).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled()
      await expectNoSeriousViolations(page)
    })
  })
}
