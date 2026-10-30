import { infiniteQueryOptions, queryOptions } from '@tanstack/react-query'

import { call } from '@/shared/api/call'
import { getApiConversation, getApiConversationById } from '@/shared/api/generated'
import {
  getApiConversationByIdOptions,
  getApiConversationByIdQueryKey,
  getApiConversationQueryKey,
} from '@/shared/api/generated/@tanstack/react-query.gen'

// The caller's conversations, latest activity first, read page by page: each page's `nextCursor`
// is the next page's `cursor`. The key extends the generated list key, so invalidating
// `conversationListKey()` (a start, a send) refetches every loaded page.
export const conversationListKey = () => getApiConversationQueryKey()

export const conversationListQuery = () =>
  infiniteQueryOptions({
    queryKey: [...conversationListKey(), 'pages'],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      call(
        getApiConversation({ query: pageParam === undefined ? {} : { cursor: pageParam }, signal }),
      ),
    getNextPageParam: (last) => last.nextCursor ?? undefined,
  })

// One conversation with its latest run, which the history follows on load.
export const conversationKey = (id: string) => getApiConversationByIdQueryKey({ path: { id } })

export const conversationQuery = (id: string) =>
  queryOptions({
    ...getApiConversationByIdOptions({ path: { id } }),
    queryFn: ({ signal }) => call(getApiConversationById({ path: { id }, signal })),
  })
