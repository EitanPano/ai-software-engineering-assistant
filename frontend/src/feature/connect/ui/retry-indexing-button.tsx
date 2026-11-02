import { RotateCcwIcon } from 'lucide-react'
import { toast } from 'sonner'

import { repositoryName, type Source } from '@/entity/source/model'
import { ActionError } from '@/shared/lib/action-error'
import { Button } from '@/shared/ui/button'

import { useRetryIndexing } from '../api/connect'

// The action of a failed row. The outcome of a failure is a toast in our words; a success shows
// as the row turning `Queued` when the list refetches.
export function RetryIndexingButton({ source }: { source: Source }) {
  const retry = useRetryIndexing()

  async function onClick() {
    try {
      await retry.mutateAsync(source.id)
    } catch (error) {
      toast.error(error instanceof ActionError ? error.message : 'Something went wrong. Try again.')
    }
  }

  return (
    <Button
      variant="outline"
      size="sm"
      disabled={retry.isPending}
      aria-label={`Retry indexing ${repositoryName(source.url)}`}
      onClick={() => void onClick()}
    >
      <RotateCcwIcon aria-hidden />
      {retry.isPending ? 'Retrying…' : 'Retry'}
    </Button>
  )
}
