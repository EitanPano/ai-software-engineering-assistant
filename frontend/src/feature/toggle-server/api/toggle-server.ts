import { useMutation, useQueryClient } from '@tanstack/react-query'

import { mcpServerKey, mcpServerListKey } from '@/entity/mcp-server/api/mcp-server'
import { call } from '@/shared/api/call'
import { patchApiMcpServerById } from '@/shared/api/generated'

import { TOGGLE_COPY } from '../model'

// Turns a server on or off. The loop reads the row at each call, so it takes effect at once.
export function useToggleServer(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    // A click made offline fails with a toast instead of resuming by itself on reconnect.
    networkMode: 'always',
    mutationFn: (enabled: boolean) =>
      call(patchApiMcpServerById({ path: { id }, body: { enabled } }), TOGGLE_COPY),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: mcpServerKey(id) })
      void queryClient.invalidateQueries({ queryKey: mcpServerListKey() })
    },
  })
}
