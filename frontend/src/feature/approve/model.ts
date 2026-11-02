import type { ErrorCopy } from '@/shared/api/call'

// How a decision ended, told to the row that holds the buttons. `stale` is a conflict: another tab,
// or the server, already settled this call, so the stream is reopened to catch up.
export type DecisionOutcome = 'decided' | 'stale' | 'failed'

// Our words for a failed approval, keyed by the envelope's `code`. A 409 covers a call already
// decided, arguments that changed since they were shown, and a run that no longer waits.
export const APPROVE_COPY: ErrorCopy & { conflict: string; internal: string } = {
  conflict: 'This call was already decided or has changed. The conversation is updating.',
  not_found: "This call isn't available any more.",
  unauthenticated: 'Your session has expired. Sign in again, then approve the call.',
  internal: "Couldn't approve the call. Try again.",
  upstream_unavailable: "Couldn't approve the call right now. Try again in a moment.",
}
