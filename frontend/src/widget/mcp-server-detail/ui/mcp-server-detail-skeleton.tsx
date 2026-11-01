import { CardSkeleton } from '@/shared/ui/pattern/skeletons'

// The two sections of the page: the server's status, then its tools.
export function McpServerDetailSkeleton() {
  return (
    <div
      className="flex max-w-3xl flex-col gap-6"
      role="status"
      aria-label="Loading MCP server"
      aria-busy="true"
    >
      <CardSkeleton />
      <CardSkeleton />
    </div>
  )
}
