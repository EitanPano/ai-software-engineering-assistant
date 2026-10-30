import { useMutation, useQueryClient } from '@tanstack/react-query'

import { conversationKey, conversationListKey } from '@/entity/conversation/api/conversation'
import { messageListKey } from '@/entity/message/api/message'
import { call } from '@/shared/api/call'
import { postApiConversationByIdMessage } from '@/shared/api/generated'

import { SEND_MESSAGE_COPY, type SendMessageInput } from '../model'

// Sends one message, which starts a run. The history, the conversation (its latest run and title)
// and the list (its order) are stale from now on; the refetch runs beside the stream, so the
// caller is not held up by it.
export function useSendMessage(conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (values: SendMessageInput) =>
      call(
        postApiConversationByIdMessage({ path: { id: conversationId }, body: values }),
        SEND_MESSAGE_COPY,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: messageListKey(conversationId) })
      void queryClient.invalidateQueries({ queryKey: conversationKey(conversationId) })
      void queryClient.invalidateQueries({ queryKey: conversationListKey() })
    },
  })
}
