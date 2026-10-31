import { onlineManager } from '@tanstack/react-query'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RouteObject } from 'react-router'

import SiteLayout from '@/app/(site)/layout'
import { NAV } from '@/app/nav'
import { createRoutes } from '@/app/routes'

import { renderRoutes } from './render-routes'
import { USER, createAppClient, createTestClient, envelope, renderApp, stubApi } from './support'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const { toast } = await import('sonner')

const ADMIN = { ...USER, role: 'admin' as const }
const ME = { 'GET /api/user/me': Response.json(ADMIN) }
const at = '2026-10-31T10:00:00Z'

const score = (over: Record<string, unknown> = {}) => ({
  search: 'hybrid',
  kind: 'all',
  caseCount: 30,
  recallAt5: 0.8,
  recallAt10: 0.9,
  recallAt20: 0.95,
  mrr: 0.71,
  ndcgAt10: 0.74,
  ...over,
})
const run = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  status: 'completed',
  errorCode: null,
  caseCount: 30,
  skippedCaseCount: 0,
  incompleteCaseCount: 0,
  headline: score(),
  createdAt: at,
  updatedAt: at,
  ...over,
})
const detail = (id: string, over: Record<string, unknown> = {}) => ({
  ...run(id),
  scores: [
    score(),
    score({ search: 'semantic', recallAt5: 0.6 }),
    score({ search: 'keyword', recallAt5: 0.5 }),
    score({ kind: 'identifier', caseCount: 15, recallAt5: 0.93 }),
    score({ kind: 'paraphrase', caseCount: 15, recallAt5: 0.67 }),
  ],
  cases: [
    {
      question: 'where is the <img src=x onerror=alert(1)> parsed?',
      kind: 'identifier',
      skipReason: null,
      incomplete: false,
      rank: 2,
      recallAt5: 1,
      recallAt10: 1,
      recallAt20: 1,
      reciprocalRank: 0.5,
      ndcgAt10: 0.63,
      topCosine: 0.51,
      relevantCosine: 0.47,
    },
    {
      question: 'how do I bake bread',
      kind: 'no_answer',
      skipReason: null,
      incomplete: false,
      rank: null,
      recallAt5: null,
      recallAt10: null,
      recallAt20: null,
      reciprocalRank: null,
      ndcgAt10: null,
      topCosine: 0.31,
      relevantCosine: null,
    },
  ],
  corpus: [
    {
      url: 'https://github.com/pallets/click',
      ref: '8.5.0',
      indexedCommit: '8b19813f2bfca99f1018a587a8cf54fc959f2e5d',
      chunkCount: 1366,
    },
  ],
  settings: {
    embeddingModel: 'voyage-code-4',
    rrfK: 60,
    candidates: 50,
    keywordCandidates: 50,
    trigramThreshold: 0.3,
  },
  cosine: { relevantMin: 0.2436, relevantMedian: 0.47, noAnswerMedian: 0.3, noAnswerMax: 0.31 },
  ...over,
})
const page = (items: unknown[], nextCursor: string | null = null) =>
  Response.json({ items, nextCursor })

const posts = (fetchMock: ReturnType<typeof stubApi>) =>
  fetchMock.mock.calls.filter(([request]) => request.method === 'POST')

beforeEach(() => vi.clearAllMocks())
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  onlineManager.setOnline(true)
})

describe('access to the eval-run routes', () => {
  it.each(['/eval-run', '/eval-run/r1'])('sends a visitor from %s to sign in', async (path) => {
    stubApi({ 'GET /api/user/me': envelope('unauthenticated', 401) })

    const router = renderRoutes(path)

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/sign-in')
    })
  })

  it.each(['/eval-run', '/eval-run/r1'])('sends a user from %s to /forbidden', async (path) => {
    const fetchMock = stubApi({ 'GET /api/user/me': Response.json(USER) })

    const router = renderRoutes(path)

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/forbidden')
    })
    expect(
      fetchMock.mock.calls.some(([request]) =>
        new URL(request.url).pathname.startsWith('/api/eval-run'),
      ),
    ).toBe(false)
  })

  it('sits in the gated admin group', () => {
    const find = (routes: RouteObject[]): RouteObject | undefined => {
      for (const route of routes) {
        if (route.children?.some((child) => child.path === 'eval-run')) return route
        const found = find(route.children ?? [])
        if (found) return found
      }
      return undefined
    }

    const group = find(createRoutes(createTestClient()))

    expect(group?.path).toBeUndefined()
    expect(group?.loader).toBeTypeOf('function')
    expect(group?.children?.some((child) => child.path === 'eval-run/:id')).toBe(true)
  })

  it('shows the Eval runs nav entry to an admin and hides it from a user', async () => {
    expect(NAV.find((entry) => entry.to === '/eval-run')?.role).toBe('admin')

    stubApi({ 'GET /api/user/me': Response.json(USER) })
    const view = renderApp(<SiteLayout />)
    expect(await screen.findByRole('link', { name: 'Conversations' })).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByRole('link', { name: 'Eval runs' })).not.toBeInTheDocument()
    })
    view.unmount()

    stubApi({ 'GET /api/user/me': Response.json(ADMIN) })
    renderApp(<SiteLayout />)
    expect((await screen.findAllByRole('link', { name: 'Eval runs' })).length).toBeGreaterThan(0)
  })
})

describe('the eval-run list route', () => {
  it('shows the empty state pointing at the header action', async () => {
    stubApi({ ...ME, 'GET /api/eval-run': page([]) })

    renderRoutes('/eval-run')

    expect(await screen.findByRole('heading', { level: 1, name: 'Eval runs' })).toBeVisible()
    expect(await screen.findByText('No eval runs yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start eval run' })).toBeEnabled()
  })

  it('lists each run with its status in words, its counts and headline scores', async () => {
    stubApi({
      ...ME,
      'GET /api/eval-run': page([
        run('r1', { skippedCaseCount: 2 }),
        run('r2', { status: 'running', headline: null, caseCount: 0 }),
      ]),
    })

    renderRoutes('/eval-run')

    const done = (await screen.findByRole('link', { name: /Completed/ })).closest('li')
    expect(done).not.toBeNull()
    expect(within(done as HTMLElement).getByText(/30 cases/)).toBeInTheDocument()
    expect(within(done as HTMLElement).getByText(/2 skipped/)).toBeInTheDocument()
    expect(within(done as HTMLElement).getByText(/Recall@5 0\.80/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Completed/ })).toHaveAttribute('href', '/eval-run/r1')
    const busy = screen.getByRole('link', { name: /Running/ }).closest('li') as HTMLElement
    expect(within(busy).queryByText(/Recall@5/)).not.toBeInTheDocument()
  })

  it('gives a failed run its reason in words and offers no re-run', async () => {
    stubApi({
      ...ME,
      'GET /api/eval-run': page([
        run('r1', { status: 'failed', errorCode: 'search_unavailable', headline: null }),
      ]),
    })

    renderRoutes('/eval-run')

    const row = (await screen.findByRole('link', { name: /Failed/ })).closest('li') as HTMLElement
    expect(within(row).getByText(/search was unavailable/i)).toBeInTheDocument()
    expect(within(row).queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByText(/hunter2/)).not.toBeInTheDocument()
  })

  it('shows the group error state when the list cannot be read', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    stubApi({ ...ME, 'GET /api/eval-run': envelope('internal', 500) })

    renderRoutes('/eval-run')

    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
    expect(screen.queryByText(/hunter2/)).not.toBeInTheDocument()
  })
})

describe('starting an eval run', () => {
  it('sends one start per click, confirms in a toast and refreshes the list', async () => {
    let started = false
    const fetchMock = stubApi({
      ...ME,
      'GET /api/eval-run': () =>
        page(started ? [run('r1', { status: 'queued', headline: null, caseCount: 0 })] : []),
      'POST /api/eval-run': () => {
        started = true
        return Response.json(run('r1', { status: 'queued', headline: null }), { status: 201 })
      },
    })
    renderRoutes('/eval-run')

    await userEvent.click(await screen.findByRole('button', { name: 'Start eval run' }))

    expect(await screen.findByRole('link', { name: /Queued/ })).toBeInTheDocument()
    expect(posts(fetchMock)).toHaveLength(1)
    expect(toast.success).toHaveBeenCalledTimes(1)
  })

  it('words a start refused because a run is active, as a toast', async () => {
    const fetchMock = stubApi({
      ...ME,
      'GET /api/eval-run': page([]),
      'POST /api/eval-run': envelope('conflict', 409),
    })
    renderRoutes('/eval-run')

    await userEvent.click(await screen.findByRole('button', { name: 'Start eval run' }))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/already/i))
    })
    expect(vi.mocked(toast.error).mock.calls[0]?.[0]).not.toMatch(/hunter2/)
    expect(posts(fetchMock)).toHaveLength(1)
  })

  it('refreshes the list after a refused start, so the run that holds the slot shows', async () => {
    let active = false
    stubApi({
      ...ME,
      'GET /api/eval-run': () =>
        page(active ? [run('r9', { status: 'running', headline: null, caseCount: 0 })] : []),
      'POST /api/eval-run': () => {
        active = true
        return envelope('conflict', 409)
      },
    })
    renderRoutes('/eval-run')

    await userEvent.click(await screen.findByRole('button', { name: 'Start eval run' }))

    expect(await screen.findByRole('link', { name: /Running/ })).toBeInTheDocument()
  })

  it('does not send a second start from a second click while the first is pending', async () => {
    let release: (value: Response) => void = () => undefined
    const fetchMock = stubApi({
      ...ME,
      'GET /api/eval-run': page([]),
      'POST /api/eval-run': () =>
        new Promise<Response>((resolve) => {
          release = resolve
        }),
    })
    renderRoutes('/eval-run')
    const button = await screen.findByRole('button', { name: 'Start eval run' })

    await userEvent.click(button)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Starting…' })).toBeDisabled()
    })
    await userEvent.click(screen.getByRole('button', { name: 'Starting…' }))

    expect(posts(fetchMock)).toHaveLength(1)
    release(Response.json(run('r1', { status: 'queued' }), { status: 201 }))
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalled()
    })
  })

  describe('starts no run the user did not ask for', () => {
    it('sends nothing but reads on load, Try again, focus and reconnect', async () => {
      vi.spyOn(console, 'error').mockImplementation(() => undefined)
      let failing = true
      const fetchMock = stubApi({
        ...ME,
        'GET /api/eval-run': () => (failing ? envelope('internal', 500) : page([run('r1')])),
        'POST /api/eval-run': Response.json(run('x'), { status: 201 }),
      })
      renderRoutes('/eval-run', createAppClient())

      const retry = await screen.findByRole('button', { name: 'Try again' })
      failing = false
      await userEvent.click(retry)
      await screen.findByRole('link', { name: /Completed/ })
      act(() => {
        window.dispatchEvent(new Event('focus'))
        document.dispatchEvent(new Event('visibilitychange'))
        onlineManager.setOnline(false)
        onlineManager.setOnline(true)
        window.dispatchEvent(new Event('online'))
      })
      await screen.findByRole('link', { name: /Completed/ })

      expect(posts(fetchMock)).toHaveLength(0)
    })

    it('sends a start made offline at once, once, and nothing more on reconnect', async () => {
      const fetchMock = vi.fn((input: Request) => {
        const { method } = input
        const path = new URL(input.url).pathname
        if (method === 'POST') return Promise.reject(new TypeError('Failed to fetch'))
        if (path === '/api/user/me') return Promise.resolve(Response.json(ADMIN))
        return Promise.resolve(page([]))
      })
      vi.stubGlobal('fetch', fetchMock)
      vi.spyOn(console, 'error').mockImplementation(() => undefined)
      renderRoutes('/eval-run')
      const button = await screen.findByRole('button', { name: 'Start eval run' })

      act(() => {
        onlineManager.setOnline(false)
      })
      await userEvent.click(button)
      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/reach the server/i))
      })
      expect(posts(fetchMock as ReturnType<typeof stubApi>)).toHaveLength(1)
      act(() => {
        onlineManager.setOnline(true)
        window.dispatchEvent(new Event('online'))
      })
      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Start eval run' })).toBeEnabled()
      })

      expect(posts(fetchMock as ReturnType<typeof stubApi>)).toHaveLength(1)
    })
  })
})

describe('the eval-run detail route', () => {
  it('reads the headline, the scores by search and kind, the cosine, the corpus and the cases', async () => {
    stubApi({ ...ME, 'GET /api/eval-run/r1': Response.json(detail('r1')) })

    renderRoutes('/eval-run/r1')

    expect(await screen.findByRole('heading', { level: 1, name: 'Eval run' })).toBeVisible()
    expect(await screen.findByText('Completed')).toBeInTheDocument()
    const hybrid = screen.getByRole('table', { name: 'Scores by search and kind' })
    const rows = within(hybrid).getAllByRole('row')
    expect(rows.length).toBe(1 + 5)
    expect(within(hybrid).getByText('0.93')).toBeInTheDocument()
    expect(screen.getByText('0.244')).toBeInTheDocument()
    expect(screen.getByText(/pallets\/click/)).toBeInTheDocument()
    expect(screen.getByText(/voyage-code-4/)).toBeInTheDocument()
    const cases = screen.getByRole('table', { name: 'Cases' })
    expect(within(cases).getByText('No answer')).toBeInTheDocument()
    expect(within(cases).getByText('how do I bake bread')).toBeInTheDocument()
  })

  it('renders a question holding HTML as text', async () => {
    stubApi({ ...ME, 'GET /api/eval-run/r1': Response.json(detail('r1')) })

    renderRoutes('/eval-run/r1')

    expect(
      await screen.findByText('where is the <img src=x onerror=alert(1)> parsed?'),
    ).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
  })

  it('warns above the scores when cases were skipped or incomplete', async () => {
    stubApi({
      ...ME,
      'GET /api/eval-run/r1': Response.json(
        detail('r1', {
          skippedCaseCount: 3,
          incompleteCaseCount: 1,
          cases: [
            {
              ...detail('r1').cases[0],
              question: 'skipped question',
              skipReason: 'source_missing',
              rank: null,
              recallAt5: null,
              reciprocalRank: null,
              ndcgAt10: null,
              topCosine: null,
              relevantCosine: null,
            },
          ],
        }),
      ),
    })

    renderRoutes('/eval-run/r1')

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(/3 cases were skipped/)).toBeInTheDocument()
    expect(within(alert).getByText(/1 case was incomplete/)).toBeInTheDocument()
    expect(screen.getByText(/source is not connected/i)).toBeInTheDocument()
  })

  it('shows an active run as a status badge over skeleton cards, with no scores', async () => {
    stubApi({
      ...ME,
      'GET /api/eval-run/r1': Response.json(
        detail('r1', {
          status: 'running',
          headline: null,
          scores: [],
          cases: [],
          cosine: null,
          settings: null,
          corpus: [],
        }),
      ),
    })

    renderRoutes('/eval-run/r1')

    expect(await screen.findByText('Running')).toBeInTheDocument()
    expect(screen.getByRole('status', { name: /Loading scores/ })).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('gives a failed run its reason instead of scores', async () => {
    stubApi({
      ...ME,
      'GET /api/eval-run/r1': Response.json(
        detail('r1', {
          status: 'failed',
          errorCode: 'no_runnable_case',
          headline: null,
          scores: [],
          cases: [],
          cosine: null,
        }),
      ),
    })

    renderRoutes('/eval-run/r1')

    expect(await screen.findByText('Failed')).toBeInTheDocument()
    expect(screen.getByText(/no case could run/i)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /start|retry/i })).not.toBeInTheDocument()
  })

  it('shows the group error state for an unknown run', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    stubApi({ ...ME, 'GET /api/eval-run/nope': envelope('not_found', 404) })

    renderRoutes('/eval-run/nope')

    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
