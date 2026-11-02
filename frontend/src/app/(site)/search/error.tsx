import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useRouteError, useSearchParams } from 'react-router'

import { dropFailedSearch } from '@/entity/chunk/api/chunk'
import { ActionError } from '@/shared/lib/action-error'
import { ErrorState } from '@/shared/ui/pattern/error-state'

import SiteError, { useSiteRetry } from '../error'

// The ErrorBoundary of /search. The group's copy says the page could not be loaded and to refresh,
// which is false while a user is over the search limit, so that one code gets its own words and
// every other failure is the group's. Both replace the page and its form inside the shell. The
// code is all that is read: `call` exposes no `Retry-After`, and the limit is a minute long.
export default function SearchError() {
  const error = useRouteError()

  if (error instanceof ActionError && error.code === 'rate_limited') {
    return <SearchRateLimited error={error} />
  }
  return <SiteError />
}

function SearchRateLimited({ error }: { error: unknown }) {
  const retry = useSiteRetry()
  const queryClient = useQueryClient()
  const [params] = useSearchParams()
  // The text the page searched, read as `SearchPage` reads it, so it is the failed search's key.
  const q = (params.get('q') ?? '').trim()

  useEffect(() => {
    console.error('route failed', error)
  }, [error])

  // Leaving the wait (Back, the nav, another text) drops the failure it shows, so the same text
  // searched after the wait is asked, not answered from the failure. Only that failure: the retry
  // renders the page as it unmounts the wait, and a newer failure that has landed by then is the
  // retry's own and stays. StrictMode runs this once early; the failed query has no observer, so
  // it only drops it sooner, and the retry asks anew.
  useEffect(() => {
    return () => {
      dropFailedSearch(queryClient, q, error)
    }
  }, [queryClient, q, error])

  return (
    <ErrorState
      title="Too many searches"
      description="Wait about a minute, then try again."
      onRetry={retry}
    />
  )
}
