import { Trash2Icon } from 'lucide-react'
import { toast } from 'sonner'

import { ActionError } from '@/shared/lib/action-error'
import { Button } from '@/shared/ui/button'
import { ConfirmDialog } from '@/shared/ui/pattern/confirm-dialog'

import { useDeleteMemory } from '../api/delete-memory'
import { DELETE_BODY, DELETE_MEMORY_COPY, DELETE_TITLE } from '../model'

// A ghost button: the page has no filled action. The outcome is a toast after the await; a failed
// delete rethrows so the dialog stays open and the row stays.
export function DeleteMemoryButton({ id }: { id: string }) {
  const remove = useDeleteMemory(id)

  async function onConfirm() {
    try {
      await remove.mutateAsync()
    } catch (error) {
      toast.error(error instanceof ActionError ? error.message : DELETE_MEMORY_COPY.internal)
      throw error
    }
    toast.success('Memory deleted')
  }

  return (
    <ConfirmDialog
      trigger={
        <Button variant="ghost" className="-ml-3 self-start sm:ml-0" aria-label="Delete memory">
          <Trash2Icon aria-hidden />
          Delete
        </Button>
      }
      title={DELETE_TITLE}
      description={DELETE_BODY}
      confirmLabel="Delete memory"
      destructive
      onConfirm={onConfirm}
    />
  )
}
