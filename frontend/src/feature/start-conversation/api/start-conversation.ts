import { useMutation, useQueryClient } from '@tanstack/react-query'

import { conversationListKey } from '@/entity/conversation/api/conversation'
import { call } from '@/shared/api/call'
import { postApiConversation } from '@/shared/api/generated'

import { START_CONVERSATION_COPY } from '../model'

// Creates an empty conversation; the list it joins is stale from now on.
export function useStartConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => call(postApiConversation(), START_CONVERSATION_COPY),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: conversationListKey() }),
  })
}
