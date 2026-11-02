import { infiniteQueryOptions, queryOptions } from '@tanstack/react-query'

import { call } from '@/shared/api/call'
import { getApiEvalRun, getApiEvalRunById } from '@/shared/api/generated'
import {
  getApiEvalRunByIdQueryKey,
  getApiEvalRunQueryKey,
} from '@/shared/api/generated/@tanstack/react-query.gen'

import { listRefreshInterval, runRefreshInterval } from '../model'

// Every read here is free, so the client's 30 s default stands (no `staleTime` override). Nothing
// here sends a start; the start is a click (`feature/measure`).
//
// The key extends the generated list key, so invalidating `evalRunListKey()` (a start) refetches
// every loaded page. While a loaded run is queued or running the list refetches itself every 3 s.
export const evalRunListKey = () => getApiEvalRunQueryKey()

export const evalRunListQuery = () =>
  infiniteQueryOptions({
    queryKey: [...evalRunListKey(), 'pages'],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      call(getApiEvalRun({ query: pageParam === undefined ? {} : { cursor: pageParam }, signal })),
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    refetchInterval: (query) => listRefreshInterval(query.state.data),
  })

export const evalRunKey = (id: string) => getApiEvalRunByIdQueryKey({ path: { id } })

export const evalRunQuery = (id: string) =>
  queryOptions({
    queryKey: evalRunKey(id),
    queryFn: ({ signal }) => call(getApiEvalRunById({ path: { id }, signal })),
    refetchInterval: (query) => runRefreshInterval(query.state.data),
  })
