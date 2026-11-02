import { expect, test } from '@playwright/test'

import { registerThroughUi, signOutThroughUi } from './auth-support'
import {
  DOTTED_QUERY,
  KEYWORD_QUERY,
  LONG_LINE_QUERY,
  SEMANTIC_QUERY,
  SYMBOL,
  expectHit,
  searchBox,
  searchFor,
} from './search-support'
import {
  REPOSITORY,
  connectRepository,
  signInAsAdmin,
  sourceRow,
  uniqueToken,
} from './source-support'
import { expectNoSeriousViolations } from './support'

// The journey needs the GitHub and Voyage fakes and a database to promote an admin in, which only
// the suite's own servers provide (playwright.config.ts), so a run against a Compose stack
// (E2E_BASE_URL) leaves it out when the tests are collected.
const EXTERNAL = Boolean(process.env.E2E_BASE_URL?.trim())
const INDEXED = { timeout: 30_000 } // the list refreshes every 3 s until a row settles

test.describe('search', () => {
  test('a visitor is sent to sign in', async ({ page }) => {
    await page.goto('/search?q=limiter')
    await expect(page).toHaveURL(/\/sign-in/)
  })

  test('a signed-in user sees the empty state first and a blank search is refused', async ({
    page,
  }) => {
    await registerThroughUi(page)

    await page.goto('/search')
    await expect(page.getByRole('heading', { level: 1, name: 'Search' })).toBeVisible()
    await expect(
      page.getByRole('heading', { level: 2, name: 'Search the knowledge base' }),
    ).toBeVisible()
    await expectNoSeriousViolations(page)

    await page.getByRole('button', { name: 'Search' }).click()
    await expect(searchBox(page)).toHaveAttribute('aria-invalid', 'true')
    await expect(page).toHaveURL(/\/search$/)
    await expectNoSeriousViolations(page)
  })

  if (!EXTERNAL) {
    test('a user finds an identifier, a dotted call and a paraphrase, and keeps them on reload', async ({
      page,
    }) => {
      test.setTimeout(120_000)
      const repository = REPOSITORY.fixture(uniqueToken())
      const admin = await signInAsAdmin(page)
      await connectRepository(page, repository)
      await expect(sourceRow(page, repository).getByText('Ready')).toBeVisible(INDEXED)

      // A plain user, not the admin, searches.
      await signOutThroughUi(page, admin)
      await registerThroughUi(page)
      await page.goto('/search')

      await searchFor(page, KEYWORD_QUERY)
      const keywordLabel = await expectHit(page, `· ${SYMBOL.keyword}`)
      await expect(page.getByText('Keyword match').first()).toBeVisible()
      await expectNoSeriousViolations(page)

      await page.reload()
      expect(await expectHit(page, `· ${SYMBOL.keyword}`)).toBe(keywordLabel)
      await expect(searchBox(page)).toHaveValue(KEYWORD_QUERY)

      await searchFor(page, DOTTED_QUERY)
      await expectHit(page, `· ${SYMBOL.dotted}`)

      await searchFor(page, SEMANTIC_QUERY)
      await expectHit(page, `· ${SYMBOL.semantic}`)
      await expectNoSeriousViolations(page)

      await page.goBack()
      await expectHit(page, `· ${SYMBOL.dotted}`)
      await expect(searchBox(page)).toHaveValue(DOTTED_QUERY)

      // One line over the bound: a piece with no symbol that wraps instead of scrolling sideways.
      await searchFor(page, LONG_LINE_QUERY)
      await expectHit(page, LONG_LINE_QUERY)
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      )
      expect(overflow).toBe(false)
    })
  }
})
