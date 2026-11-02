import { XIcon } from 'lucide-react'
import { toast } from 'sonner'

import { ActionError } from '@/shared/lib/action-error'
import { Button } from '@/shared/ui/button'

import { useReject } from '../api/reject'
import { REJECT_COPY } from '../model'

// What the decision buttons report to their row; the same words as the approve feature's, kept
// local because a feature never imports a sibling.
type Outcome = 'decided' | 'stale' | 'failed'

// The outline button of a waiting tool call, beside the filled approve.
export function RejectButton({
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
  onDone: (outcome: Outcome) => void
}) {
  const reject = useReject()

  async function onClick() {
    onStart()
    try {
      await reject.mutateAsync({ approvalId, argumentsDigest })
    } catch (error) {
      toast.error(error instanceof ActionError ? error.message : REJECT_COPY.internal)
      onDone(error instanceof ActionError && error.code === 'conflict' ? 'stale' : 'failed')
      return
    }
    onDone('decided')
  }

  return (
    <Button
      variant="outline"
      disabled={disabled || reject.isPending}
      onClick={() => void onClick()}
      className="w-full sm:w-auto"
    >
      <XIcon aria-hidden />
      {reject.isPending ? 'Rejecting…' : 'Reject call'}
    </Button>
  )
}
