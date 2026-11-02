import { useMutation, useQueryClient } from '@tanstack/react-query'

import { memoryListKey } from '@/entity/memory/api/memory'
import { call } from '@/shared/api/call'
import { deleteApiMemoryById } from '@/shared/api/generated'

import { DELETE_MEMORY_COPY } from '../model'

// Deletes one memory; the list is read again so the row goes. A memory that is already gone
// (404) refreshes the list too, so the row does not linger.
export function useDeleteMemory(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    networkMode: 'always',
    mutationFn: () => call(deleteApiMemoryById({ path: { id } }), DELETE_MEMORY_COPY),
    onSettled: () => queryClient.invalidateQueries({ queryKey: memoryListKey() }),
  })
}
