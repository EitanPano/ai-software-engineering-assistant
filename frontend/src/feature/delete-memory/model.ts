import type { ErrorCopy } from '@/shared/api/call'

export const DELETE_MEMORY_COPY: ErrorCopy & { internal: string } = {
  not_found: "This memory isn't there any more.",
  unauthenticated: 'Your session has expired. Sign in again, then try again.',
  internal: "Couldn't delete the memory. Try again.",
}

export const DELETE_TITLE = 'Delete this memory?'

// Said on every delete, whether or not a conversation read it: recall stops at once, and a
// conversation that already read it keeps what it read.
export const DELETE_BODY =
  'No conversation will recall it from now on. A conversation that already read it keeps it, and so does the message you wrote it in.'
