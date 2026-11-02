import { PlayIcon } from 'lucide-react'
import { toast } from 'sonner'

import { ActionError } from '@/shared/lib/action-error'
import { Button } from '@/shared/ui/button'

import { useStartEvalRun } from '../api/measure'

// The one primary action of the eval-run list. Only this click starts a run; the outcome is a toast
// shown after the await, and a success shows as the new row when the list refetches.
export function MeasureButton() {
  const start = useStartEvalRun()

  async function onClick() {
    try {
      await start.mutateAsync()
      toast.success('Eval run started')
    } catch (error) {
      toast.error(error instanceof ActionError ? error.message : 'Something went wrong. Try again.')
    }
  }

  return (
    <Button disabled={start.isPending} onClick={() => void onClick()}>
      <PlayIcon aria-hidden />
      {start.isPending ? 'Starting…' : 'Start eval run'}
    </Button>
  )
}
