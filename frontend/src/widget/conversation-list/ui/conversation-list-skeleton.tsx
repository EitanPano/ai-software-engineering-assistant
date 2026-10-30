import { ListSkeleton } from '@/shared/ui/pattern/skeletons'

// The list's shape while it loads: a few rows in the same column.
export function ConversationListSkeleton() {
  return (
    <div className="max-w-3xl" role="status" aria-label="Loading conversations" aria-busy="true">
      <ListSkeleton rows={4} />
    </div>
  )
}
