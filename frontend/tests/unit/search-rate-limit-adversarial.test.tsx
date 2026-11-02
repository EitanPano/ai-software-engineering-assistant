import { act, fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { envelope, stubApi, USER } from './support'
import { renderRoutes } from './render-routes'
import { hit } from './search-support'

// QA's attacks on the `/search` limit state: a refusal that is not our envelope, a retry that
// meets another failure, rapid retries, and leaving the route while limited.
const ME = { 'GET /api/user/me': Response.json(USER) }
const result = (items: unknown[]) => Response.json({ items, incomplete: false })

const RATE_LIMITED_TITLE = 'Too many searches'
const GROUP_TITLE = 'Something went wrong'

const searchesSent = (fetchMock: ReturnType<typeof stubApi>) =>
  fetchMock.mock.calls.filter(([request]) => new URL(request.url).pathname === '/api/search').length

const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the search limit state under attack', () => {
  it('words a 429 from a proxy, whatever its body, as the wait and shows none of the body', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    stubApi({
      ...ME,
      'GET /api/search': () =>
        new Response('<html>Rate limit exceeded: token sk-secret-123 at 10.0.0.7</html>', {
          status: 429,
          headers: { 'content-type': 'text/html', 'retry-after': '3600' },
        }),
    })

    renderRoutes('/search?q=limiter')

    expect(await screen.findByText(RATE_LIMITED_TITLE)).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(/wait about a minute/i)
    expect(screen.queryByText(/sk-secret|10\.0\.0\.7|3600/)).not.toBeInTheDocument()
    expect(screen.queryByText(GROUP_TITLE)).not.toBeInTheDocument()
  })

  it('words a 429 with a JSON body that is not our envelope the same way', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    stubApi({
      ...ME,
      'GET /api/search': () => Response.json({ detail: 'slow down, hunter2' }, { status: 429 }),
    })

    renderRoutes('/search?q=limiter')

    expect(await screen.findByText(RATE_LIMITED_TITLE)).toBeInTheDocument()
    expect(screen.queryByText(/hunter2/)).not.toBeInTheDocument()
  })

  it.each([
    ['internal', 500],
    ['forbidden', 403],
    ['validation_failed', 400],
    ['upstream_unavailable', 503],
  ] as const)('shows the group failure, not the wait, for a %s (%i)', async (code, status) => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    stubApi({ ...ME, 'GET /api/search': envelope(code, status) })

    renderRoutes('/search?q=limiter')

    expect(await screen.findByText(GROUP_TITLE)).toBeInTheDocument()
    expect(screen.queryByText(RATE_LIMITED_TITLE)).not.toBeInTheDocument()
  })

  it('swaps the wait for the group failure when the retry meets another failure', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let calls = 0
    stubApi({
      ...ME,
      'GET /api/search': () => {
        calls += 1
        return calls === 1 ? envelope('rate_limited', 429) : envelope('upstream_unavailable', 503)
      },
    })

    renderRoutes('/search?q=limiter')
    await userEvent.click(await screen.findByRole('button', { name: /try again/i }))

    expect(await screen.findByText(GROUP_TITLE)).toBeInTheDocument()
    expect(screen.queryByText(RATE_LIMITED_TITLE)).not.toBeInTheDocument()
  })

  it('sends one search per retry even when the retry is clicked twice at once', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const fetchMock = stubApi({ ...ME, 'GET /api/search': () => envelope('rate_limited', 429) })

    renderRoutes('/search?q=limiter')
    const retry = await screen.findByRole('button', { name: /try again/i })
    expect(searchesSent(fetchMock)).toBe(1)

    // Two clicks in one tick, with nothing awaited between them: `userEvent.dblClick` waits a real
    // timer before each pointer action, and the stubbed API answers in microtasks, so its second
    // click can follow a finished retry and be a real second one. The button must still be there
    // for the second click to count; `fireEvent` renders inside a synchronous `act`.
    fireEvent.click(retry)
    expect(retry).toBeInTheDocument()
    fireEvent.click(retry)
    await settle()

    expect(await screen.findByText(RATE_LIMITED_TITLE)).toBeInTheDocument()
    expect(searchesSent(fetchMock)).toBe(2)
  })

  it('shows the form again, with no search sent, when the user leaves and returns to /search', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const fetchMock = stubApi({ ...ME, 'GET /api/search': () => envelope('rate_limited', 429) })

    const router = renderRoutes('/search?q=limiter')
    expect(await screen.findByText(RATE_LIMITED_TITLE)).toBeInTheDocument()

    await act(async () => {
      await router.navigate('/search')
    })

    expect(await screen.findByLabelText('Search the knowledge base')).toHaveValue('')
    expect(screen.queryByText(RATE_LIMITED_TITLE)).not.toBeInTheDocument()
    await settle()
    expect(searchesSent(fetchMock)).toBe(1)
  })

  it('searches another text after the wait, with no retry', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let calls = 0
    const fetchMock = stubApi({
      ...ME,
      'GET /api/search': () => {
        calls += 1
        return calls === 1 ? envelope('rate_limited', 429) : result([hit({ path: 'next.py' })])
      },
    })

    const router = renderRoutes('/search?q=limiter')
    expect(await screen.findByText(RATE_LIMITED_TITLE)).toBeInTheDocument()
    await act(async () => {
      await router.navigate('/search')
    })

    await userEvent.type(await screen.findByLabelText('Search the knowledge base'), 'other')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('next.py:10-24')).toBeInTheDocument()
    expect(searchesSent(fetchMock)).toBe(2)
  })
})
