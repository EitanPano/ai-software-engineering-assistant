import { z } from 'zod'

import '@/shared/lib/zod-messages'
import { zGetApiSearchQuery } from '@/shared/api/generated/zod.gen'

// The contract's limit on the text, for copy that names it.
export const MAX_QUERY = zGetApiSearchQuery.shape.q.maxLength ?? 500

export const EMPTY_QUERY_MESSAGE = 'Enter an identifier or a few words to search for'

// The form schema extends the generated query, so the length limit is the contract's. The text is
// trimmed first, as the server does, and its empty case is worded here.
export const searchSchema = zGetApiSearchQuery.pick({ q: true }).extend({
  q: z.string().trim().min(1, EMPTY_QUERY_MESSAGE).pipe(zGetApiSearchQuery.shape.q),
})

export type SearchInput = z.input<typeof searchSchema>
