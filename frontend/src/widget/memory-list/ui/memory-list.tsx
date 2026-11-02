import { useSuspenseInfiniteQuery } from '@tanstack/react-query'
import { BrainIcon } from 'lucide-react'
import { Link } from 'react-router'

import { memoryListQuery } from '@/entity/memory/api/memory'
import { MemoryRow } from '@/entity/memory/ui/memory-row'
import { DeleteMemoryButton } from '@/feature/delete-memory/ui/delete-memory-button'
import { Button } from '@/shared/ui/button'
import { EmptyState } from '@/shared/ui/pattern/empty-state'
import { ErrorState } from '@/shared/ui/pattern/error-state'

// What the agent remembers about the caller, newest first, in a list-width column. Older ones
// load a page at a time behind "Show more"; a failed page keeps what is loaded and offers a retry.
export function MemoryList() {
  const { data, hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } =
    useSuspenseInfiniteQuery(memoryListQuery())
  const items = data.pages.flatMap((page) => page.items)

  if (items.length === 0) {
    return (
      <EmptyState
        icon={BrainIcon}
        title="Nothing remembered yet"
        description="Facts you state about yourself and your work appear here after a conversation."
        action={
          <Button asChild variant="outline">
            <Link to="/conversation">Go to conversations</Link>
          </Button>
        }
      />
    )
  }

  return (
    <div className="flex max-w-3xl flex-col gap-3">
      <ul className="flex flex-col gap-3">
        {items.map((memory) => (
          <li key={memory.id}>
            <MemoryRow memory={memory} action={<DeleteMemoryButton id={memory.id} />} />
          </li>
        ))}
      </ul>
      {isFetchNextPageError ? (
        <ErrorState
          title="Couldn't load more memories"
          description="Your other memories are still here. Try again."
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
