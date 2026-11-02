import { useSuspenseInfiniteQuery } from '@tanstack/react-query'
import { GaugeIcon } from 'lucide-react'

import { evalRunListQuery } from '@/entity/eval-run/api/eval-run'
import { EvalRunRow } from '@/entity/eval-run/ui/eval-run-row'
import { Button } from '@/shared/ui/button'
import { EmptyState } from '@/shared/ui/pattern/empty-state'
import { ErrorState } from '@/shared/ui/pattern/error-state'

// The eval runs, newest first, in a list-width column. The page header carries the one primary
// action (start), so the empty state points at it. Rows refresh by themselves while one is going
// (the entity's query); a failed row says why and offers no re-run.
export function EvalRunList() {
  const { data, hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } =
    useSuspenseInfiniteQuery(evalRunListQuery())
  const items = data.pages.flatMap((page) => page.items)

  if (items.length === 0) {
    return (
      <EmptyState
        icon={GaugeIcon}
        title="No eval runs yet"
        description="Use Start eval run above to measure how well search finds the labelled cases."
      />
    )
  }

  return (
    <div className="flex max-w-3xl flex-col gap-3">
      <ul className="flex flex-col gap-3">
        {items.map((run) => (
          <li key={run.id}>
            <EvalRunRow run={run} />
          </li>
        ))}
      </ul>
      {isFetchNextPageError ? (
        <ErrorState
          title="Couldn't load more eval runs"
          description="Your other runs are still here. Try again."
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
