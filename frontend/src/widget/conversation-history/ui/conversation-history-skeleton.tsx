import { ListSkeleton } from '@/shared/ui/pattern/skeletons'
import { Skeleton } from '@/shared/ui/skeleton'

// The history's shape while it loads: a couple of turns and the send box.
export function ConversationHistorySkeleton() {
  return (
    <div
      className="flex flex-col gap-6"
      role="status"
      aria-label="Loading conversation"
      aria-busy="true"
    >
      <div className="max-w-3xl">
        <ListSkeleton rows={2} />
      </div>
      <Skeleton className="h-24 w-full" />
    </div>
  )
}
