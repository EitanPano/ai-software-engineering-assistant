import { z } from 'zod'

import '@/shared/lib/zod-messages'
import type { SentMessage } from '@/shared/api'
import { zSendMessageBody } from '@/shared/api/generated/zod.gen'

export type { SentMessage }

// The form schema runs the contract's limits (1 to 32000 characters) on the trimmed text and
// words the empty case itself; the limits are never copied.
export const sendMessageSchema = zSendMessageBody.extend({
  content: z.string().trim().min(1, 'Enter a message').pipe(zSendMessageBody.shape.content),
})

export type SendMessageInput = z.input<typeof sendMessageSchema>

// Copy for each outcome, keyed by the envelope's `code` (shared/api/call.ts has the defaults).
// `conflict` is a send while the agent is still writing or waits for a decision on a tool call;
// `rate_limited` is the per-user limit.
export const SEND_MESSAGE_COPY = {
  conflict:
    'The agent is still writing or waiting for your decision on a tool call. Decide it or wait for the answer, then send again.',
  rate_limited: "You're sending messages too quickly. Wait a few minutes and try again.",
  not_found: "This conversation isn't available any more.",
  internal: "Couldn't send your message. Try again.",
  upstream_unavailable: "Couldn't send your message right now. Try again in a moment.",
}
