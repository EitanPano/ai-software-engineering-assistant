import { expect, test, type Page } from '@playwright/test'

import { registerThroughUi, signOutThroughUi } from './auth-support'
import { MARKER, sendMessage, startAndSend, uniqueToken } from './conversation-support'
import { expectNoSeriousViolations } from './support'

// The journeys need the scripted Anthropic and Voyage fakes and the knowledge server, which only
// the suite's own servers start (playwright.config.ts), so a run against a Compose stack
// (E2E_BASE_URL) leaves them out when the tests are collected.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())

if (!EXTERNAL) {
  defineJourneys()
}

const factOf = (token: string) => `My deploy notes live in ops-${token}.md`

// Signs up, states a fact in a first conversation and waits until `/memory` lists it: extraction
// runs after the run completed, so the row appears a moment later.
async function stateFact(page: Page, token: string): Promise<string> {
  await startAndSend(page, `Remember this ${MARKER.fact(factOf(token))}`)
  await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled({
    timeout: 30_000,
  })
  await expect(async () => {
    await page.goto('/memory')
    await expect(page.getByText(factOf(token))).toBeVisible({ timeout: 2_000 })
  }).toPass({ timeout: 30_000 })
  return factOf(token)
}

async function recallInNewConversation(page: Page) {
  await page.goto('/conversation')
  await page.getByRole('button', { name: 'Start conversation' }).click()
  await expect(page).toHaveURL(/\/conversation\/[^/]+$/)
  await sendMessage(page, `What did I tell you? ${MARKER.recall}`)
  const log = page.getByRole('log')
  await expect(log.getByText('knowledge__recall', { exact: true })).toBeVisible({
    timeout: 30_000,
  })
  await expect(log.getByText('Succeeded')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled()
  return log
}

function defineJourneys() {
  test.describe('memory', () => {
    test('uses a fact in a new conversation', async ({ page }) => {
      test.setTimeout(120_000)
      const fact = await stateFact(page, uniqueToken())
      await expectNoSeriousViolations(page)

      const log = await recallInNewConversation(page)

      // The fact is in the new conversation only because recall returned it.
      await expect(log.getByText(fact).first()).toBeVisible()
      await expectNoSeriousViolations(page)
    })

    test('a deleted memory is not used again', async ({ page }) => {
      test.setTimeout(120_000)
      const fact = await stateFact(page, uniqueToken())

      const row = page.getByRole('listitem').filter({ hasText: fact })
      await row.getByRole('button', { name: 'Delete memory' }).click()
      const dialog = page.getByRole('dialog', { name: 'Delete this memory?' })
      await expect(dialog).toContainText('No conversation will recall it')
      await expect(dialog).toContainText('already read it keeps it')
      await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
      await expectNoSeriousViolations(page)
      await dialog.getByRole('button', { name: 'Delete memory' }).click()

      await expect(page.getByText(fact)).toHaveCount(0)
      await page.reload()
      await expect(page.getByText('Nothing remembered yet')).toBeVisible()

      const log = await recallInNewConversation(page)
      await expect(log.getByText(fact)).toHaveCount(0)
    })

    test("keeps one person's memories from another", async ({ page }) => {
      test.setTimeout(120_000)
      const email = await registerThroughUi(page)
      const token = uniqueToken()
      await page.goto('/conversation')
      await page.getByRole('button', { name: 'Start conversation' }).click()
      await expect(page).toHaveURL(/\/conversation\/[^/]+$/)
      await sendMessage(page, `Remember this ${MARKER.fact(factOf(token))}`)
      await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled({
        timeout: 30_000,
      })
      await expect(async () => {
        await page.goto('/memory')
        await expect(page.getByText(factOf(token))).toBeVisible({ timeout: 2_000 })
      }).toPass({ timeout: 30_000 })

      await signOutThroughUi(page, email)
      await registerThroughUi(page)
      await page.goto('/memory')
      await expect(page.getByText('Nothing remembered yet')).toBeVisible()
      await expect(page.getByText(factOf(token))).toHaveCount(0)

      const log = await recallInNewConversation(page)
      await expect(log.getByText(factOf(token))).toHaveCount(0)
    })

    test('shows the empty state with a way back to the conversations', async ({ page }) => {
      await registerThroughUi(page)
      await page.goto('/memory')

      await expect(page.getByRole('heading', { level: 1, name: 'Memory' })).toBeVisible()
      await expect(page.getByText('Nothing remembered yet')).toBeVisible()
      await page.getByRole('link', { name: 'Go to conversations' }).click()
      await expect(page).toHaveURL(/\/conversation$/)
    })
  })
}
