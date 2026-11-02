import { useMutation, useQueryClient } from '@tanstack/react-query'

import { listingKey, mcpServerKey, mcpServerListKey } from '@/entity/mcp-server/api/mcp-server'
import { toolPolicyKey } from '@/entity/tool-policy/api/tool-policy'
import { call } from '@/shared/api/call'
import { postApiMcpServerByIdAcceptance } from '@/shared/api/generated'
import { ActionError } from '@/shared/lib/action-error'

import { ACCEPT_COPY } from '../model'

// Pins what the admin was shown, which also enables the server: a decision that changes what the
// model reads, so it is sent by a click and nothing else (`AGENTS.md › A paid start`, as
// `feature/approve`): `retry: false`, and `networkMode: 'always'` so a click made offline fails
// instead of resuming on reconnect. The body is the listing's digest and nothing else; the browser
// never sends a definition.
export function useAccept(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    retry: false,
    networkMode: 'always',
    mutationFn: (listingDigest: string) =>
      call(postApiMcpServerByIdAcceptance({ path: { id }, body: { listingDigest } }), ACCEPT_COPY),
    onSettled: (_data, error) => {
      // Only a 409 means the listing moved: read it again, so the page shows what an accept would
      // now pin. Any other failure keeps the text and digest the admin read, so a retry binds to
      // them; a hostile server cannot swap them between a failed accept and the click after it.
      if (error instanceof ActionError && error.code === 'conflict') {
        void queryClient.invalidateQueries({ queryKey: listingKey(id) })
      } else if (!error) {
        void queryClient.invalidateQueries({ queryKey: mcpServerKey(id) })
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: mcpServerListKey() })
      void queryClient.invalidateQueries({ queryKey: toolPolicyKey(id) })
    },
  })
}
