import { CheckIcon } from 'lucide-react'
import { toast } from 'sonner'

import { ActionError } from '@/shared/lib/action-error'
import { Button } from '@/shared/ui/button'

import { useApprove } from '../api/approve'
import { APPROVE_COPY, type DecisionOutcome } from '../model'

// The filled button of a waiting tool call. `onStart` fires on the click so the row can turn the
// other decision off; `onDone` reports how it ended once the request settled. A failure is a toast
// after the await, in our words.
export function ApproveButton({
  approvalId,
  argumentsDigest,
  disabled = false,
  onStart,
  onDone,
}: {
  approvalId: string
  argumentsDigest: string
  disabled?: boolean
  onStart: () => void
  onDone: (outcome: DecisionOutcome) => void
}) {
  const approve = useApprove()

  async function onClick() {
    onStart()
    try {
      await approve.mutateAsync({ approvalId, argumentsDigest })
    } catch (error) {
      toast.error(error instanceof ActionError ? error.message : APPROVE_COPY.internal)
      onDone(error instanceof ActionError && error.code === 'conflict' ? 'stale' : 'failed')
      return
    }
    onDone('decided')
  }

  return (
    <Button
      disabled={disabled || approve.isPending}
      onClick={() => void onClick()}
      className="w-full sm:w-auto"
    >
      <CheckIcon aria-hidden />
      {approve.isPending ? 'Approving…' : 'Approve call'}
    </Button>
  )
}
