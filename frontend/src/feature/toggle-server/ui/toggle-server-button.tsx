import { PowerIcon } from 'lucide-react'
import { toast } from 'sonner'

import { ActionError } from '@/shared/lib/action-error'
import { Button } from '@/shared/ui/button'

import { useToggleServer } from '../api/toggle-server'
import { TOGGLE_COPY } from '../model'

// Outline: the page's filled action is the review. A failure is a toast after the await.
export function ToggleServerButton({ id, enabled }: { id: string; enabled: boolean }) {
  const toggle = useToggleServer(id)

  async function onClick() {
    try {
      await toggle.mutateAsync(!enabled)
    } catch (error) {
      toast.error(error instanceof ActionError ? error.message : TOGGLE_COPY.internal)
      return
    }
    toast.success(enabled ? 'Server disabled' : 'Server enabled')
  }

  return (
    <Button
      variant="outline"
      disabled={toggle.isPending}
      onClick={() => void onClick()}
      className="w-full sm:w-auto"
    >
      <PowerIcon aria-hidden />
      {enabled ? 'Disable server' : 'Enable server'}
    </Button>
  )
}
