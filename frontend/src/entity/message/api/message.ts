import { queryOptions } from '@tanstack/react-query'

import { call } from '@/shared/api/call'
import { getApiConversationByIdMessage } from '@/shared/api/generated'
import {
  getApiConversationByIdMessageOptions,
  getApiConversationByIdMessageQueryKey,
} from '@/shared/api/generated/@tanstack/react-query.gen'

// A conversation's newest messages (the first page; earlier ones are a later task).
export const messageListKey = (conversationId: string) =>
  getApiConversationByIdMessageQueryKey({ path: { id: conversationId } })

export const messageListQuery = (conversationId: string) =>
  queryOptions({
    ...getApiConversationByIdMessageOptions({ path: { id: conversationId } }),
    queryFn: ({ signal }) =>
      call(getApiConversationByIdMessage({ path: { id: conversationId }, signal })),
  })
