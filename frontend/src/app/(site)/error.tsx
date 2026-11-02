import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useLocation, useNavigate, useRouteError } from 'react-router'

import { ErrorState } from '@/shared/ui/pattern/error-state'

// The group's retry, shared with a segment boundary that has its own words. It resets the queries
// in the error state (a suspense query that failed is not asked again on remount) and leaves a
// result the user holds alone: a retry asks again for what failed, never for what the user has.
// Then it navigates to the same path and query, which re-runs the route's loaders and hands the
// boundary a new location, what clears it. The hash is left out: the router reads a navigation
// between two equal hashes as a hash change and runs no loader, so a retry on `/#main` (the skip
// link makes it) would do nothing. A retry loses the fragment, which has done its job by then. A
// revalidation alone clears the boundary only if it outlasts a render, and with the session read
// cached it does not.
export function useSiteRetry() {
  const navigate = useNavigate()
  const { pathname, search } = useLocation()
  const queryClient = useQueryClient()
  return () => {
    void queryClient.resetQueries({ predicate: (query) => query.state.status === 'error' })
    void navigate({ pathname, search }, { replace: true })
  }
}

// The ErrorBoundary of every route in the group, rendered inside the shell. The message is
// user-safe; the cause goes to the console.
export default function SiteError() {
  const error = useRouteError()
  const retry = useSiteRetry()

  useEffect(() => {
    console.error('route failed', error)
  }, [error])

  return (
    <ErrorState
      title="Something went wrong"
      description="The page could not be loaded. Try again, or refresh if the problem persists."
      onRetry={retry}
    />
  )
}
