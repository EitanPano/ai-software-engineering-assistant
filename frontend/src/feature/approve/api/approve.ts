import { useMutation } from '@tanstack/react-query'

import { call } from '@/shared/api/call'
import { postApiApprovalByIdDecision } from '@/shared/api/generated'

import { APPROVE_COPY } from '../model'

// Approves one tool call, which then runs: a decision that acts and spends, so it is sent by a
// click and nothing else (`AGENTS.md › A paid start`): `retry: false`, and `networkMode: 'always'`
// so a click made offline fails at once instead of resuming on reconnect. The body echoes the
// digest of the arguments the person was shown, so the server binds the decision to them. Nothing
// is invalidated: the run's stream carries the outcome.
export function useApprove() {
  return useMutation({
    retry: false,
    networkMode: 'always',
    mutationFn: (input: { approvalId: string; argumentsDigest: string }) =>
      call(
        postApiApprovalByIdDecision({
          path: { id: input.approvalId },
          body: { decision: 'approved', argumentsDigest: input.argumentsDigest },
        }),
        APPROVE_COPY,
      ),
  })
}
