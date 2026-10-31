import { infiniteQueryOptions } from '@tanstack/react-query'

import { call } from '@/shared/api/call'
import { getApiSource } from '@/shared/api/generated'
import { getApiSourceQueryKey } from '@/shared/api/generated/@tanstack/react-query.gen'

import { refreshInterval } from '../model'

// The connected sources, newest first, page by page. The key extends the generated list key, so
// invalidating `sourceListKey()` (a connect, a retry) refetches every loaded page. While a loaded
// row is queued or indexing the list refetches itself every 3 s; it stops when none is.
export const sourceListKey = () => getApiSourceQueryKey()

export const sourceListQuery = () =>
  infiniteQueryOptions({
    queryKey: [...sourceListKey(), 'pages'],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      call(getApiSource({ query: pageParam === undefined ? {} : { cursor: pageParam }, signal })),
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    refetchInterval: (query) => refreshInterval(query.state.data),
  })
