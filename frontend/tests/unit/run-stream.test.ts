import { afterEach, describe, expect, it, vi } from 'vitest'

import { streamRun } from '@/entity/run/api/run'
import type { RunEvent } from '@/shared/api'

const at = '2026-10-30T10:00:00Z'
const started = (sequence: number): RunEvent => ({ type: 'run_started', sequence, createdAt: at })
const delta = (sequence: number, text: string): RunEvent => ({
  type: 'text_delta',
  sequence,
  createdAt: at,
  text,
})
const finished = (sequence: number): RunEvent => ({
  type: 'run_finished',
  sequence,
  createdAt: at,
  status: 'completed',
  errorCode: null,
})

function sse(events: RunEvent[]): Response {
  const body = events
    .map((event) => `id: ${String(event.sequence)}\ndata: ${JSON.stringify(event)}\n\n`)
    .join('')
  return new Response(body, { headers: { 'content-type': 'text/event-stream' } })
}

type Reply = Response | Error
// Each call to fetch takes the next reply; an Error is a dropped connection.
function stubStream(replies: Reply[]) {
  const queue = [...replies]
  const fetchMock = vi.fn((_request: Request) => {
    const reply = queue.shift()
    if (reply === undefined) return Promise.reject(new Error('no more replies'))
    return reply instanceof Error ? Promise.reject(reply) : Promise.resolve(reply)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const lastEventId = (fetchMock: ReturnType<typeof stubStream>, call: number) =>
  fetchMock.mock.calls[call]?.[0].headers.get('Last-Event-ID')

const noSleep = () => Promise.resolve()

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('streamRun', () => {
  it('delivers the events in order and ends at run_finished', async () => {
    const fetchMock = stubStream([sse([started(1), delta(2, 'Hi'), finished(3)])])
    const seen: number[] = []

    const outcome = await streamRun('r1', {
      signal: new AbortController().signal,
      onEvent: (event) => seen.push(event.sequence),
      sleep: noSleep,
    })

    expect(outcome).toBe('finished')
    expect(seen).toEqual([1, 2, 3])
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(new URL(fetchMock.mock.calls[0]?.[0].url ?? '').pathname).toBe('/api/run/r1/event')
    expect(lastEventId(fetchMock, 0)).toBeNull()
  })

  it('reopens with Last-Event-ID after a clean close before run_finished, once each', async () => {
    const fetchMock = stubStream([
      sse([started(1), delta(2, 'Hel')]),
      // The server replays after N: here it also repeats 2, which must not render twice.
      sse([delta(2, 'Hel'), delta(3, 'lo'), finished(4)]),
    ])
    const seen: number[] = []

    const outcome = await streamRun('r1', {
      signal: new AbortController().signal,
      onEvent: (event) => seen.push(event.sequence),
      sleep: noSleep,
    })

    expect(outcome).toBe('finished')
    expect(seen).toEqual([1, 2, 3, 4])
    expect(lastEventId(fetchMock, 1)).toBe('2')
  })

  it('reopens after a dropped connection', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const fetchMock = stubStream([
      sse([started(1), delta(2, 'a')]),
      new Error('network down'),
      sse([delta(3, 'b'), finished(4)]),
    ])
    const seen: number[] = []

    const outcome = await streamRun('r1', {
      signal: new AbortController().signal,
      onEvent: (event) => seen.push(event.sequence),
      sleep: noSleep,
    })

    expect(outcome).toBe('finished')
    expect(seen).toEqual([1, 2, 3, 4])
    expect(lastEventId(fetchMock, 2)).toBe('2')
  })

  it('gives up after consecutive failures with no progress', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const fetchMock = stubStream([
      new Error('down'),
      new Error('down'),
      new Error('down'),
      new Error('down'),
    ])
    const onEvent = vi.fn()

    const outcome = await streamRun('r1', {
      signal: new AbortController().signal,
      onEvent,
      sleep: noSleep,
      maxFailures: 3,
    })

    expect(outcome).toBe('lost')
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(onEvent).not.toHaveBeenCalled()
  })

  it('does not count empty clean closes at the server lifetime as failures', async () => {
    // A run can think for longer than the server keeps one stream open: each close is clean and
    // brings nothing, and the stream must keep following, not be reported lost.
    const fetchMock = stubStream([
      sse([]),
      sse([]),
      sse([]),
      sse([]),
      sse([]),
      sse([started(1), finished(2)]),
    ])
    const seen: number[] = []

    const outcome = await streamRun('r1', {
      signal: new AbortController().signal,
      onEvent: (event) => seen.push(event.sequence),
      sleep: noSleep,
      maxFailures: 2,
    })

    expect(outcome).toBe('finished')
    expect(seen).toEqual([1, 2])
    expect(fetchMock).toHaveBeenCalledTimes(6)
  })

  it('counts a rate-limited reopen as a failure and gives up', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const limited = () =>
      Response.json({ error: { code: 'rate_limited', message: 'x' } }, { status: 429 })
    const fetchMock = stubStream([limited(), limited(), limited(), limited()])

    const outcome = await streamRun('r1', {
      signal: new AbortController().signal,
      onEvent: () => undefined,
      sleep: noSleep,
      maxFailures: 3,
    })

    expect(outcome).toBe('lost')
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('gives up when clean closes alternate with failures that bring nothing', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const fetchMock = stubStream([new Error('down'), sse([]), new Error('down'), new Error('down')])

    const outcome = await streamRun('r1', {
      signal: new AbortController().signal,
      onEvent: () => undefined,
      sleep: noSleep,
      maxFailures: 2,
    })

    expect(outcome).toBe('lost')
    expect(fetchMock).toHaveBeenCalledTimes(4)
  })

  it('resets the failure count whenever a connection makes progress', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    stubStream([
      new Error('down'),
      sse([started(1)]),
      new Error('down'),
      sse([delta(2, 'a')]),
      new Error('down'),
      sse([finished(3)]),
    ])

    const outcome = await streamRun('r1', {
      signal: new AbortController().signal,
      onEvent: () => undefined,
      sleep: noSleep,
      maxFailures: 2,
    })

    expect(outcome).toBe('finished')
  })

  it('stops quietly when aborted', async () => {
    const controller = new AbortController()
    stubStream([sse([started(1)])])
    const onEvent = vi.fn(() => {
      controller.abort()
    })

    const outcome = await streamRun('r1', { signal: controller.signal, onEvent, sleep: noSleep })

    expect(outcome).toBe('aborted')
    expect(onEvent).toHaveBeenCalledTimes(1)
  })
})

describe('streamRun at an approval', () => {
  const asked: RunEvent = {
    type: 'approval_requested',
    sequence: 3,
    createdAt: at,
    approvalId: 'a1',
    toolUseId: 't1',
    argumentsDigest: 'a'.repeat(64),
  }
  const answered: RunEvent = {
    type: 'approval_decided',
    sequence: 4,
    createdAt: at,
    approvalId: 'a1',
    toolUseId: 't1',
    decision: 'approved',
  }

  it('reports paused on a clean close while an approval is undecided, and reopens nothing', async () => {
    const fetchMock = stubStream([sse([started(1), asked])])
    const sleep = vi.fn(noSleep)

    const outcome = await streamRun('r1', {
      signal: new AbortController().signal,
      onEvent: () => undefined,
      sleep,
    })

    expect(outcome).toBe('paused')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(sleep).not.toHaveBeenCalled()
  })

  it('goes on when the approval was decided before the close', async () => {
    stubStream([sse([started(1), asked, answered]), sse([finished(5)])])

    const outcome = await streamRun('r1', {
      signal: new AbortController().signal,
      onEvent: () => undefined,
      sleep: noSleep,
    })

    expect(outcome).toBe('finished')
  })

  it('still reopens after a dropped connection with an approval open', async () => {
    const fetchMock = stubStream([new Error('drop'), sse([asked])])
    vi.spyOn(console, 'error').mockImplementation(() => undefined)

    const outcome = await streamRun('r1', {
      signal: new AbortController().signal,
      onEvent: () => undefined,
      sleep: noSleep,
    })

    expect(outcome).toBe('paused')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
