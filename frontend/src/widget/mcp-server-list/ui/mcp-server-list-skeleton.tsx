import { ListSkeleton } from '@/shared/ui/pattern/skeletons'

// Two rows in the list's column.
export function McpServerListSkeleton() {
  return (
    <div className="max-w-3xl" role="status" aria-label="Loading MCP servers" aria-busy="true">
      <ListSkeleton rows={2} rowClassName="h-20" />
    </div>
  )
}
