import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderRoutes } from './render-routes'
import { createAppClient, envelope, stubApi } from './support'

// The route table, rendered in a memory router against a stubbed API: loaders, the group
// fallbacks and error boundaries, and the guards, end to end except the network.
const HEALTH = { status: 'ok', version: '1.2.3', uptimeSeconds: 42 }

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the home route', () => {
  it('shows the group fallback while the loader runs, then the page', async () => {
    let release: (response: Response) => void = () => undefined
    stubApi({
      'GET /api/health': () => new Promise<Response>((resolve) => (release = resolve)),
      'GET /api/user/me': envelope('unauthenticated', 401),
    })

    renderRoutes('/')

    expect(await screen.findByRole('status', { name: 'Loading' })).toBeInTheDocument()
    expect(screen.getByRole('banner')).toBeInTheDocument()

    release(Response.json(HEALTH))

    expect(await screen.findByRole('heading', { level: 1, name: 'Home' })).toBeInTheDocument()
    expect(screen.getByText(/API v1\.2\.3, up 42s/)).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: 'Loading' })).not.toBeInTheDocument()
  })

  it('renders the group error boundary inside the shell when the API fails, and retries', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let healthy = false
    stubApi({
      'GET /api/health': () => (healthy ? Response.json(HEALTH) : envelope('internal', 500)),
      'GET /api/user/me': envelope('unauthenticated', 401),
    })

    renderRoutes('/')

    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.queryByText(/hunter2/)).not.toBeInTheDocument()

    healthy = true
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText(/API v1\.2\.3/)).toBeInTheDocument()
  })
})

describe('the group retry with the cache fresh as in the app', () => {
  it('re-runs a failed loader from the boundary and shows the page', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let healthy = false
    stubApi({
      'GET /api/health': () => (healthy ? Response.json(HEALTH) : envelope('internal', 500)),
      'GET /api/user/me': envelope('unauthenticated', 401),
    })

    renderRoutes('/', createAppClient())
    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()

    healthy = true
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText(/API v1\.2\.3/)).toBeInTheDocument()
  })

  it('re-runs a failed loader on a URL with a hash, as the skip link makes', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let healthy = false
    const fetchMock = stubApi({
      'GET /api/health': () => (healthy ? Response.json(HEALTH) : envelope('internal', 500)),
      'GET /api/user/me': envelope('unauthenticated', 401),
    })
    const healthRequests = () =>
      fetchMock.mock.calls.filter(([request]) => new URL(request.url).pathname === '/api/health')
        .length

    renderRoutes('/#main', createAppClient())
    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()
    expect(healthRequests()).toBe(1)

    healthy = true
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

    await waitFor(() => {
      expect(healthRequests()).toBe(2)
    })
    expect(await screen.findByText(/API v1\.2\.3/)).toBeInTheDocument()
  })
})

describe('an unknown URL', () => {
  it('renders not-found inside the shell', async () => {
    stubApi({ 'GET /api/user/me': envelope('unauthenticated', 401) })

    renderRoutes('/no/such/page')

    expect(await screen.findByText('Page not found')).toBeInTheDocument()
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to the start' })).toHaveAttribute('href', '/')
  })
})
