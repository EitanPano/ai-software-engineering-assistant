import type { ErrorCopy } from '@/shared/api/call'

// Our words for a failed accept, keyed by the envelope's `code`. A 409 is a listing that changed
// since it was shown (or one that cannot be accepted); the page reloads the listing it reads.
export const ACCEPT_COPY: ErrorCopy & { conflict: string; internal: string } = {
  conflict: 'The listing changed since you read it. Review the new listing before accepting.',
  not_found: "This server isn't available any more.",
  unauthenticated: 'Your session has expired. Sign in again, then accept the listing.',
  internal: "Couldn't accept the listing. Try again.",
  upstream_unavailable: "The server didn't answer, so nothing was accepted. Try again in a moment.",
}
