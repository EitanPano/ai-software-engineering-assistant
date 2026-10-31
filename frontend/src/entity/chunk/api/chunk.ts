import { queryOptions } from '@tanstack/react-query'

import { call } from '@/shared/api/call'
import { getApiSearch } from '@/shared/api/generated'
import { getApiSearchQueryKey } from '@/shared/api/generated/@tanstack/react-query.gen'

// The best chunks of every ready source for a text. A search is a bounded top-k, not a list: no
// cursor, no `limit` (the contract's default of 10 holds).
export const searchKey = (q: string) => getApiSearchQueryKey({ query: { q } })

export const searchQuery = (q: string) =>
  queryOptions({
    queryKey: searchKey(q),
    queryFn: ({ signal }) => call(getApiSearch({ query: { q }, signal })),
  })
