import { mkdirSync } from 'node:fs'

import { expect, test } from '@playwright/test'

import { registerThroughUi } from './auth-support'
import { e2eDatabaseUrl } from './eval-run-support'
import { openServer, seedChangedServer, uniqueServerName } from './mcp-server-support'
import { signInAsAdmin } from './source-support'

// QA's attacks on the MCP server screens. Nothing registers when the suite targets a running
// stack, because the seed writes to the browser-test database only.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())
const SHOTS = process.env.QA_SHOTS_DIR

if (!EXTERNAL) {
  test.describe('qa: mcp server', () => {
    test('a rapid double click on accept pins once and leaves the server enabled', async ({
      page,
    }) => {
      test.setTimeout(90_000)
      const name = uniqueServerName()
      await signInAsAdmin(page)
      seedChangedServer(await e2eDatabaseUrl(), name)
      await openServer(page, name)
      await page.getByRole('link', { name: 'Review listing' }).click()
      const accept = page.getByRole('button', { name: 'Accept listing' })
      await expect(accept).toBeVisible()

      if (SHOTS) {
        mkdirSync(SHOTS, { recursive: true })
        await page.screenshot({ path: `${SHOTS}/changed-full.png`, fullPage: true })
        await accept.scrollIntoViewIfNeeded()
        await page.screenshot({ path: `${SHOTS}/changed-accept-viewport.png` })
        await page.getByText('Live version').first().scrollIntoViewIfNeeded()
        await page.screenshot({ path: `${SHOTS}/changed-versions-viewport.png` })
      }

      await accept.dblclick({ noWaitAfter: true })
      await expect(page).toHaveURL(/\/mcp-server\/[^/]+$/)
      await expect(page.getByText('Enabled', { exact: true })).toBeVisible()
      await expect(page.getByText('Listing accepted', { exact: true }).first()).toBeVisible()

      // Leave the row disabled, as the seed made it.
      await page.getByRole('button', { name: 'Disable server' }).click()
      await expect(page.getByText('Disabled', { exact: true })).toBeVisible()
    })

    test('a plain user opening a listing url is sent to /forbidden', async ({ page }) => {
      await registerThroughUi(page)
      await page.goto('/mcp-server/00000000-0000-0000-0000-000000000000/listing')
      await expect(page).toHaveURL(/\/forbidden$/)
    })

    test('an admin opening an unknown server sees an error state, not a crash', async ({
      page,
    }) => {
      await signInAsAdmin(page)
      await page.goto('/mcp-server/00000000-0000-0000-0000-000000000000')
      await expect(page.getByRole('alert')).toBeVisible()
      await expect(page.getByText(/Internal|Traceback|\b404\b|\b500\b/)).toHaveCount(0)
    })

    test('the long github listing keeps the page from scrolling sideways', async ({ page }) => {
      test.setTimeout(60_000)
      await signInAsAdmin(page)
      await openServer(page, 'github')
      await page.getByRole('link', { name: 'Review listing' }).click()
      await expect(page.getByRole('heading', { level: 3 }).first()).toBeVisible()
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
      expect(overflow).toBeLessThanOrEqual(0)
      if (SHOTS) {
        const height = await page.evaluate(() => document.documentElement.scrollHeight)
        for (const [i, frac] of [0.02, 0.3, 0.6].entries()) {
          await page.evaluate(
            (y) => {
              window.scrollTo(0, y)
            },
            Math.floor(height * frac),
          )
          await page.screenshot({ path: `${SHOTS}/github-slice-${String(i)}.png` })
        }
      }
    })
  })
}
