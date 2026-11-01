import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RunEvent } from '@/shared/api'

import { renderRoutes } from './render-routes'
import { USER, envelope, stubApi } from './support'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const { toast } = await import('sonner')

const at = '2026-10-30T10:00:00Z'
const conversation = (id: string, title: string | null = null) => ({
  id,
  title,
  createdAt: at,
  updatedAt: at,
})
const page = (items: unknown[]) => Response.json({ items, nextCursor: null })
const message = (id: string, role: 'user' | 'assistant', text: string) => ({
  id,
  role,
  text,
  runId: 'r1',
  createdAt: at,
})
const run = (status: string, errorCode: string | null = null) => ({
  id: 'r1',
  status,
  errorCode,
  createdAt: at,
})
const detail = (latestRun: unknown = null) =>
  Response.json({ ...conversation('c1', 'Plan the migration'), latestRun })

function sse(events: RunEvent[]): Response {
  const body = events
    .map((event) => `id: ${String(event.sequence)}\ndata: ${JSON.stringify(event)}\n\n`)
    .join('')
  return new Response(body, { headers: { 'content-type': 'text/event-stream' } })
}

const ME = { 'GET /api/user/me': Response.json(USER) }

beforeEach(() => vi.clearAllMocks())
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the conversation list route', () => {
  it('sends a visitor to sign in', async () => {
    stubApi({ 'GET /api/user/me': envelope('unauthenticated', 401) })

    const router = renderRoutes('/conversation')

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/sign-in')
    })
  })

  it('shows the empty state with the start action', async () => {
    stubApi({ ...ME, 'GET /api/conversation': page([]) })

    renderRoutes('/conversation')

    expect(await screen.findByRole('heading', { level: 1, name: 'Conversations' })).toBeVisible()
    expect(await screen.findByText('No conversations yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start conversation' })).toBeEnabled()
  })

  it('lists the conversations with a link each, untitled ones by a fallback name', async () => {
    stubApi({
      ...ME,
      'GET /api/conversation': page([conversation('c1', 'Plan the migration'), conversation('c2')]),
    })

    renderRoutes('/conversation')

    const first = await screen.findByRole('link', { name: /Plan the migration/ })
    expect(first).toHaveAttribute('href', '/conversation/c1')
    expect(screen.getByRole('link', { name: /Untitled conversation/ })).toHaveAttribute(
      'href',
      '/conversation/c2',
    )
  })

  it('shows more conversations from the next cursor, until there are none', async () => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: Request) => {
        const url = new URL(input.url)
        urls.push(`${url.pathname}${url.search}`)
        if (url.pathname === '/api/user/me') return Promise.resolve(Response.json(USER))
        const cursor = url.searchParams.get('cursor')
        return Promise.resolve(
          cursor === 'abc'
            ? Response.json({ items: [conversation('c2', 'Older one')], nextCursor: null })
            : Response.json({ items: [conversation('c1', 'Newest')], nextCursor: 'abc' }),
        )
      }),
    )

    renderRoutes('/conversation')

    expect(await screen.findByRole('link', { name: /Newest/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Older one/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show more' }))

    expect(await screen.findByRole('link', { name: /Older one/ })).toHaveAttribute(
      'href',
      '/conversation/c2',
    )
    expect(screen.getByRole('link', { name: /Newest/ })).toBeInTheDocument()
    expect(urls.some((url) => url.includes('cursor=abc'))).toBe(true)
    expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument()
  })

  it('keeps the loaded conversations and offers a retry when the next page fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.stubGlobal(
      'fetch',
      vi.fn((input: Request) => {
        const url = new URL(input.url)
        if (url.pathname === '/api/user/me') return Promise.resolve(Response.json(USER))
        return Promise.resolve(
          url.searchParams.get('cursor') === 'abc'
            ? envelope('internal', 500)
            : Response.json({ items: [conversation('c1', 'Newest')], nextCursor: 'abc' }),
        )
      }),
    )

    renderRoutes('/conversation')
    await userEvent.click(await screen.findByRole('button', { name: 'Show more' }))

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Newest/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    expect(screen.queryByText(/hunter2/)).not.toBeInTheDocument()
  })

  it('starts a conversation and opens it', async () => {
    const fetchMock = stubApi({
      ...ME,
      'GET /api/conversation': page([]),
      'POST /api/conversation': Response.json(conversation('c9'), { status: 201 }),
      'GET /api/conversation/c9': Response.json({ ...conversation('c9'), latestRun: null }),
      'GET /api/conversation/c9/message': page([]),
    })

    const router = renderRoutes('/conversation')
    await userEvent.click(await screen.findByRole('button', { name: 'Start conversation' }))

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/conversation/c9')
    })
    expect(fetchMock.mock.calls.some(([r]) => r.method === 'POST')).toBe(true)
  })

  it('toasts our words when starting fails and stays on the list', async () => {
    stubApi({
      ...ME,
      'GET /api/conversation': page([]),
      'POST /api/conversation': envelope('internal', 500),
    })
    vi.spyOn(console, 'error').mockImplementation(() => undefined)

    const router = renderRoutes('/conversation')
    await userEvent.click(await screen.findByRole('button', { name: 'Start conversation' }))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalled()
    })
    expect(router.state.location.pathname).toBe('/conversation')
    expect(vi.mocked(toast.error).mock.calls[0]?.[0]).not.toMatch(/hunter2/)
  })

  it('renders the group error state when the list cannot load', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    stubApi({ ...ME, 'GET /api/conversation': envelope('internal', 500) })

    renderRoutes('/conversation')

    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByRole('banner')).toBeInTheDocument()
  })
})

describe('the conversation route', () => {
  it('shows an empty state above the send form for a new conversation', async () => {
    stubApi({
      ...ME,
      'GET /api/conversation/c1': detail(),
      'GET /api/conversation/c1/message': page([]),
    })

    renderRoutes('/conversation/c1')

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Plan the migration' }),
    ).toBeVisible()
    expect(screen.getByText('Ask the agent something')).toBeInTheDocument()
    expect(screen.getByLabelText('Message')).toBeEnabled()
  })

  it('shows the history oldest first, assistant text as Markdown, in a log', async () => {
    stubApi({
      ...ME,
      'GET /api/conversation/c1': detail(run('completed')),
      // The API answers newest first.
      'GET /api/conversation/c1/message': page([
        message('m2', 'assistant', 'Use **two** steps'),
        message('m1', 'user', 'How do I migrate?'),
      ]),
    })

    renderRoutes('/conversation/c1')

    const log = await screen.findByRole('log')
    const text = log.textContent
    expect(text.indexOf('How do I migrate?')).toBeLessThan(text.indexOf('Use two steps'))
    expect(within(log).getByText('two').tagName).toBe('STRONG')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows a failed run as an alert in our words and keeps the form enabled', async () => {
    stubApi({
      ...ME,
      'GET /api/conversation/c1': detail(run('failed', 'upstream_unavailable')),
      'GET /api/conversation/c1/message': page([message('m1', 'user', 'Hi')]),
    })

    renderRoutes('/conversation/c1')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/unavailable/i)
    expect(screen.getByLabelText('Message')).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeEnabled()
  })

  it('follows a run in progress on load and replaces it with the stored answer', async () => {
    let answered = false
    stubApi({
      ...ME,
      'GET /api/conversation/c1': detail(run('running')),
      'GET /api/conversation/c1/message': () =>
        page(
          answered
            ? [message('m2', 'assistant', 'The answer'), message('m1', 'user', 'Question')]
            : [message('m1', 'user', 'Question')],
        ),
      'GET /api/run/r1/event': () => {
        answered = true
        return sse([
          { type: 'run_started', sequence: 1, createdAt: at },
          { type: 'text_delta', sequence: 2, createdAt: at, text: 'The ' },
          { type: 'text_delta', sequence: 3, createdAt: at, text: 'answer' },
          {
            type: 'run_finished',
            sequence: 4,
            createdAt: at,
            status: 'completed',
            errorCode: null,
          },
        ])
      },
    })

    renderRoutes('/conversation/c1')

    await waitFor(() => {
      expect(screen.getAllByText('The answer')).toHaveLength(1)
    })
    expect(screen.getByRole('log')).toHaveTextContent('Question')
    await waitFor(() => expect(screen.queryByText(/Agent is working/)).not.toBeInTheDocument())
  })

  it('shows a tool call in place with its result', async () => {
    stubApi({
      ...ME,
      'GET /api/conversation/c1': detail(run('running')),
      'GET /api/conversation/c1/message': page([message('m1', 'user', 'Question')]),
      'GET /api/run/r1/event': sse([
        { type: 'run_started', sequence: 1, createdAt: at },
        {
          type: 'tool_call_started',
          sequence: 2,
          createdAt: at,
          toolUseId: 't1',
          name: 'lookup',
          input: { q: 'x' },
        },
        {
          type: 'tool_call_finished',
          sequence: 3,
          createdAt: at,
          toolUseId: 't1',
          status: 'denied',
          output: 'not allowed',
        },
        {
          type: 'run_finished',
          sequence: 4,
          createdAt: at,
          status: 'failed',
          errorCode: 'refused',
        },
      ]),
    })

    renderRoutes('/conversation/c1')

    expect(await screen.findByText('lookup')).toBeInTheDocument()
    expect(screen.getByText('Denied')).toBeInTheDocument()
    expect(screen.getByText('not allowed')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  describe('a call waiting for approval', () => {
    const DIGEST = 'c'.repeat(64)
    const waitingEvents: RunEvent[] = [
      { type: 'run_started', sequence: 1, createdAt: at },
      {
        type: 'tool_call_started',
        sequence: 2,
        createdAt: at,
        toolUseId: 't1',
        name: 'fixture__note',
        input: { text: 'hello' },
      },
      {
        type: 'approval_requested',
        sequence: 3,
        createdAt: at,
        approvalId: 'a1',
        toolUseId: 't1',
        argumentsDigest: DIGEST,
      },
    ]
    const waitingApi = (extra: Record<string, Response> = {}) =>
      stubApi({
        ...ME,
        'GET /api/conversation/c1': detail(run('awaiting_approval')),
        'GET /api/conversation/c1/message': page([message('m1', 'user', 'Question')]),
        'GET /api/run/r1/event': sse(waitingEvents),
        ...extra,
      })

    it('shows the arguments and both decisions, keeps send off and announces the wait', async () => {
      waitingApi()

      renderRoutes('/conversation/c1')

      expect(await screen.findByText('Needs approval')).toBeInTheDocument()
      const box = screen.getByRole('group', { name: 'Arguments of fixture__note' })
      expect(box).toHaveTextContent('"text": "hello"')
      expect(screen.getByRole('button', { name: 'Approve call' })).toBeEnabled()
      expect(screen.getByRole('button', { name: 'Reject call' })).toBeEnabled()
      expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
      expect(screen.queryByText('Agent is working…')).not.toBeInTheDocument()
      await waitFor(() => {
        expect(screen.getByRole('status')).toHaveTextContent(
          'The agent is waiting for your approval to call fixture__note.',
        )
      })
    })

    it('sends the decision with the digest, turns both buttons off and reopens the stream', async () => {
      const fetchMock = waitingApi({
        'POST /api/approval/a1/decision': Response.json({
          id: 'a1',
          toolUseId: 't1',
          decision: 'approved',
          decidedAt: at,
        }),
      })
      renderRoutes('/conversation/c1')

      await userEvent.click(await screen.findByRole('button', { name: 'Approve call' }))

      await waitFor(() => {
        const posts = fetchMock.mock.calls.filter(([request]) => request.method === 'POST')
        expect(posts).toHaveLength(1)
      })
      const post = fetchMock.mock.calls.find(([request]) => request.method === 'POST')?.[0]
      expect(await post?.json()).toEqual({ decision: 'approved', argumentsDigest: DIGEST })
      expect(screen.getByRole('button', { name: 'Reject call' })).toBeDisabled()
      await waitFor(() => {
        const streams = fetchMock.mock.calls.filter(([request]) =>
          request.url.endsWith('/api/run/r1/event'),
        )
        expect(streams.length).toBeGreaterThan(1)
      })
    })

    it('announces each wait afresh when two calls of the same tool wait in turn', async () => {
      const second: RunEvent[] = [
        {
          type: 'tool_call_started',
          sequence: 4,
          createdAt: at,
          toolUseId: 't2',
          name: 'fixture__note',
          input: { text: 'again' },
        },
        {
          type: 'approval_requested',
          sequence: 5,
          createdAt: at,
          approvalId: 'a2',
          toolUseId: 't2',
          argumentsDigest: 'd'.repeat(64),
        },
      ]
      const decision = (id: string, toolUseId: string, sequence: number): RunEvent => ({
        type: 'approval_decided',
        sequence,
        createdAt: at,
        approvalId: id,
        toolUseId,
        decision: 'rejected',
      })
      let call = 0
      const streams = [
        [...waitingEvents, ...second],
        [...waitingEvents, ...second, decision('a1', 't1', 6)],
        [...waitingEvents, ...second, decision('a1', 't1', 6), decision('a2', 't2', 7)],
      ]
      const decided = Response.json({
        id: 'a1',
        toolUseId: 't1',
        decision: 'rejected',
        decidedAt: at,
      })
      stubApi({
        ...ME,
        'GET /api/conversation/c1': detail(run('awaiting_approval')),
        'GET /api/conversation/c1/message': page([message('m1', 'user', 'Question')]),
        'GET /api/run/r1/event': () => sse(streams[Math.min(call, 2)] ?? []),
        'POST /api/approval/a1/decision': () => {
          call = 1
          return decided.clone()
        },
        'POST /api/approval/a2/decision': () => {
          call = 2
          return decided.clone()
        },
      })
      renderRoutes('/conversation/c1')

      // The status line is read fresh each time: the loading state has one of its own.
      const line = () => screen.getByRole('status').textContent
      await waitFor(() => {
        expect(line()).toContain('2 tool calls')
      })
      const first = line()

      const [firstReject] = await screen.findAllByRole('button', { name: 'Reject call' })
      await userEvent.click(firstReject as HTMLElement)
      await waitFor(() => {
        expect(line()).toContain('to call fixture__note')
      })
      expect(line()).not.toBe(first)

      await userEvent.click(await screen.findByRole('button', { name: 'Reject call' }))
      await waitFor(() => {
        expect(line()).toBe('')
      })
    })

    it('says so in our words when the call was already decided, and keeps the decisions open', async () => {
      waitingApi({ 'POST /api/approval/a1/decision': envelope('conflict', 409) })
      renderRoutes('/conversation/c1')

      await userEvent.click(await screen.findByRole('button', { name: 'Reject call' }))

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('already decided'))
      })
      expect(toast.error).not.toHaveBeenCalledWith(expect.stringContaining('hunter2'))
    })
  })

  it('shows a down tool server as a notice in the log and goes on to the answer', async () => {
    stubApi({
      ...ME,
      'GET /api/conversation/c1': detail(run('running')),
      'GET /api/conversation/c1/message': page([message('m1', 'user', 'Question')]),
      'GET /api/run/r1/event': sse([
        { type: 'run_started', sequence: 1, createdAt: at },
        { type: 'mcp_server_unavailable', sequence: 2, createdAt: at, name: 'knowledge' },
        { type: 'text_delta', sequence: 3, createdAt: at, text: 'Answer without tools.' },
        { type: 'run_finished', sequence: 4, createdAt: at, status: 'completed', errorCode: null },
      ]),
    })

    renderRoutes('/conversation/c1')

    const log = await screen.findByRole('log', { name: 'Conversation history' })
    const notice = await within(log).findByRole('alert')
    expect(notice).toHaveTextContent('knowledge')
    expect(notice).toHaveTextContent(/unavailable/i)
    const answer = await within(log).findByText('Answer without tools.')
    expect(notice.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.queryByText(/didn't finish/)).not.toBeInTheDocument()
  })

  it('sends a message and follows the new run', async () => {
    stubApi({
      ...ME,
      'GET /api/conversation/c1': detail(),
      'GET /api/conversation/c1/message': page([]),
      'POST /api/conversation/c1/message': Response.json(
        { message: message('m1', 'user', 'Hello'), run: run('queued') },
        { status: 201 },
      ),
      'GET /api/run/r1/event': () =>
        sse([
          { type: 'run_started', sequence: 1, createdAt: at },
          { type: 'text_delta', sequence: 2, createdAt: at, text: 'Streaming reply' },
        ]),
    })

    renderRoutes('/conversation/c1')
    await userEvent.type(await screen.findByLabelText('Message'), 'Hello')
    await userEvent.click(screen.getByRole('button', { name: 'Send message' }))

    expect(await screen.findByText('Streaming reply')).toBeInTheDocument()
  })

  it('renders the group error state for a conversation that is not there', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    stubApi({ ...ME, 'GET /api/conversation/zzz': envelope('not_found', 404) })

    renderRoutes('/conversation/zzz')

    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()
  })
})
