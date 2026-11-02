import { useEffect } from 'react'
import { useRouteError } from 'react-router'

import { ActionError } from '@/shared/lib/action-error'
import { ErrorState } from '@/shared/ui/pattern/error-state'

import SiteError, { useSiteRetry } from '@/app/(site)/error'

// The ErrorBoundary of the listing review. The group's copy says the page could not be loaded,
// which hides the two things an admin can act on: the server did not answer (a 503), and the
// listing cannot be accepted at all (a 409: knowledge, or a listing the rules refuse). Anything
// else is the group's.
export default function ListingError() {
  const error = useRouteError()

  if (
    error instanceof ActionError &&
    (error.code === 'upstream_unavailable' || error.code === 'conflict')
  ) {
    return <ListingUnavailable error={error} />
  }
  return <SiteError />
}

function ListingUnavailable({ error }: { error: ActionError }) {
  const retry = useSiteRetry()

  useEffect(() => {
    console.error('route failed', error)
  }, [error])

  if (error.code === 'conflict') {
    return (
      <ErrorState
        title="This listing can't be accepted"
        description="This server has no listing to accept, or its listing breaks a rule: no tools, a repeated or invalid tool name. Nothing was changed."
        onRetry={retry}
      />
    )
  }
  return (
    <ErrorState
      title="This server didn't answer"
      description="We couldn't read its listing, so there is nothing to review. Try again in a moment."
      onRetry={retry}
    />
  )
}
