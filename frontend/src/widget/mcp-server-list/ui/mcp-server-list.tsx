import { useSuspenseInfiniteQuery } from '@tanstack/react-query'
import { ServerIcon } from 'lucide-react'

import { mcpServerListQuery } from '@/entity/mcp-server/api/mcp-server'
import { McpServerRow } from '@/entity/mcp-server/ui/mcp-server-row'
import { Button } from '@/shared/ui/button'
import { EmptyState } from '@/shared/ui/pattern/empty-state'
import { ErrorState } from '@/shared/ui/pattern/error-state'

// The MCP servers, newest first, in a list-width column. The read calls no server: the pin status
// is the stored listing against the pin.
export function McpServerList() {
  const { data, hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } =
    useSuspenseInfiniteQuery(mcpServerListQuery())
  const items = data.pages.flatMap((page) => page.items)

  if (items.length === 0) {
    return (
      <EmptyState
        icon={ServerIcon}
        title="No MCP servers"
        description="The servers the agent can use appear here once the app has registered them."
      />
    )
  }

  return (
    <div className="flex max-w-3xl flex-col gap-3">
      <ul className="flex flex-col gap-3">
        {items.map((server) => (
          <li key={server.id}>
            <McpServerRow server={server} />
          </li>
        ))}
      </ul>
      {isFetchNextPageError ? (
        <ErrorState
          title="Couldn't load more servers"
          description="Your other servers are still here. Try again."
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
