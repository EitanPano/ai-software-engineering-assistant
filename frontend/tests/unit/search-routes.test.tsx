import { QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { createMemoryRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { NAV } from '@/app/nav'
import SearchError from '@/app/(site)/search/error'
import SearchPage from '@/app/(site)/search/page'

import { createAppClient, createTestClient, envelope, stubApi, USER } from './support'
import { renderRoutes } from './render-routes'
import { hit } from './search-support'

const ME = { 'GET /api/user/me': Response.json(USER) }
const result = (items: unknown[], incomplete = false) => Response.json({ items, incomplete })

// The segment's own state for a search refused by the limit; the group's is "Something went wrong".
const RATE_LIMITED_TITLE = 'Too many searches'

// How many searches the page has sent so far.
const searchesSent = (fetchMock: ReturnType<typeof stubApi>) =>
  fetchMock.mock.calls.filter(([request]) => new URL(request.url).pathname === '/api/search').length

// Lets every pending microtask and the fetches they start run, so a count taken after it is
// final: the stubbed API answers at once and nothing in the page waits on a timer.
const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })

// A click as a browser delivers it. Testing Library runs its own events (`userEvent`, `fireEvent`)
// inside a synchronous `act`, which renders the router's `loading` revalidation and so clears an
// error boundary that a browser's click leaves in place; without the act environment there is no
// such `act`. The flag is set back after each test.
const actEnvironment = globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT?: boolean }
const clickLikeABrowser = (element: HTMLElement) => {
  actEnvironment.IS_REACT_ACT_ENVIRONMENT = false
  element.click()
}

afterEach(() => {
  actEnvironment.IS_REACT_ACT_ENVIRONMENT = true
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('access to /search', () => {
  it('sends a visitor to sign in', async () => {
    stubApi({ 'GET /api/user/me': envelope('unauthenticated', 401) })

    const router = renderRoutes('/search?q=limiter')

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/sign-in')
    })
  })

  it('lists Search in the nav for everyone', () => {
    const entry = NAV.find((item) => item.to === '/search')
    expect(entry?.label).toBe('Search')
    expect(entry?.role).toBeUndefined()
  })
})

describe('the search route', () => {
  it('asks nothing before a search and shows the empty state with the form', async () => {
    const fetchMock = stubApi({ ...ME, 'GET /api/search': result([]) })

    renderRoutes('/search')

    expect(await screen.findByRole('heading', { level: 1, name: 'Search' })).toBeVisible()
    expect(screen.getByLabelText('Search the knowledge base')).toBeVisible()
    expect(screen.getByText('Search the knowledge base', { selector: 'h2' })).toBeVisible()
    const paths = fetchMock.mock.calls.map(([request]) => new URL(request.url).pathname)
    expect(paths).not.toContain('/api/search')
  })

  it('shows each hit with its repository, path:start-end and text, sending q and no limit', async () => {
    const fetchMock = stubApi({
      ...ME,
      'GET /api/search': result([
        hit(),
        hit({
          chunkId: 'c2',
          path: 'docs/guide.md',
          symbol: null,
          startLine: 5,
          endLine: 5,
          fullTextRank: null,
          content: 'plain words',
        }),
      ]),
    })

    renderRoutes('/search?q=check_limit')

    expect(await screen.findByText('src/limiter.py:10-24')).toBeInTheDocument()
    expect(screen.getByText('docs/guide.md:5')).toBeInTheDocument()
    expect(screen.getAllByText('octocat/Hello-World')).toHaveLength(2)
    expect(within(screen.getByRole('main')).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getAllByText('Keyword match')).toHaveLength(1)
    expect(screen.getByLabelText('Search the knowledge base')).toHaveValue('check_limit')
    const search = fetchMock.mock.calls
      .map(([request]) => new URL(request.url))
      .find((url) => url.pathname === '/api/search')
    expect(search?.searchParams.get('q')).toBe('check_limit')
    expect(search?.searchParams.get('limit')).toBeNull()
  })

  it('keeps the same two hits when two share a range, keyed by chunk id', async () => {
    stubApi({
      ...ME,
      'GET /api/search': result([hit({ chunkId: 'a' }), hit({ chunkId: 'b' })]),
    })

    renderRoutes('/search?q=x')

    expect(await screen.findAllByText('src/limiter.py:10-24')).toHaveLength(2)
  })

  it('says nothing matched after a search with no hit', async () => {
    stubApi({ ...ME, 'GET /api/search': result([]) })

    renderRoutes('/search?q=zzzz')

    expect(await screen.findByText('No matches')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('warns above the hits when the result is incomplete', async () => {
    stubApi({ ...ME, 'GET /api/search': result([hit()], true) })

    renderRoutes('/search?q=limiter')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/may be missing/i)
    const list = within(screen.getByRole('main')).getByRole('list')
    expect(alert.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows the group error state, with no server text, when the search fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    stubApi({ ...ME, 'GET /api/search': envelope('upstream_unavailable', 503) })

    renderRoutes('/search?q=limiter')

    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
    expect(screen.queryByText(RATE_LIMITED_TITLE)).not.toBeInTheDocument()
    expect(screen.queryByText(/hunter2/)).not.toBeInTheDocument()
  })

  it('shows the group error state when the API is unreachable', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.stubGlobal(
      'fetch',
      vi.fn((input: Request) =>
        new URL(input.url).pathname === '/api/user/me'
          ? Promise.resolve(Response.json(USER))
          : Promise.reject(new TypeError('network')),
      ),
    )

    renderRoutes('/search?q=limiter')

    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
    expect(screen.queryByText(RATE_LIMITED_TITLE)).not.toBeInTheDocument()
  })

  it('asks a user over the limit to wait, and its retry searches again', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let calls = 0
    const fetchMock = stubApi({
      ...ME,
      'GET /api/search': () => {
        calls += 1
        return calls === 1 ? envelope('rate_limited', 429) : result([hit()])
      },
    })

    renderRoutes('/search?q=limiter')

    expect(await screen.findByText(RATE_LIMITED_TITLE)).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(/wait about a minute/i)
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument()
    expect(screen.queryByText(/hunter2/)).not.toBeInTheDocument()
    // The segment's state replaces the page and its form, inside the shell.
    expect(screen.queryByLabelText('Search the knowledge base')).not.toBeInTheDocument()
    expect(screen.getByRole('banner')).toBeInTheDocument()
    await settle()
    expect(searchesSent(fetchMock)).toBe(1)

    await userEvent.click(screen.getByRole('button', { name: /try again/i }))

    expect(await screen.findByText('src/limiter.py:10-24')).toBeInTheDocument()
    expect(screen.getByLabelText('Search the knowledge base')).toHaveValue('limiter')
    expect(screen.queryByText(RATE_LIMITED_TITLE)).not.toBeInTheDocument()
    expect(searchesSent(fetchMock)).toBe(2)
  })

  it('retries from the wait with the cache fresh as in the app, and searches again', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let calls = 0
    const fetchMock = stubApi({
      ...ME,
      'GET /api/search': () => {
        calls += 1
        return calls === 1 ? envelope('rate_limited', 429) : result([hit()])
      },
    })

    renderRoutes('/search?q=limiter', createAppClient())
    expect(await screen.findByText(RATE_LIMITED_TITLE)).toBeInTheDocument()

    clickLikeABrowser(screen.getByRole('button', { name: /try again/i }))

    expect(await screen.findByText('src/limiter.py:10-24')).toBeInTheDocument()
    expect(searchesSent(fetchMock)).toBe(2)
  })

  it('retries a failed search from the group state with the cache fresh as in the app', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let calls = 0
    const fetchMock = stubApi({
      ...ME,
      'GET /api/search': () => {
        calls += 1
        return calls === 1 ? envelope('upstream_unavailable', 503) : result([hit()])
      },
    })

    renderRoutes('/search?q=limiter', createAppClient())
    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /try again/i }))

    expect(await screen.findByText('src/limiter.py:10-24')).toBeInTheDocument()
    expect(searchesSent(fetchMock)).toBe(2)
  })

  it('keeps asking the user to wait when the retry is refused too', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const fetchMock = stubApi({ ...ME, 'GET /api/search': envelope('rate_limited', 429) })

    renderRoutes('/search?q=limiter')
    expect(await screen.findByText(RATE_LIMITED_TITLE)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /try again/i }))

    await waitFor(() => {
      expect(searchesSent(fetchMock)).toBe(2)
    })
    expect(await screen.findByText(RATE_LIMITED_TITLE)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
    await settle()
    expect(searchesSent(fetchMock)).toBe(2)
  })

  it('searches the same text again after leaving the wait, with no retry', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let calls = 0
    const fetchMock = stubApi({
      ...ME,
      'GET /api/search': () => {
        calls += 1
        return calls === 1 ? envelope('rate_limited', 429) : result([hit()])
      },
    })

    const router = renderRoutes('/search?q=limiter')
    expect(await screen.findByText(RATE_LIMITED_TITLE)).toBeInTheDocument()

    // The user reads the wait, leaves it, and a minute later searches the same text again.
    await act(async () => {
      await router.navigate('/search')
    })
    await userEvent.type(await screen.findByLabelText('Search the knowledge base'), 'limiter')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('src/limiter.py:10-24')).toBeInTheDocument()
    expect(screen.queryByText(RATE_LIMITED_TITLE)).not.toBeInTheDocument()
    expect(searchesSent(fetchMock)).toBe(2)
  })

  it('keeps a result it holds when a retry is refused, so Back shows it with no search', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let calls = 0
    // The window holds after the first search: every later one is refused, a refetch of alpha too.
    const fetchMock = stubApi({
      ...ME,
      'GET /api/search': () => {
        calls += 1
        return calls === 1 ? result([hit({ path: 'alpha.py' })]) : envelope('rate_limited', 429)
      },
    })

    const router = renderRoutes('/search?q=alpha')
    expect(await screen.findByText('alpha.py:10-24')).toBeInTheDocument()
    await act(async () => {
      await router.navigate('/search?q=beta')
    })
    expect(await screen.findByText(RATE_LIMITED_TITLE)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /try again/i }))
    await waitFor(() => {
      expect(searchesSent(fetchMock)).toBe(3)
    })
    expect(await screen.findByText(RATE_LIMITED_TITLE)).toBeInTheDocument()

    await act(async () => {
      await router.navigate(-1)
    })

    expect(await screen.findByText('alpha.py:10-24')).toBeInTheDocument()
    expect(screen.queryByText(RATE_LIMITED_TITLE)).not.toBeInTheDocument()
    await settle()
    // alpha, beta, and the refused retry of beta: Back to alpha asked nothing.
    expect(searchesSent(fetchMock)).toBe(3)
  })

  it('retries a failed search from the group state and shows the hits', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let calls = 0
    const fetchMock = stubApi({
      ...ME,
      'GET /api/search': () => {
        calls += 1
        return calls === 1 ? envelope('upstream_unavailable', 503) : result([hit()])
      },
    })

    renderRoutes('/search?q=limiter')
    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /try again/i }))

    expect(await screen.findByText('src/limiter.py:10-24')).toBeInTheDocument()
    expect(searchesSent(fetchMock)).toBe(2)
  })

  it('shows the wait and keeps the retry to one search under StrictMode', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let calls = 0
    const fetchMock = stubApi({
      'GET /api/search': () => {
        calls += 1
        return calls === 1 ? envelope('rate_limited', 429) : result([hit()])
      },
    })
    // The page and its boundary as routes.tsx wires them, in StrictMode as main.tsx mounts them,
    // so every effect runs its setup, cleanup and setup again. The session guard is left out:
    // StrictMode on React's development build aborts the guard's first session read, which is not
    // what is under test.
    const router = createMemoryRouter(
      [{ path: '/search', loader: () => null, Component: SearchPage, ErrorBoundary: SearchError }],
      { initialEntries: ['/search?q=limiter'] },
    )
    render(
      <StrictMode>
        <QueryClientProvider client={createTestClient()}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </StrictMode>,
    )

    expect(await screen.findByText(RATE_LIMITED_TITLE)).toBeInTheDocument()
    await settle()
    expect(searchesSent(fetchMock)).toBe(1)

    await userEvent.click(screen.getByRole('button', { name: /try again/i }))

    expect(await screen.findByText('src/limiter.py:10-24')).toBeInTheDocument()
    expect(searchesSent(fetchMock)).toBe(2)
  })

  it('sends no search the user did not ask for', async () => {
    // Only Date is faked, so the query cache sees the result age while promises and timers run.
    vi.useFakeTimers({ toFake: ['Date'] })
    // A result is kept past any freshness the query client gives a read (30 s in the app).
    const age = () => {
      vi.setSystemTime(Date.now() + 10 * 60_000)
    }
    // The hit's file is named after the text searched, so the page shows which result it holds.
    const fetchMock = stubApi({
      ...ME,
      'GET /api/search': () => {
        const request = fetchMock.mock.calls.at(-1)?.[0]
        const q = request ? new URL(request.url).searchParams.get('q') : null
        return result([hit({ chunkId: `chunk-${String(q)}`, path: `${String(q)}.py` })])
      },
    })

    const router = renderRoutes('/search?q=alpha')
    expect(await screen.findByText('alpha.py:10-24')).toBeInTheDocument()
    expect(searchesSent(fetchMock)).toBe(1)

    // Each trigger fires on a result aged past its freshness and records the searches it sent.
    const sent: Record<string, number> = {}
    const trigger = async (name: string, fire: () => void | Promise<void>) => {
      age()
      const before = searchesSent(fetchMock)
      await act(async () => {
        await fire()
      })
      await settle()
      sent[name] = searchesSent(fetchMock) - before
    }

    await trigger('focus', () => {
      window.dispatchEvent(new Event('visibilitychange'))
    })
    await trigger('reconnect', () => {
      window.dispatchEvent(new Event('offline'))
      window.dispatchEvent(new Event('online'))
    })
    // The control: a search the user asks for sends exactly one.
    await trigger('asked', async () => {
      await router.navigate('/search?q=beta')
    })
    expect(await screen.findByText('beta.py:10-24')).toBeInTheDocument()
    await trigger('back', async () => {
      await router.navigate(-1)
    })

    expect(await screen.findByText('alpha.py:10-24')).toBeInTheDocument()
    expect(sent).toEqual({ focus: 0, reconnect: 0, asked: 1, back: 0 })
  })

  it('does not search for text over the limit and says so', async () => {
    const fetchMock = stubApi({ ...ME, 'GET /api/search': result([]) })

    renderRoutes(`/search?q=${'x'.repeat(501)}`)

    expect(await screen.findByText(/500 characters or fewer/)).toBeInTheDocument()
    const paths = fetchMock.mock.calls.map(([request]) => new URL(request.url).pathname)
    expect(paths).not.toContain('/api/search')
  })

  it('searches again from the form and puts the text in the URL', async () => {
    stubApi({ ...ME, 'GET /api/search': result([hit()]) })

    const router = renderRoutes('/search')
    await userEvent.type(await screen.findByLabelText('Search the knowledge base'), 'limiter')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => {
      expect(router.state.location.search).toBe('?q=limiter')
    })
    const list = await within(screen.getByRole('main')).findByRole('list')
    expect(within(list).getByText('src/limiter.py:10-24')).toBeInTheDocument()
  })
})
