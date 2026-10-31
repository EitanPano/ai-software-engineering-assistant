import { expect, type Locator, type Page } from '@playwright/test'

// The search queries of the acceptance criterion, repeated from backend/tests/fixture_repository.py
// (the fixture repository is served by the fake GitHub for any `<owner>/<repo>`, embedded by the
// scripted fake Voyage). Each expects a chunk of `src/limiter.py`; the exact lines are the
// backend's test, here a hit is told by its path, its symbol and a `start-end` range.
export const LIMITER_PATH = 'src/limiter.py'
export const KEYWORD_QUERY = 'sliding_window_remaining'
export const DOTTED_QUERY = 'defer_penalty'
export const LONG_LINE_QUERY = 'QUOKKA_SNAPSHOT'
// Shares no word with the chunk it expects.
export const SEMANTIC_QUERY = 'throttle abusive clients exceeding quotas'

// The symbol each query's chunk carries.
export const SYMBOL = {
  keyword: 'sliding_window_remaining',
  dotted: 'admit_batch',
  semantic: 'WindowCounter',
}

export const searchBox = (page: Page) => page.getByLabel('Search the knowledge base')

// Searches through the form, as a person does, and waits until the text is in the URL.
export async function searchFor(page: Page, text: string) {
  await searchBox(page).fill(text)
  await page.getByRole('button', { name: 'Search' }).click()
  await page.waitForURL((url) => url.searchParams.get('q') === text)
}

// A hit of the limiter file holding `text` (a symbol is shown as `· name`, a piece of the long
// line by its content). Several repositories can hold the same fixture, so a hit is told by path
// and content, not by owner.
export function limiterHit(page: Page, text: string): Locator {
  return page
    .getByRole('main')
    .getByRole('listitem')
    .filter({ hasText: new RegExp(`${LIMITER_PATH}:\\d+(-\\d+)?`) })
    .filter({ hasText: text })
    .first()
}

// Asserts the hit is on screen with its `start-end` label, and returns the label's text.
export async function expectHit(page: Page, text: string): Promise<string> {
  const hit = limiterHit(page, text)
  await expect(hit).toBeVisible({ timeout: 15_000 })
  const label = hit.getByText(new RegExp(`^${LIMITER_PATH}:\\d+(-\\d+)?$`)).first()
  await expect(label).toBeVisible()
  return (await label.textContent()) ?? ''
}
