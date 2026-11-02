import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RouteObject } from 'react-router'

import { createRoutes } from '@/app/routes'
import { NAV } from '@/app/nav'
import SiteLayout from '@/app/(site)/layout'

import { renderApp, USER, createTestClient, envelope, stubApi } from './support'
import { renderRoutes } from './render-routes'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const { toast } = await import('sonner')

const ADMIN = { ...USER, role: 'admin' as const }
const ME = { 'GET /api/user/me': Response.json(ADMIN) }
const at = '2026-10-31T10:00:00Z'
const source = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  url: `https://github.com/octocat/${id}`,
  ref: 'main',
  status: 'ready',
  errorCode: null,
  indexedCommit: 'abc1234',
  documentCount: 3,
  chunkCount: 12,
  createdAt: at,
  updatedAt: at,
  ...over,
})
const page = (items: unknown[], nextCursor: string | null = null) =>
  Response.json({ items, nextCursor })

beforeEach(() => vi.clearAllMocks())
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('access to the source routes', () => {
  it.each(['/source', '/source/connect'])('sends a visitor from %s to sign in', async (path) => {
    stubApi({ 'GET /api/user/me': envelope('unauthenticated', 401) })

    const router = renderRoutes(path)

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/sign-in')
    })
  })

  it.each(['/source', '/source/connect'])('sends a user from %s to /forbidden', async (path) => {
    stubApi({ 'GET /api/user/me': Response.json(USER) })

    const router = renderRoutes(path)

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/forbidden')
    })
  })

  it('gates the admin group itself, so a staff route added to it is guarded', () => {
    const find = (routes: RouteObject[]): RouteObject | undefined => {
      for (const route of routes) {
        if (route.children?.some((child) => child.path === 'source')) return route
        const found = find(route.children ?? [])
        if (found) return found
      }
      return undefined
    }

    const group = find(createRoutes(createTestClient()))

    expect(group).toBeDefined()
    expect(group?.path).toBeUndefined()
    expect(group?.loader).toBeTypeOf('function')
  })

  it('shows the Sources nav entry to an admin and hides it from a user', async () => {
    expect(NAV.find((entry) => entry.to === '/source')?.role).toBe('admin')

    stubApi({ 'GET /api/user/me': Response.json(USER) })
    const view = renderApp(<SiteLayout />)
    expect(await screen.findByRole('link', { name: 'Conversations' })).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByRole('link', { name: 'Sources' })).not.toBeInTheDocument()
    })
    view.unmount()

    stubApi({ 'GET /api/user/me': Response.json(ADMIN) })
    renderApp(<SiteLayout />)
    expect((await screen.findAllByRole('link', { name: 'Sources' })).length).toBeGreaterThan(0)
  })
})

describe('the source list route', () => {
  it('shows the empty state pointing at the header action', async () => {
    stubApi({ ...ME, 'GET /api/source': page([]) })

    renderRoutes('/source')

    expect(await screen.findByRole('heading', { level: 1, name: 'Sources' })).toBeVisible()
    expect(await screen.findByText('No repositories connected')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Connect repository' })).toHaveAttribute(
      'href',
      '/source/connect',
    )
  })

  it('lists each source with its name, a status in words and its counts', async () => {
    stubApi({
      ...ME,
      'GET /api/source': page([
        source('Hello-World'),
        source('building', { status: 'indexing', documentCount: 0, chunkCount: 0 }),
      ]),
    })

    renderRoutes('/source')

    const ready = (await screen.findByText('octocat/Hello-World')).closest('li')
    expect(ready).not.toBeNull()
    expect(within(ready as HTMLElement).getByText('Ready')).toBeInTheDocument()
    expect(within(ready as HTMLElement).getByText(/3 documents/)).toBeInTheDocument()
    expect(within(ready as HTMLElement).getByText(/12 chunks/)).toBeInTheDocument()
    const busy = screen.getByText('octocat/building').closest('li') as HTMLElement
    expect(within(busy).getByText('Indexing')).toBeInTheDocument()
    expect(within(busy).queryByRole('button', { name: /Retry/ })).not.toBeInTheDocument()
  })

  it('shows a failed row with its reason and retries it', async () => {
    let retried = false
    stubApi({
      ...ME,
      'GET /api/source': () =>
        page([
          retried
            ? source('broken', { status: 'queued', documentCount: 0, chunkCount: 0 })
            : source('broken', { status: 'failed', errorCode: 'embedding_unavailable' }),
        ]),
      'POST /api/source/broken/indexing': () => {
        retried = true
        return Response.json(source('broken', { status: 'queued' }), { status: 202 })
      },
    })

    renderRoutes('/source')

    const row = (await screen.findByText('octocat/broken')).closest('li') as HTMLElement
    expect(within(row).getByText('Failed')).toBeInTheDocument()
    expect(within(row).getByText(/embedding service/i)).toBeInTheDocument()
    await userEvent.click(
      within(row).getByRole('button', { name: 'Retry indexing octocat/broken' }),
    )

    expect(await screen.findByText('Queued')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Retry indexing/ })).not.toBeInTheDocument()
  })

  it('toasts in our words when the retry is refused', async () => {
    stubApi({
      ...ME,
      'GET /api/source': page([source('broken', { status: 'failed', errorCode: 'internal' })]),
      'POST /api/source/broken/indexing': envelope('conflict', 409),
    })

    renderRoutes('/source')
    await userEvent.click(
      await screen.findByRole('button', { name: 'Retry indexing octocat/broken' }),
    )

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(1)
    })
    expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/can't be retried/i))
    expect(toast.error).not.toHaveBeenCalledWith(expect.stringContaining('hunter2'))
  })

  it('shows more sources from the next cursor', async () => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: Request) => {
        const url = new URL(input.url)
        urls.push(`${url.pathname}${url.search}`)
        if (url.pathname === '/api/user/me') return Promise.resolve(Response.json(ADMIN))
        return Promise.resolve(
          url.searchParams.get('cursor') === 'abc'
            ? page([source('older')])
            : page([source('newest')], 'abc'),
        )
      }),
    )

    renderRoutes('/source')
    expect(await screen.findByText('octocat/newest')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show more' }))

    expect(await screen.findByText('octocat/older')).toBeInTheDocument()
    expect(urls.some((url) => url.includes('cursor=abc'))).toBe(true)
  })

  it('reaches the group error state when the API is down', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    stubApi({ ...ME, 'GET /api/source': envelope('internal', 500) })

    renderRoutes('/source')

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText(/hunter2/)).not.toBeInTheDocument()
  })
})

describe('the connect route', () => {
  async function fill(url: string, ref = '') {
    await userEvent.type(await screen.findByLabelText('Repository URL'), url)
    if (ref) await userEvent.type(screen.getByLabelText(/Branch, tag or commit/), ref)
    await userEvent.click(screen.getByRole('button', { name: 'Connect repository' }))
  }

  it('connects, sending no ref when the field is empty, and returns to the list', async () => {
    let body: unknown
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: Request) => {
        const url = new URL(input.url)
        if (url.pathname === '/api/user/me') return Response.json(ADMIN)
        if (input.method === 'POST') {
          body = await input.json()
          return Response.json(source('Hello-World', { status: 'queued' }), { status: 201 })
        }
        return page([source('Hello-World', { status: 'queued' })])
      }),
    )

    const router = renderRoutes('/source/connect')
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Connect repository' }),
    ).toBeVisible()
    await fill('https://github.com/octocat/Hello-World')

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/source')
    })
    expect(body).toEqual({ url: 'https://github.com/octocat/Hello-World' })
    expect(await screen.findByText('Queued')).toBeInTheDocument()
  })

  it('sends the ref when one is typed', async () => {
    let body: unknown
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: Request) => {
        const url = new URL(input.url)
        if (url.pathname === '/api/user/me') return Response.json(ADMIN)
        if (input.method === 'POST') {
          body = await input.json()
          return Response.json(source('x'), { status: 201 })
        }
        return page([])
      }),
    )

    renderRoutes('/source/connect')
    await fill('https://github.com/octocat/Hello-World', 'v1.0')

    await waitFor(() => {
      expect(body).toEqual({ url: 'https://github.com/octocat/Hello-World', ref: 'v1.0' })
    })
  })

  it('refuses a malformed url before calling the API', async () => {
    const fetchMock = stubApi({ ...ME })

    renderRoutes('/source/connect')
    await fill('http://github.com/octocat/Hello-World')

    expect(await screen.findByText(/Enter the repository as/)).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([request]) => request.method === 'POST')).toBe(false)
  })

  it.each([
    ['not_found', 404, /couldn't find a public repository/i],
    ['conflict', 409, /already connected/i],
  ])('puts a %s on the url field', async (code, status, text) => {
    stubApi({ ...ME, 'POST /api/source': envelope(code, status) })

    renderRoutes('/source/connect')
    await fill('https://github.com/octocat/missing')

    const input = await screen.findByLabelText('Repository URL')
    await waitFor(() => {
      expect(input).toHaveAttribute('aria-invalid', 'true')
    })
    expect(screen.getByText(text)).toBeInTheDocument()
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('shows the server-side url rule as a field error, not its text', async () => {
    stubApi({
      ...ME,
      'POST /api/source': Response.json(
        {
          error: {
            code: 'validation_failed',
            message: 'server text: hunter2',
            details: [{ path: 'url', message: 'repository ends in .git' }],
          },
          requestId: 'r1',
        },
        { status: 400 },
      ),
    })

    renderRoutes('/source/connect')
    await fill('https://github.com/octocat/repo.git')

    expect(await screen.findByText(/Enter the repository as/)).toBeInTheDocument()
    expect(screen.queryByText(/hunter2/)).not.toBeInTheDocument()
  })

  it('toasts when GitHub is unreachable and keeps the form', async () => {
    stubApi({ ...ME, 'POST /api/source': envelope('upstream_unavailable', 503) })

    const router = renderRoutes('/source/connect')
    await fill('https://github.com/octocat/Hello-World')

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(1)
    })
    expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/GitHub/))
    expect(router.state.location.pathname).toBe('/source/connect')
    expect(screen.getByRole('button', { name: 'Connect repository' })).toBeEnabled()
  })

  it('cancels back to the list', async () => {
    stubApi({ ...ME, 'GET /api/source': page([]) })

    renderRoutes('/source/connect')
    await screen.findByLabelText('Repository URL')

    expect(screen.getByRole('link', { name: 'Cancel' })).toHaveAttribute('href', '/source')
  })
})
