import { useSuspenseInfiniteQuery } from '@tanstack/react-query'
import { MessagesSquareIcon } from 'lucide-react'

import { conversationListQuery } from '@/entity/conversation/api/conversation'
import { ConversationRow } from '@/entity/conversation/ui/conversation-row'
import { Button } from '@/shared/ui/button'
import { EmptyState } from '@/shared/ui/pattern/empty-state'
import { ErrorState } from '@/shared/ui/pattern/error-state'

// The caller's conversations, latest activity first, in a list-width column. The page header
// carries the one primary action (start), so the empty state points at it instead of repeating it.
// Older ones load a page at a time behind "Show more"; a failed page keeps what is loaded and
// offers a retry.
export function ConversationList() {
  const { data, hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } =
    useSuspenseInfiniteQuery(conversationListQuery())
  const items = data.pages.flatMap((page) => page.items)

  if (items.length === 0) {
    return (
      <EmptyState
        icon={MessagesSquareIcon}
        title="No conversations yet"
        description="Start a conversation to ask the agent about your code."
      />
    )
  }

  return (
    <div className="flex max-w-3xl flex-col gap-3">
      <ul className="flex flex-col gap-3">
        {items.map((conversation) => (
          <li key={conversation.id}>
            <ConversationRow conversation={conversation} />
          </li>
        ))}
      </ul>
      {isFetchNextPageError ? (
        <ErrorState
          title="Couldn't load more conversations"
          description="Your other conversations are still here. Try again."
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
