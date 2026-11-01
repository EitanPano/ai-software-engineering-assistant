import type { ErrorCopy } from '@/shared/api/call'

export const SET_POLICY_COPY: ErrorCopy & { internal: string } = {
  validation_failed: "That tool can't be set to that. Pick one of the other options.",
  not_found: "This tool isn't available any more.",
  unauthenticated: 'Your session has expired. Sign in again, then set the policy.',
  internal: "Couldn't set the policy. Try again.",
}
