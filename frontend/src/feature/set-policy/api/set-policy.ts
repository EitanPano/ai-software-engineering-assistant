import { useMutation, useQueryClient } from '@tanstack/react-query'

import { toolPolicyKey } from '@/entity/tool-policy/api/tool-policy'
import type { Effect } from '@/entity/tool-policy/model'
import { call } from '@/shared/api/call'
import { putApiToolPolicyByMcpServerIdByToolName } from '@/shared/api/generated'

import { SET_POLICY_COPY } from '../model'

// Sets one tool's effect; the next call uses it. The document is refetched on success or failure,
// so the select always shows the stored effect.
export function useSetPolicy(mcpServerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    // A click made offline fails with a toast instead of resuming by itself on reconnect.
    networkMode: 'always',
    mutationFn: (input: { toolName: string; effect: Effect }) =>
      call(
        putApiToolPolicyByMcpServerIdByToolName({
          path: { mcpServerId, toolName: input.toolName },
          body: { effect: input.effect },
        }),
        SET_POLICY_COPY,
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: toolPolicyKey(mcpServerId) }),
  })
}
