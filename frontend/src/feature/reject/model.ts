import type { ErrorCopy } from '@/shared/api/call'

// Our words for a failed rejection, keyed by the envelope's `code`. There is no reason to give: the
// agent is told a person rejected the call and the person says more in their next message.
export const REJECT_COPY: ErrorCopy & { conflict: string; internal: string } = {
  conflict: 'This call was already decided or has changed. The conversation is updating.',
  not_found: "This call isn't available any more.",
  unauthenticated: 'Your session has expired. Sign in again, then reject the call.',
  internal: "Couldn't reject the call. Try again.",
  upstream_unavailable: "Couldn't reject the call right now. Try again in a moment.",
}
