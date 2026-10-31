import type { ErrorCopy } from '@/shared/api/call'

// The words of a failed start, keyed by the envelope's `code`; anything else takes the default
// copy. A 409 means a run is active (one at a time), which is a wait, not a fault.
export const MEASURE_COPY: ErrorCopy = {
  conflict: 'An eval run is already in progress. Wait for it to finish, then start another.',
  forbidden: 'Only an admin can start an eval run.',
  unauthenticated: 'Your session has expired. Sign in again, then start the run.',
}
