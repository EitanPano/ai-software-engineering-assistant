import { getApiRunByIdEvent } from '@/shared/api/generated'
import type { RunEvent } from '@/shared/api'

export type StreamOutcome = 'finished' | 'lost' | 'aborted'

export type StreamOptions = {
  signal: AbortSignal
  onEvent: (event: RunEvent) => void
  // Consecutive connections that delivered nothing new before the stream is given up as lost.
  maxFailures?: number
  // Waits before a reopen; injected so a test does not sleep.
  sleep?: (ms: number) => Promise<void>
}

const MAX_FAILURES = 5
const BASE_DELAY_MS = 250
const MAX_DELAY_MS = 4000

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

// Follows one run's events until `run_finished`. The generated SSE client stops silently on a clean
// close and never resets its attempt count, so it is used for one connection at a time
// (`sseMaxRetryAttempts: 1`) and this loop owns reconnection: it reopens with `Last-Event-ID` set to
// the last sequence delivered, hands each event over once, and counts a connection that errored
// and brought nothing new as a failure (`lost` after `maxFailures` in a row). A clean close, which
// the server does at its stream lifetime, or a connection that made progress resets the count.
export async function streamRun(
  runId: string,
  { signal, onEvent, maxFailures = MAX_FAILURES, sleep = wait }: StreamOptions,
): Promise<StreamOutcome> {
  let lastSequence = -1
  let failures = 0
  // A function, so the checks below are not narrowed by the loop condition.
  const aborted = () => signal.aborted

  while (!aborted()) {
    let progressed = false
    // Set when the client reports an error (a non-2xx answer such as a 429, a drop mid-stream) or
    // the call throws. A clean close reports nothing: the server ends a stream at its maximum
    // lifetime, and a run can think for longer than that.
    let errored = false
    try {
      const { stream } = await getApiRunByIdEvent({
        path: { id: runId },
        ...(lastSequence >= 0 ? { headers: { 'Last-Event-ID': lastSequence } } : {}),
        signal,
        sseMaxRetryAttempts: 1,
        onSseError: (error) => {
          errored = true
          if (!aborted()) console.error('[api] run stream dropped', { cause: error })
        },
      })
      for await (const event of stream) {
        if (aborted()) return 'aborted'
        if (event.sequence <= lastSequence) continue
        lastSequence = event.sequence
        progressed = true
        onEvent(event)
        if (event.type === 'run_finished') return 'finished'
      }
    } catch (cause) {
      errored = true
      if (!aborted()) console.error('[api] run stream failed', { cause })
    }

    if (aborted()) break
    // Progress or a clean close shows the server is answering: the count restarts. Only a
    // connection that errored and brought nothing is a failure, so a stuck run still ends (its
    // reopens meet the stream's rate limit).
    failures = progressed || !errored ? 0 : failures + 1
    if (failures >= maxFailures) return 'lost'
    await sleep(Math.min(BASE_DELAY_MS * 2 ** Math.max(failures - 1, 0), MAX_DELAY_MS))
  }
  return 'aborted'
}
