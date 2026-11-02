import { expect, test, type Locator } from '@playwright/test'

import { MARKER, startAndSend } from './conversation-support'
import { expectNoSeriousViolations } from './support'

// The journeys need the scripted Anthropic fake, which only the suite's own servers start
// (playwright.config.ts), so a run against a Compose stack (E2E_BASE_URL) leaves them out when the
// tests are collected.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())

// Registered only when the suite starts its own servers; nothing skips at run time.
if (!EXTERNAL) {
  defineJourneys()
}

// The characters of a text in the order they stand on screen, which is what a person reads. The
// DOM keeps its own order whatever the direction does, so only a browser can answer this.
function onScreen(host: Locator) {
  return host.evaluate((element) => {
    const text = element.firstChild
    if (text === null) return ''
    return Array.from(text.textContent ?? '', (character, index) => {
      const range = document.createRange()
      range.setStart(text, index)
      range.setEnd(text, index + 1)
      return { character, left: range.getBoundingClientRect().left }
    })
      .sort((a, b) => a.left - b.left)
      .map(({ character }) => character)
      .join('')
  })
}

const hostBeside = (link: Locator) => link.locator('xpath=preceding-sibling::span')

async function box(locator: Locator) {
  const found = await locator.boundingBox()
  if (found === null) throw new Error('the element has no box')
  return found
}

function defineJourneys() {
  test.describe('a link in an answer', () => {
    test('shows its real host before its words, whatever the answer does', async ({ page }) => {
      await startAndSend(page, `Explain ${MARKER.links}`)
      const log = page.getByRole('log')

      // A direction override in the words reverses them, and leaves the host as it is.
      const overridden = log.getByRole('link', { name: /the docs/ })
      await expect(overridden).toBeVisible()
      await expect(overridden).toHaveAttribute('href', 'https://moc.buhtig.se/?d=secret')
      expect(await onScreen(hostBeside(overridden))).toBe('(moc.buhtig.se)')
      const overriddenHost = await box(hostBeside(overridden))
      expect(overriddenHost.x + overriddenHost.width).toBeLessThanOrEqual((await box(overridden)).x)

      // A bare URL whose reversed words read as GitHub's still names where it goes.
      const reversed = log.getByRole('link', { name: /moc\.buhtig/ })
      expect(await onScreen(hostBeside(reversed))).toBe('(evil.example)')

      // A label that fills the screen cannot push the host away from its first line.
      const long = log.getByRole('link', { name: /^a long label/ })
      const longHost = await box(hostBeside(long))
      expect(longHost.y).toBeLessThanOrEqual((await box(long)).y + 1)
      expect(await onScreen(hostBeside(long))).toBe('(far.example)')

      // A wide first column cannot cut the host at the table's scrolling edge.
      const inTable = log.getByRole('link', { name: 'in a table' })
      const wrapper = await box(log.locator('table').locator('xpath=..'))
      const tableHost = await box(hostBeside(inTable))
      expect(tableHost.x + tableHost.width).toBeLessThanOrEqual(wrapper.x + wrapper.width)
      await expect(hostBeside(inTable)).toHaveText('(github.com.evil.example)')

      await expectNoSeriousViolations(page)
    })
  })
}
