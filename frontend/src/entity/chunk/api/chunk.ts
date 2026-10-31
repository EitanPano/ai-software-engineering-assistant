import { queryOptions, type QueryClient } from '@tanstack/react-query'

import { call } from '@/shared/api/call'
import { getApiSearch } from '@/shared/api/generated'
import { getApiSearchQueryKey } from '@/shared/api/generated/@tanstack/react-query.gen'

// The best chunks of every ready source for a text. A search is a bounded top-k, not a list: no
// cursor, no `limit` (the contract's default of 10 holds).
export const searchKey = (q: string) => getApiSearchQueryKey({ query: { q } })

// A search embeds its text and counts against the user's limit (5 a minute), so a kept result is
// never asked again by itself: with `staleTime: Infinity` a return to the tab, a dropped
// connection and Back to an earlier text send nothing, where the client's 30 s would send one
// each. A result stays until a reload or the 5 minutes it may sit off screen; a search refused by
// the limit is dropped by `dropFailedSearch` and reset by the route boundary's retry.
export const searchQuery = (q: string) =>
  queryOptions({
    queryKey: searchKey(q),
    queryFn: ({ signal }) => call(getApiSearch({ query: { q }, signal })),
    staleTime: Infinity,
  })

// A suspense query that failed is not asked again when its page remounts, so a search refused by
// the limit would answer the same text with the wait until the cache forgot it (5 minutes), however
// long the user waited. The wait state calls this as it unmounts, with the error it shows (a
// suspense query throws `query.state.error` itself, so the object is the same). Only that failure
// goes: a kept result stays, and so does what the retry has started (pending) or has just been
// refused with (a newer error), which a wait that unmounts as the retry renders must not delete.
export function dropFailedSearch(queryClient: QueryClient, q: string, error: unknown) {
  queryClient.removeQueries({
    queryKey: searchKey(q),
    predicate: (query) => query.state.error === error,
  })
}
