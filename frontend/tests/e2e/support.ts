import AxeBuilder from '@axe-core/playwright'
import { expect, type Locator, type Page } from '@playwright/test'

export async function expectNoSeriousViolations(page: Page) {
  await settled(page.locator('html'))
  const results = await new AxeBuilder({ page }).analyze()
  const serious = results.violations.filter(
    (violation) => violation.impact === 'serious' || violation.impact === 'critical',
  )
  expect(serious).toEqual([])
}

// A sheet slides in over 500 ms and a box read mid-slide is fractional (43.99998 px for a 44 px
// button); a button re-enabled after a run fades from 50% opacity, and axe reads a blended colour
// mid-fade. Wait for the finite animations, then measure or scan; the thresholds stay exact. It
// cannot wait for a transition that has not started: assert the end state (an enabled button)
// before it. A transition that is retargeted or whose element is removed is cancelled, and a
// cancelled animation's `finished` rejects, so each batch is awaited with `allSettled`; the
// replacement transition is a new animation, so it loops until none is left. Playwright's test
// timeout bounds it. Only a running animation is awaited: one that finished with `fill: forwards`
// or `both` stays in `getAnimations()` for good, so waiting on "any finite animation" never ends.
export async function settled(locator: Locator) {
  await locator.evaluate(async (element) => {
    const pending = () =>
      element
        .getAnimations({ subtree: true })
        .filter(
          (animation) =>
            animation.effect?.getTiming().iterations !== Infinity &&
            animation.playState === 'running',
        )
    for (let batch = pending(); batch.length > 0; batch = pending()) {
      await Promise.allSettled(batch.map((animation) => animation.finished))
    }
  })
}

// What a screen must satisfy whatever its content: no WCAG A/AA axe violation, no sideways scroll
// and exactly one visible h1. Returns one line per failure, naming the rule or the numbers, so a
// failing screen tells the agent what to fix; an empty list is a pass.
const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

// The checks are the same as Next's `screenProblems`; this one waits for networkidle where Next
// waits for its streamed meta refresh and title to settle.
export async function screenProblems(page: Page): Promise<string[]> {
  await page.waitForLoadState('networkidle')
  await settled(page.locator('html'))
  const problems: string[] = []

  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()
  for (const violation of results.violations) {
    const targets = violation.nodes.map((node) => node.target.join(' ')).join(' | ')
    problems.push(`axe ${violation.id} (${String(violation.impact)}): ${targets}`)
  }

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  if (scrollWidth > clientWidth) {
    problems.push(
      `horizontal overflow: scrollWidth ${String(scrollWidth)} > clientWidth ${String(clientWidth)}`,
    )
  }

  const headings = await page.getByRole('heading', { level: 1 }).count()
  if (headings !== 1) problems.push(`expected exactly one h1, found ${String(headings)}`)

  return problems
}

export const isPhone = (project: string) => project === 'phone'
