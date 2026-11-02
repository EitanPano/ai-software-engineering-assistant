import { mkdirSync } from 'node:fs'

import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { PASSWORD, registerThroughUi } from './auth-support'
import { searchBox } from './search-support'
import { expectNoSeriousViolations } from './support'

// The suite runs every limit 100 times higher (playwright.config.ts) and a Compose stack runs them
// as set, so the test does not count: it sends blank searches, which cost nothing and count, until
// the API answers 429, then opens the page as the same user. MOST is the highest limit a scale can
// make (1,000 times 5) with a margin.
const MOST = 6_000
const BATCH = 50
const WAIT = 'Too many searches'
const SCREENS = 'test-results/screens'

// One more window's worth of blank searches when the last window has ended; a no-op while it holds
// (every attempt is refused, and a refused attempt leaves the window's expiry alone).
async function reachTheLimit(request: APIRequestContext, token: string): Promise<void> {
  const headers = { Authorization: `Bearer ${token}` }
  for (let sent = 0; sent < MOST; sent += BATCH) {
    const statuses = await Promise.all(
      Array.from({ length: BATCH }, async () => {
        const res = await request.get('/api/search', { params: { q: '' }, headers })
        return res.status()
      }),
    )
    if (statuses.includes(429)) return
    expect(statuses.every((status) => status === 400)).toBe(true)
  }
  throw new Error(`no 429 after ${String(MOST)} searches`)
}

// A second session of the account just registered, in a context of its own so the page's session is
// untouched; the limit counts the user, not the session.
async function secondSession(request: APIRequestContext, email: string): Promise<string> {
  const login = await request.post('/api/auth/login', { data: { email, password: PASSWORD } })
  expect(login.ok()).toBe(true)
  const session = (await login.json()) as { tokens: { accessToken: string } }
  return session.tokens.accessToken
}

async function openLimited(page: Page, request: APIRequestContext, token: string, theme: string) {
  await reachTheLimit(request, token)
  await page.evaluate((value) => {
    localStorage.setItem('theme', value)
  }, theme)
  await page.goto('/search?q=limiter')
  await expect(page.getByText(WAIT)).toBeVisible()
}

test.describe('search limit', () => {
  test('a user over the limit is asked to wait, keeps the rest of the app, and the retry asks again', async ({
    page,
    request,
  }, info) => {
    test.setTimeout(120_000)
    const email = await registerThroughUi(page)
    const token = await secondSession(request, email)

    await openLimited(page, request, token, 'light')

    // The wait replaces the page and its form, inside the shell, in the app's own words.
    await expect(page.getByRole('alert')).toContainText('Wait about a minute, then try again.')
    await expect(searchBox(page)).toHaveCount(0)
    await expect(page.getByRole('banner')).toBeVisible()
    await expect(page.getByRole('contentinfo')).toBeVisible()
    await expect(page.getByText(/rate_limited|too many requests|429/i)).toHaveCount(0)
    await expectNoSeriousViolations(page)
    mkdirSync(SCREENS, { recursive: true })
    await page.screenshot({
      path: `${SCREENS}/search-limited-${info.project.name}-light.png`,
      fullPage: true,
    })

    // The retry asks the API once more, and the window still holds, so the wait stays.
    const asked = page.waitForRequest(
      (req) => req.method() === 'GET' && new URL(req.url()).pathname === '/api/search',
    )
    await page.getByRole('button', { name: 'Try again' }).click()
    await asked
    await expect(page.getByText(WAIT)).toBeVisible()
    await expectNoSeriousViolations(page)

    // Only search is limited: the user's other pages still open.
    await page.goto('/profile')
    await expect(page.getByRole('heading', { level: 1, name: 'Profile' })).toBeVisible()
  })

  test('the wait reads in dark and on a desktop screen', async ({ page, request }, info) => {
    test.setTimeout(120_000)
    const email = await registerThroughUi(page)
    const token = await secondSession(request, email)
    mkdirSync(SCREENS, { recursive: true })

    await openLimited(page, request, token, 'dark')
    await expect(page.locator('html')).toHaveClass(/dark/)
    await expectNoSeriousViolations(page)
    await page.screenshot({
      path: `${SCREENS}/search-limited-${info.project.name}-dark.png`,
      fullPage: true,
    })

    await page.setViewportSize({ width: 1280, height: 720 })
    await openLimited(page, request, token, 'light')
    await expectNoSeriousViolations(page)
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    )
    expect(overflow).toBe(false)
    await page.screenshot({ path: `${SCREENS}/search-limited-desktop-light.png`, fullPage: true })
  })
})
