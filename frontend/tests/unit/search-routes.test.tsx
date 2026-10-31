import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { NAV } from '@/app/nav'

import { envelope, stubApi, USER } from './support'
import { renderRoutes } from './render-routes'
import { hit } from './search-support'

const ME = { 'GET /api/user/me': Response.json(USER) }
const result = (items: unknown[], incomplete = false) => Response.json({ items, incomplete })

afterEach(() => {
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

    expect(await screen.findByRole('button', { name: /try again/i })).toBeInTheDocument()
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

    expect(await screen.findByRole('button', { name: /try again/i })).toBeInTheDocument()
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
