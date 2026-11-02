import { infiniteQueryOptions } from '@tanstack/react-query'

import { call } from '@/shared/api/call'
import { getApiMemory } from '@/shared/api/generated'
import { getApiMemoryQueryKey } from '@/shared/api/generated/@tanstack/react-query.gen'

// The caller's memories, newest first, read page by page: each page's `nextCursor` is the next
// page's `cursor`. The key extends the generated list key, so invalidating `memoryListKey()` (a
// delete) refetches every loaded page.
export const memoryListKey = () => getApiMemoryQueryKey()

export const memoryListQuery = () =>
  infiniteQueryOptions({
    queryKey: [...memoryListKey(), 'pages'],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      call(getApiMemory({ query: pageParam === undefined ? {} : { cursor: pageParam }, signal })),
    getNextPageParam: (last) => last.nextCursor ?? undefined,
  })
