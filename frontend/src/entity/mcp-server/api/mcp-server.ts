import { infiniteQueryOptions, queryOptions } from '@tanstack/react-query'

import { call } from '@/shared/api/call'
import {
  getApiMcpServer,
  getApiMcpServerById,
  getApiMcpServerByIdListing,
} from '@/shared/api/generated'
import {
  getApiMcpServerByIdListingQueryKey,
  getApiMcpServerByIdQueryKey,
  getApiMcpServerQueryKey,
} from '@/shared/api/generated/@tanstack/react-query.gen'

export const mcpServerListKey = () => getApiMcpServerQueryKey()

export const mcpServerListQuery = () =>
  infiniteQueryOptions({
    queryKey: [...mcpServerListKey(), 'pages'],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      call(
        getApiMcpServer({ query: pageParam === undefined ? {} : { cursor: pageParam }, signal }),
      ),
    getNextPageParam: (last) => last.nextCursor ?? undefined,
  })

export const mcpServerKey = (id: string) => getApiMcpServerByIdQueryKey({ path: { id } })

export const mcpServerQuery = (id: string) =>
  queryOptions({
    queryKey: mcpServerKey(id),
    queryFn: ({ signal }) => call(getApiMcpServerById({ path: { id }, signal })),
  })

export const listingKey = (id: string) => getApiMcpServerByIdListingQueryKey({ path: { id } })

// The one read that calls the live server. It is never prefetched (only the review page reads it).
// It is read once per visit. A failed read marks the query invalidated, and that beats any
// `staleTime`, so `refetchOnMount`, `refetchOnWindowFocus` and `refetchOnReconnect` are all
// `false`: with them no automatic read starts (`staleTime: Infinity` stays; `'static'` would stop
// the 409's reload). Only the 409's invalidate reloads a page already open. `gcTime: 0` ends the
// entry once the page closes (a suspense query keeps it one second), then a reopen reads again.
export const listingQuery = (id: string) =>
  queryOptions({
    queryKey: listingKey(id),
    queryFn: ({ signal }) => call(getApiMcpServerByIdListing({ path: { id }, signal })),
    staleTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    gcTime: 0,
  })
