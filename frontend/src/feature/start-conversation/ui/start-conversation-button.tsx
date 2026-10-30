import { PlusIcon } from 'lucide-react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { ActionError } from '@/shared/lib/action-error'
import { Button } from '@/shared/ui/button'

import { useStartConversation } from '../api/start-conversation'

// The primary action of the conversation list: start one and open it. The outcome of a failure is
// a toast in our words; a success navigates, so it has none.
export function StartConversationButton() {
  const start = useStartConversation()
  const navigate = useNavigate()

  async function onClick() {
    try {
      const conversation = await start.mutateAsync()
      await navigate(`/conversation/${conversation.id}`)
    } catch (error) {
      toast.error(error instanceof ActionError ? error.message : 'Something went wrong. Try again.')
    }
  }

  return (
    <Button onClick={() => void onClick()} disabled={start.isPending}>
      <PlusIcon aria-hidden />
      {start.isPending ? 'Starting…' : 'Start conversation'}
    </Button>
  )
}
