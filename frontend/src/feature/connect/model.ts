import { z } from 'zod'

import '@/shared/lib/zod-messages'
import { zPostApiSourceBody } from '@/shared/api/generated/zod.gen'

// The form schema extends the generated body, so the url and ref limits are the contract's. The
// `.git`, `.`, `..` and ref `..` rules exist only on the server: its 400 lands on the field with
// the copy below. The ref field is optional: an empty box sends no ref.
const URL_MESSAGE = 'Enter the repository as https://github.com/owner/repository'
const REF_MESSAGE =
  'Use a branch, tag or commit: letters, digits, dots, slashes, dashes or underscores'

const generatedUrl = zPostApiSourceBody.shape.url
const generatedRef = zPostApiSourceBody.shape.ref.unwrap()

export const connectSchema = zPostApiSourceBody.extend({
  url: z
    .string()
    .trim()
    .superRefine((value, ctx) => {
      if (!generatedUrl.safeParse(value).success)
        ctx.addIssue({ code: 'custom', message: URL_MESSAGE })
    }),
  ref: z
    .string()
    .trim()
    .superRefine((value, ctx) => {
      if (value !== '' && !generatedRef.safeParse(value).success) {
        ctx.addIssue({ code: 'custom', message: REF_MESSAGE })
      }
    }),
})

export type ConnectInput = z.input<typeof connectSchema>

// The request body: no `ref` key when the box is empty (the API rejects an empty string).
export function toConnectBody(values: ConnectInput): { url: string; ref?: string } {
  const url = values.url.trim()
  const ref = values.ref.trim()
  return ref === '' ? { url } : { url, ref }
}

// Copy for each outcome, keyed by the envelope's `code` (shared/api/call.ts has the defaults).
// `not_found` and `conflict` belong to the url field; GitHub being down is a toast.
export const CONNECT_COPY = {
  not_found: "We couldn't find a public repository at that address, or that branch, tag or commit.",
  conflict: 'That repository is already connected at that branch, tag or commit.',
  upstream_unavailable: "GitHub isn't reachable right now. Try again in a moment.",
  internal: "Couldn't connect the repository. Try again.",
  'validation_failed:url': URL_MESSAGE,
  'validation_failed:ref': REF_MESSAGE,
}

export const RETRY_COPY = {
  conflict: "That source can't be retried: it isn't failed any more.",
  not_found: "That source isn't available any more.",
  internal: "Couldn't retry indexing. Try again.",
}
