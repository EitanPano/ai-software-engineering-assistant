import { CheckIcon } from 'lucide-react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { ActionError } from '@/shared/lib/action-error'
import { Button } from '@/shared/ui/button'

import { useAccept } from '../api/accept'
import { ACCEPT_COPY } from '../model'

// The filled button of the review. It sends the digest of the listing on screen; on success it
// goes to the server's page, on a stale digest it toasts and the page reloads the listing.
export function AcceptButton({
  serverId,
  listingDigest,
}: {
  serverId: string
  listingDigest: string
}) {
  const accept = useAccept(serverId)
  const navigate = useNavigate()

  async function onClick() {
    try {
      await accept.mutateAsync(listingDigest)
    } catch (error) {
      toast.error(error instanceof ActionError ? error.message : ACCEPT_COPY.internal)
      return
    }
    toast.success('Listing accepted')
    await navigate(`/mcp-server/${serverId}`)
  }

  return (
    <Button disabled={accept.isPending} onClick={() => void onClick()} className="w-full sm:w-auto">
      <CheckIcon aria-hidden />
      {accept.isPending ? 'Accepting…' : 'Accept listing'}
    </Button>
  )
}
