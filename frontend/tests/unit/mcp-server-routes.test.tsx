import { focusManager, onlineManager } from '@tanstack/react-query'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NAV } from '@/app/nav'

import { USER, createTestClient, envelope, stubApi } from './support'
import { renderRoutes } from './render-routes'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const { toast } = await import('sonner')

const ADMIN = { ...USER, role: 'admin' as const }
const ME = { 'GET /api/user/me': Response.json(ADMIN) }
const at = '2026-11-01T10:00:00Z'
const DIGEST = 'a'.repeat(64)

const server = (over: Record<string, unknown> = {}) => ({
  id: 's1',
  name: 'lab',
  enabled: true,
  pinStatus: 'current',
  createdAt: at,
  updatedAt: at,
  ...over,
})
const policy = (items: unknown[]) => Response.json({ mcpServerId: 's1', items })
const row = (toolName: string, effect: string | null, effects = ['allow', 'ask', 'deny']) => ({
  toolName,
  effect,
  effects,
})
const listing = (items: unknown[]) =>
  Response.json({ mcpServerId: 's1', listingDigest: DIGEST, items })
const listed = (name: string, change: string, over: Record<string, unknown> = {}) => ({
  name,
  change,
  description: `${name} text`,
  inputSchema: '{}',
  pinnedDescription: null,
  pinnedInputSchema: null,
  ...over,
})

beforeEach(() => vi.clearAllMocks())
afterEach(() => {
  vi.useRealTimers()
  focusManager.setFocused(undefined)
  onlineManager.setOnline(true)
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const PATHS = ['/mcp-server', '/mcp-server/s1', '/mcp-server/s1/listing']

describe('access to the MCP server routes', () => {
  it.each(PATHS)('sends a visitor from %s to sign in', async (path) => {
    stubApi({ 'GET /api/user/me': envelope('unauthenticated', 401) })
    const router = renderRoutes(path)
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/sign-in')
    })
  })

  it.each(PATHS)('sends a user from %s to /forbidden', async (path) => {
    stubApi({ 'GET /api/user/me': Response.json(USER) })
    const router = renderRoutes(path)
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/forbidden')
    })
  })

  it('has an admin-only nav entry', () => {
    expect(NAV.find((entry) => entry.to === '/mcp-server')?.role).toBe('admin')
  })
})

describe('the MCP server list', () => {
  it('shows each server with its pin status and whether it is on, in words', async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server': Response.json({
        items: [
          server({ id: 's1', name: 'lab', pinStatus: 'changed' }),
          server({ id: 's2', name: 'knowledge', pinStatus: 'not_required', enabled: false }),
        ],
        nextCursor: null,
      }),
    })

    renderRoutes('/mcp-server')

    const lab = (await screen.findByRole('link', { name: 'lab' })).closest('li') as HTMLElement
    expect(within(lab).getByText('Listing changed')).toBeInTheDocument()
    expect(within(lab).getByText('Enabled')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'lab' })).toHaveAttribute('href', '/mcp-server/s1')
    const knowledge = screen.getByRole('link', { name: 'knowledge' }).closest('li') as HTMLElement
    expect(within(knowledge).getByText('No pin needed')).toBeInTheDocument()
    expect(within(knowledge).getByText('Disabled')).toBeInTheDocument()
  })

  it('shows more servers from the next cursor', async () => {
    let calls = 0
    stubApi({
      ...ME,
      'GET /api/mcp-server': () => {
        calls += 1
        return Response.json(
          calls > 1
            ? { items: [server({ id: 's2', name: 'older' })], nextCursor: null }
            : { items: [server({ id: 's1', name: 'newest' })], nextCursor: 'abc' },
        )
      },
    })

    renderRoutes('/mcp-server')
    await userEvent.click(await screen.findByRole('button', { name: 'Show more' }))

    expect(await screen.findByRole('link', { name: 'older' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'newest' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument()
  })

  it('keeps the loaded servers and offers a retry when the next page fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let calls = 0
    stubApi({
      ...ME,
      'GET /api/mcp-server': () => {
        calls += 1
        return calls === 1
          ? Response.json({ items: [server({ name: 'newest' })], nextCursor: 'abc' })
          : envelope('internal', 500)
      },
    })

    renderRoutes('/mcp-server')
    await userEvent.click(await screen.findByRole('button', { name: 'Show more' }))

    expect(await screen.findByText("Couldn't load more servers")).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'newest' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    expect(screen.queryByText(/hunter2/)).not.toBeInTheDocument()
  })

  it('shows the empty state', async () => {
    stubApi({ ...ME, 'GET /api/mcp-server': Response.json({ items: [], nextCursor: null }) })

    renderRoutes('/mcp-server')

    expect(await screen.findByText('No MCP servers')).toBeInTheDocument()
  })

  it('shows the group error when the API is unreachable', async () => {
    stubApi({ ...ME, 'GET /api/mcp-server': envelope('internal', 500) })

    renderRoutes('/mcp-server')

    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()
  })
})

describe('the MCP server page', () => {
  it('reads a tool with no policy row as denied, and offers only the effects it is sent', async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'unpinned', enabled: false })),
      'GET /api/tool-policy/s1': policy([row('read', null), row('write', 'ask', ['ask', 'deny'])]),
    })

    renderRoutes('/mcp-server/s1')

    const select = await screen.findByRole('combobox', { name: 'Policy for read' })
    expect(select).toHaveTextContent('Denied (no rule)')
    expect(screen.getByRole('combobox', { name: 'Policy for write' })).toHaveTextContent('Ask')
    await userEvent.click(select)
    expect(await screen.findByRole('option', { name: 'Allow' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    await userEvent.click(screen.getByRole('combobox', { name: 'Policy for write' }))
    const list = await screen.findByRole('listbox')
    expect(within(list).queryByRole('option', { name: 'Allow' })).not.toBeInTheDocument()
    expect(within(list).getByRole('option', { name: 'Deny' })).toBeInTheDocument()
  })

  it('says what turning a server off does, and what a new listing does to conversations', async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server()),
      'GET /api/tool-policy/s1': policy([row('read', 'allow')]),
    })

    renderRoutes('/mcp-server/s1')

    expect(await screen.findByText(/never gets its tools/)).toBeInTheDocument()
    expect(screen.getByText(/Existing conversations keep their tools/)).toBeInTheDocument()
  })

  it('offers the review as the filled action only when the listing is not current', async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/tool-policy/s1': policy([]),
    })

    renderRoutes('/mcp-server/s1')

    expect(await screen.findByRole('link', { name: 'Review listing' })).toHaveAttribute(
      'href',
      '/mcp-server/s1/listing',
    )
  })

  it('has no review for the knowledge server', async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(
        server({ name: 'knowledge', pinStatus: 'not_required' }),
      ),
      'GET /api/tool-policy/s1': policy([row('search', 'allow')]),
    })

    renderRoutes('/mcp-server/s1')

    await screen.findByRole('combobox', { name: 'Policy for search' })
    expect(screen.queryByRole('link', { name: 'Review listing' })).not.toBeInTheDocument()
  })

  it('sets a policy with the chosen effect', async () => {
    const put = vi.fn()
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server()),
      'GET /api/tool-policy/s1': policy([row('read', 'ask')]),
      'PUT /api/tool-policy/s1/read': () => {
        put()
        return Response.json(row('read', 'allow'))
      },
    })
    renderRoutes('/mcp-server/s1')

    await userEvent.click(await screen.findByRole('combobox', { name: 'Policy for read' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Allow' }))

    await waitFor(() => {
      expect(put).toHaveBeenCalledTimes(1)
    })
  })

  it('keeps the stored effect and toasts when a policy write fails', async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server()),
      'GET /api/tool-policy/s1': policy([row('read', 'ask')]),
      'PUT /api/tool-policy/s1/read': envelope('internal', 500),
    })
    renderRoutes('/mcp-server/s1')

    await userEvent.click(await screen.findByRole('combobox', { name: 'Policy for read' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Deny' }))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(1)
    })
    expect(screen.getByRole('combobox', { name: 'Policy for read' })).toHaveTextContent('Ask')
  })

  it('fails a policy set offline with a toast, and sends nothing more on reconnect', async () => {
    const puts = vi.fn()
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server()),
      'GET /api/tool-policy/s1': policy([row('read', 'ask')]),
      'PUT /api/tool-policy/s1/read': () => {
        puts()
        return envelope('internal', 500)
      },
    })
    renderRoutes('/mcp-server/s1')
    const select = await screen.findByRole('combobox', { name: 'Policy for read' })

    act(() => {
      onlineManager.setOnline(false)
    })
    await userEvent.click(select)
    await userEvent.click(await screen.findByRole('option', { name: 'Allow' }))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(1)
    })
    act(() => {
      onlineManager.setOnline(true)
    })
    expect(puts).toHaveBeenCalledTimes(1)
  })

  it('fails a toggle made offline with a toast, and sends nothing more on reconnect', async () => {
    const patches = vi.fn()
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server()),
      'GET /api/tool-policy/s1': policy([]),
      'PATCH /api/mcp-server/s1': () => {
        patches()
        return envelope('internal', 500)
      },
    })
    renderRoutes('/mcp-server/s1')
    const button = await screen.findByRole('button', { name: 'Disable server' })

    act(() => {
      onlineManager.setOnline(false)
    })
    await userEvent.click(button)

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(1)
    })
    act(() => {
      onlineManager.setOnline(true)
    })
    expect(patches).toHaveBeenCalledTimes(1)
  })

  it('disables an enabled server', async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server()),
      'GET /api/tool-policy/s1': policy([]),
      'PATCH /api/mcp-server/s1': () => Response.json(server({ enabled: false })),
    })
    const fetchMock = vi.mocked(fetch)
    renderRoutes('/mcp-server/s1')

    await userEvent.click(await screen.findByRole('button', { name: 'Disable server' }))

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledTimes(1)
    })
    const request = fetchMock.mock.calls
      .map((call) => call[0] as unknown as Request)
      .find((r) => r.method === 'PATCH')
    expect(await request?.clone().json()).toEqual({ enabled: false })
  })

  it('toasts our words when enabling is refused', async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ enabled: false, pinStatus: 'unpinned' })),
      'GET /api/tool-policy/s1': policy([]),
      'PATCH /api/mcp-server/s1': envelope('conflict', 409),
    })
    renderRoutes('/mcp-server/s1')

    await userEvent.click(await screen.findByRole('button', { name: 'Enable server' }))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(1)
    })
    expect(vi.mocked(toast.error).mock.calls[0]?.[0]).toBe(
      'Review and accept the listing first. Accepting enables the server.',
    )
  })
})

describe('the listing review route', () => {
  it('shows every tool whole with its change, and the accept after all of it', async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': listing([
        listed('note', 'changed', { pinnedDescription: 'old note text' }),
        listed('fresh', 'added'),
      ]),
    })

    renderRoutes('/mcp-server/s1/listing')

    expect(await screen.findByText('old note text')).toBeInTheDocument()
    expect(screen.getByText('Changed')).toBeInTheDocument()
    expect(screen.getByText('Added')).toBeInTheDocument()
    expect(screen.getByText(/Accepting enables the server/)).toBeInTheDocument()
    expect(screen.getByText(/deny a changed one/)).toBeInTheDocument()
    const accept = screen.getByRole('button', { name: 'Accept listing' })
    const last = screen.getByText('fresh text')
    expect(last.compareDocumentPosition(accept) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('reads the server once on arrival, from the page and not from a loader', async () => {
    const fetchMock = stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': listing([listed('note', 'added')]),
    })

    renderRoutes('/mcp-server/s1/listing')

    await screen.findByRole('button', { name: 'Accept listing' })
    const reads = fetchMock.mock.calls.filter(
      (call) => new URL(call[0].url).pathname === '/api/mcp-server/s1/listing',
    )
    expect(reads).toHaveLength(1)
  })

  it('offers no accept when the listing matches the pin', async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server()),
      'GET /api/mcp-server/s1/listing': listing([listed('note', 'unchanged')]),
    })

    renderRoutes('/mcp-server/s1/listing')

    expect(await screen.findByText(/matches the accepted listing/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept listing' })).not.toBeInTheDocument()
  })

  it('sends the digest it showed, and no definition', async () => {
    const calls: string[] = []
    const fetchMock = stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': listing([listed('note', 'added')]),
      'POST /api/mcp-server/s1/acceptance': () => {
        calls.push('post')
        return Response.json(server())
      },
    })
    const router = renderRoutes('/mcp-server/s1/listing')

    await userEvent.click(await screen.findByRole('button', { name: 'Accept listing' }))

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/mcp-server/s1')
    })
    const post = fetchMock.mock.calls.map((call) => call[0]).find((r) => r.method === 'POST')
    expect(await post?.clone().json()).toEqual({ listingDigest: DIGEST })
    expect(toast.success).toHaveBeenCalledTimes(1)
  })

  it('toasts and reloads the listing when the accept is stale', async () => {
    let reads = 0
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': () => {
        reads += 1
        return listing([listed(reads === 1 ? 'first' : 'second', 'added')])
      },
      'POST /api/mcp-server/s1/acceptance': envelope('conflict', 409),
    })
    const router = renderRoutes('/mcp-server/s1/listing')

    await userEvent.click(await screen.findByRole('button', { name: 'Accept listing' }))

    expect(await screen.findByText('second text')).toBeInTheDocument()
    expect(toast.error).toHaveBeenCalledTimes(1)
    expect(vi.mocked(toast.error).mock.calls[0]?.[0]).toBe(
      'The listing changed since you read it. Review the new listing before accepting.',
    )
    expect(router.state.location.pathname).toBe('/mcp-server/s1/listing')
  })

  it('sends the accept once, on a click, and never retries or resumes it', async () => {
    const client = createTestClient()
    const fetchMock = stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': listing([listed('note', 'added')]),
      'POST /api/mcp-server/s1/acceptance': envelope('internal', 500),
    })
    renderRoutes('/mcp-server/s1/listing', client)
    const button = await screen.findByRole('button', { name: 'Accept listing' })
    const posts = () => fetchMock.mock.calls.filter((call) => call[0].method === 'POST')
    expect(posts()).toHaveLength(0)

    await userEvent.click(button)

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(1)
    })
    expect(posts()).toHaveLength(1)
    const options = client.getMutationCache().getAll()[0]?.options
    expect(options?.retry).toBe(false)
    expect(options?.networkMode).toBe('always')
  })

  it('keeps the listing and digest it showed when an accept fails, and retries with them', async () => {
    let reads = 0
    const fetchMock = stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': () => {
        reads += 1
        return Response.json({
          mcpServerId: 's1',
          listingDigest: reads === 1 ? DIGEST : 'b'.repeat(64),
          items: [listed(reads === 1 ? 'first' : 'second', 'added')],
        })
      },
      'POST /api/mcp-server/s1/acceptance': () => envelope('upstream_unavailable', 503),
    })
    renderRoutes('/mcp-server/s1/listing')

    await userEvent.click(await screen.findByRole('button', { name: 'Accept listing' }))
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(1)
    })
    await userEvent.click(screen.getByRole('button', { name: 'Accept listing' }))
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(2)
    })

    const posts = fetchMock.mock.calls.map((call) => call[0]).filter((r) => r.method === 'POST')
    const digests = await Promise.all(
      posts.map(
        async (post) => ((await post.clone().json()) as { listingDigest: string }).listingDigest,
      ),
    )
    expect(digests).toEqual([DIGEST, DIGEST])
    expect(reads).toBe(1)
    expect(screen.getByText('first text')).toBeInTheDocument()
  })

  it('keeps the listing it read when the tab is refocused or the network returns', async () => {
    let reads = 0
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': () => {
        reads += 1
        return listing([listed(reads === 1 ? 'first' : 'second', 'added')])
      },
    })
    const client = createTestClient()
    renderRoutes('/mcp-server/s1/listing', client)
    await screen.findByText('first text')
    // A suspense query is fresh for its first second whatever its `staleTime`, so the clock moves
    // on (Date only; the timers stay real) before the tab comes back.
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(Date.now() + 60_000)

    await act(async () => {
      focusManager.setFocused(false)
      focusManager.setFocused(true)
      document.dispatchEvent(new Event('visibilitychange'))
      onlineManager.setOnline(false)
      onlineManager.setOnline(true)
      window.dispatchEvent(new Event('online'))
      // Let a refetch, if one was started, reach the network: the library hops through a few
      // zero-delay timers (paused-mutation resume, notify batching) before it fetches.
      for (let turn = 0; turn < 10; turn += 1) {
        await new Promise((resolve) => setTimeout(resolve, 0))
      }
    })

    expect(reads).toBe(1)
    expect(screen.getByText('first text')).toBeInTheDocument()
  })

  it('keeps the listing when the reload after a 409 fails, even if the tab is refocused', async () => {
    let reads = 0
    const fetchMock = stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': () => {
        reads += 1
        return reads === 1
          ? listing([listed('first', 'added')])
          : envelope('upstream_unavailable', 503)
      },
      'POST /api/mcp-server/s1/acceptance': () => envelope('conflict', 409),
    })
    renderRoutes('/mcp-server/s1/listing')
    await userEvent.click(await screen.findByRole('button', { name: 'Accept listing' }))
    await waitFor(() => {
      expect(reads).toBe(2)
    })
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(1)
    })
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(Date.now() + 60_000)

    await act(async () => {
      focusManager.setFocused(false)
      focusManager.setFocused(true)
      document.dispatchEvent(new Event('visibilitychange'))
      onlineManager.setOnline(false)
      onlineManager.setOnline(true)
      window.dispatchEvent(new Event('online'))
      for (let turn = 0; turn < 10; turn += 1) {
        await new Promise((resolve) => setTimeout(resolve, 0))
      }
    })

    expect(reads).toBe(2)
    expect(screen.getByText('first text')).toBeInTheDocument()
    vi.useRealTimers()
    await userEvent.click(screen.getByRole('button', { name: 'Accept listing' }))
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(2)
    })
    const posts = fetchMock.mock.calls.map((call) => call[0]).filter((r) => r.method === 'POST')
    const digests = await Promise.all(
      posts.map(
        async (post) => ((await post.clone().json()) as { listingDigest: string }).listingDigest,
      ),
    )
    expect(digests).toEqual([DIGEST, DIGEST])
  })

  it('keeps the listing when the page is reopened within the cached second after a failed reload', async () => {
    let reads = 0
    const fetchMock = stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': () => {
        reads += 1
        return reads === 1
          ? listing([listed('first', 'added')])
          : envelope('upstream_unavailable', 503)
      },
      'POST /api/mcp-server/s1/acceptance': () => envelope('conflict', 409),
    })
    const router = renderRoutes('/mcp-server/s1/listing')
    await userEvent.click(await screen.findByRole('button', { name: 'Accept listing' }))
    await waitFor(() => {
      expect(reads).toBe(2)
    })
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(1)
    })

    // Leave the review page and come back inside the one second a suspense query stays cached.
    await act(async () => {
      await router.navigate('/mcp-server/s1')
    })
    await waitFor(() => {
      expect(screen.queryByText('first text')).not.toBeInTheDocument()
    })
    await act(async () => {
      await router.navigate('/mcp-server/s1/listing')
      for (let turn = 0; turn < 30; turn += 1) {
        await new Promise((resolve) => setTimeout(resolve, 0))
      }
    })

    expect(reads).toBe(2)
    expect(await screen.findByText('first text')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Accept listing' }))
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledTimes(2)
    })
    const posts = fetchMock.mock.calls.map((call) => call[0]).filter((r) => r.method === 'POST')
    const digests = await Promise.all(
      posts.map(
        async (post) => ((await post.clone().json()) as { listingDigest: string }).listingDigest,
      ),
    )
    expect(digests).toEqual([DIGEST, DIGEST])
  })

  it('shows no stored policy for a tool the accept takes off the pin', async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': listing([
        listed('gone', 'removed'),
        listed('kept', 'added'),
      ]),
      'GET /api/tool-policy/s1': policy([row('gone', 'allow'), row('kept', 'allow')]),
    })

    renderRoutes('/mcp-server/s1/listing')

    await screen.findAllByText(/Stored policy: Allow/)
    expect(screen.getAllByText(/Stored policy/)).toHaveLength(1)
  })

  it("shows each tool's stored policy beside its change, in words", async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': listing([
        listed('note', 'changed', { pinnedDescription: 'old' }),
        listed('fresh', 'added'),
        // New in this listing, so the policy document does not name it yet.
        listed('later', 'added'),
      ]),
      'GET /api/tool-policy/s1': policy([row('note', 'allow'), row('fresh', null)]),
    })

    renderRoutes('/mcp-server/s1/listing')

    expect(await screen.findByText(/Stored policy: Allow/)).toBeInTheDocument()
    // No row denies, and the screen says so: for a row-less tool and for one not listed yet.
    expect(screen.getAllByText('Stored policy: Denied (no rule)')).toHaveLength(2)
  })

  it('still renders the review when the policy read fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': listing([listed('note', 'added')]),
      'GET /api/tool-policy/s1': envelope('internal', 500),
    })

    renderRoutes('/mcp-server/s1/listing')

    expect(await screen.findByRole('button', { name: 'Accept listing' })).toBeInTheDocument()
    expect(screen.getByText('note text')).toBeInTheDocument()
    expect(screen.queryByText(/Stored policy/)).not.toBeInTheDocument()
  })

  it('words a server that did not answer, with a retry', async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': envelope('upstream_unavailable', 503),
    })

    renderRoutes('/mcp-server/s1/listing')

    expect(await screen.findByText("This server didn't answer")).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('words a listing that cannot be accepted', async () => {
    stubApi({
      ...ME,
      'GET /api/mcp-server/s1': Response.json(server({ pinStatus: 'changed' })),
      'GET /api/mcp-server/s1/listing': envelope('conflict', 409),
    })

    renderRoutes('/mcp-server/s1/listing')

    expect(await screen.findByText("This listing can't be accepted")).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
