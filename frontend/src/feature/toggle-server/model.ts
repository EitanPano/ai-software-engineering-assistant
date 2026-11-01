import type { ErrorCopy } from '@/shared/api/call'

export const TOGGLE_COPY: ErrorCopy & { conflict: string; internal: string } = {
  conflict: 'Review and accept the listing first. Accepting enables the server.',
  not_found: "This server isn't available any more.",
  unauthenticated: 'Your session has expired. Sign in again, then try again.',
  internal: "Couldn't change the server. Try again.",
}
