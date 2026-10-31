import { useSuspenseInfiniteQuery } from '@tanstack/react-query'
import { DatabaseIcon } from 'lucide-react'

import { sourceListQuery } from '@/entity/source/api/source'
import { SourceRow } from '@/entity/source/ui/source-row'
import { RetryIndexingButton } from '@/feature/connect/ui/retry-indexing-button'
import { Button } from '@/shared/ui/button'
import { EmptyState } from '@/shared/ui/pattern/empty-state'
import { ErrorState } from '@/shared/ui/pattern/error-state'

// The connected repositories, newest first, in a list-width column. The page header carries the
// one primary action (connect), so the empty state points at it. Rows refresh by themselves while
// one is being indexed (the entity's query); a failed row offers its retry.
export function SourceList() {
  const { data, hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } =
    useSuspenseInfiniteQuery(sourceListQuery())
  const items = data.pages.flatMap((page) => page.items)

  if (items.length === 0) {
    return (
      <EmptyState
        icon={DatabaseIcon}
        title="No repositories connected"
        description="Use Connect repository above to add a public GitHub repository to the knowledge base."
      />
    )
  }

  return (
    <div className="flex max-w-3xl flex-col gap-3">
      <ul className="flex flex-col gap-3">
        {items.map((source) => (
          <li key={source.id}>
            <SourceRow
              source={source}
              action={source.status === 'failed' ? <RetryIndexingButton source={source} /> : null}
            />
          </li>
        ))}
      </ul>
      {isFetchNextPageError ? (
        <ErrorState
          title="Couldn't load more repositories"
          description="Your other repositories are still here. Try again."
          onRetry={() => void fetchNextPage()}
        />
      ) : hasNextPage ? (
        <Button
          variant="outline"
          className="self-center"
          disabled={isFetchingNextPage}
          onClick={() => void fetchNextPage()}
        >
          {isFetchingNextPage ? 'Loading…' : 'Show more'}
        </Button>
      ) : null}
    </div>
  )
}
