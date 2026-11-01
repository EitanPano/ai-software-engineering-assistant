import { useMutation } from '@tanstack/react-query'

import { call } from '@/shared/api/call'
import { postApiApprovalByIdDecision } from '@/shared/api/generated'

import { REJECT_COPY } from '../model'

// Rejects one tool call: the agent gets a denied result and the run goes on. Sent by a click only,
// as `useApprove` is (`retry: false`, `networkMode: 'always'`), with the digest it was shown.
export function useReject() {
  return useMutation({
    retry: false,
    networkMode: 'always',
    mutationFn: (input: { approvalId: string; argumentsDigest: string }) =>
      call(
        postApiApprovalByIdDecision({
          path: { id: input.approvalId },
          body: { decision: 'rejected', argumentsDigest: input.argumentsDigest },
        }),
        REJECT_COPY,
      ),
  })
}
