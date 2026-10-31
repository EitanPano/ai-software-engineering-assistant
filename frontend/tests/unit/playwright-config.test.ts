import { readFileSync } from 'node:fs'

import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

async function load(env: Record<string, string>) {
  vi.resetModules()
  for (const [name, value] of Object.entries(env)) vi.stubEnv(name, value)
  return (await import('../../playwright.config')).default
}

describe('playwright.config.ts', () => {
  it('takes a blank E2E_BASE_URL as unset and starts its own servers', async () => {
    // A CI variable exported empty must not become the origin ('' would start servers on no URL).
    const config = await load({ E2E_BASE_URL: '   ', E2E_DATABASE_URL: 'postgres://u:p@h/app_e2e' })

    expect(config.use?.baseURL).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/)
    expect(config.webServer).toBeDefined()
  })

  it('starts the scripted Anthropic fake and points the API at it', async () => {
    const config = await load({ E2E_BASE_URL: '', E2E_DATABASE_URL: 'postgres://u:p@h/app_e2e' })
    const servers = [config.webServer ?? []].flat()
    const fake = servers.find((server) => server.command.includes('tests.fake_anthropic'))
    const api = servers.find((server) => server.command.includes('app.main'))

    expect(fake?.url).toBe('http://127.0.0.1:8101/health')
    expect(fake?.reuseExistingServer).toBe(false)
    expect(api?.env?.ANTHROPIC_BASE_URL).toBe('http://127.0.0.1:8101')
    // No real key: the fake needs none, and a placeholder is not shaped like one.
    expect(api?.env?.ANTHROPIC_API_KEY).not.toMatch(/^sk-ant-/)
  })

  it('starts the GitHub and Voyage fakes before the API and points the API at them', async () => {
    const config = await load({ E2E_BASE_URL: '', E2E_DATABASE_URL: 'postgres://u:p@h/app_e2e' })
    const servers = [config.webServer ?? []].flat()
    const github = servers.find((server) => server.command.includes('tests.fake_github'))
    const voyage = servers.find((server) => server.command.includes('tests.fake_voyage'))
    const api = servers.find((server) => server.command.includes('app.main'))

    expect(github?.url).toBe('http://127.0.0.1:8102/health')
    expect(voyage?.url).toBe('http://127.0.0.1:8103/health')
    expect(github?.reuseExistingServer).toBe(false)
    expect(voyage?.reuseExistingServer).toBe(false)
    expect(servers.indexOf(github as (typeof servers)[number])).toBeLessThan(
      servers.indexOf(api as (typeof servers)[number]),
    )
    expect(servers.indexOf(voyage as (typeof servers)[number])).toBeLessThan(
      servers.indexOf(api as (typeof servers)[number]),
    )
    expect(api?.env?.GITHUB_BASE_URL).toBe('http://127.0.0.1:8102')
    expect(api?.env?.VOYAGE_BASE_URL).toBe('http://127.0.0.1:8103')
    // A placeholder the fake never checks, not shaped like a real key.
    expect(api?.env?.VOYAGE_API_KEY).toBeTruthy()
    expect(api?.env?.VOYAGE_API_KEY).not.toMatch(/^pa-/)
  })

  it('keeps an explicit E2E_BASE_URL and starts nothing', async () => {
    const config = await load({ E2E_BASE_URL: 'http://127.0.0.1:3000' })

    expect(config.use?.baseURL).toBe('http://127.0.0.1:3000')
    expect(config.webServer).toBeUndefined()
  })

  it('routes the touch and desktop checks by tag, so no spec skips at run time', async () => {
    const config = await load({ E2E_BASE_URL: 'http://127.0.0.1:3000' })
    const project = (name: string) => config.projects?.find((p) => p.name === name)

    expect(project('phone')?.grepInvert).toEqual(/@desktop/)
    expect(project('desktop')?.grepInvert).toEqual(/@phone/)
    const specs = readFileSync('tests/e2e/shell.spec.ts', 'utf8')
    expect(specs).not.toMatch(/\.skip\(/)
  })
})
