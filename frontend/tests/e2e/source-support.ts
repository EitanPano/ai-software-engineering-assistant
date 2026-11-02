import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { expect, type APIRequestContext, type Page } from '@playwright/test'

import { PASSWORD, fillSignIn, registerThroughUi, signOutThroughUi } from './auth-support'

// The scripted GitHub and Voyage fakes (backend/tests/fake_github.py, fake_voyage.py). The fake
// GitHub serves the fixture repository for any `<owner>/<repo>` and picks a script by the
// repository name, so parallel journeys stay apart:
//   - `missing-<token>`: no such repository (404).
//   - `embedfail-<key>`: the fixture, whose indexing fails at Voyage until KEY is released.
export const GITHUB_URL = 'https://github.com'
export const VOYAGE_FAKE_URL = 'http://127.0.0.1:8103'
export const OWNER = 'e2e'

export function uniqueToken(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

export const REPOSITORY = {
  fixture: (token: string) => `fixture-${token}`,
  missing: (token: string) => `missing-${token}`,
  embedFail: (key: string) => `embedfail-${key}`,
}

export const repositoryUrl = (repository: string) => `${GITHUB_URL}/${OWNER}/${repository}`

// What the screens spec's `setup` receives: the account just registered and the browser-test
// database. Promotes the account with the system operation (no endpoint does it), exactly as an
// operator would: the password goes in on stdin, never in the arguments. A non-zero exit throws,
// so the test fails. Only `databaseUrl`, which the callers check ends in `_e2e`, is written to.
export function grantAdmin(account: { email: string; databaseUrl: string }): Promise<void> {
  execFileSync('uv', ['run', 'python', '-m', 'app.infra.scripts.grant_admin', account.email], {
    cwd: fileURLToPath(new URL('../../../backend', import.meta.url)),
    input: `${PASSWORD}\n`,
    env: { ...process.env, DATABASE_URL: account.databaseUrl },
    stdio: ['pipe', 'pipe', 'pipe'],
  })
  return Promise.resolve()
}

// Signs up, promotes the account and signs in again through the UI: the promotion ends the
// account's sessions, and a token keeps the role it was issued with.
export async function signInAsAdmin(page: Page): Promise<string> {
  const email = await registerThroughUi(page)
  const { e2eDatabaseUrl } = await import('../../scripts/e2e-database-url')
  const databaseUrl = e2eDatabaseUrl(
    process.env.E2E_DATABASE_URL,
    'postgres://app:app@127.0.0.1:5432/app_e2e',
  )
  await grantAdmin({ email, databaseUrl })
  await signOutThroughUi(page, email)
  await fillSignIn(page, email)
  await expect(page).toHaveURL(/\/$/, { timeout: 15_000 })
  return email
}

// Lets a held `embedfail` repository's embeddings go through.
export async function releaseEmbedding(request: APIRequestContext, key: string) {
  const response = await request.post(`${VOYAGE_FAKE_URL}/release/${key}`)
  expect(response.ok()).toBe(true)
}

// The row of a repository on the source list.
export const sourceRow = (page: Page, repository: string) =>
  page.getByRole('listitem').filter({ hasText: `${OWNER}/${repository}` })

// Opens the connect form from the list and submits a repository.
export async function connectRepository(page: Page, repository: string) {
  await page.goto('/source')
  await page.getByRole('link', { name: 'Connect repository' }).click()
  await expect(page).toHaveURL(/\/source\/connect$/)
  await page.getByLabel('Repository URL').fill(repositoryUrl(repository))
  await page.getByRole('button', { name: 'Connect repository' }).click()
}
