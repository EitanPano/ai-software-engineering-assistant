import { ListSkeleton } from '@/shared/ui/pattern/skeletons'

// The list's shape while it loads: a few rows in the same column.
export function SourceListSkeleton() {
  return (
    <div className="max-w-3xl" role="status" aria-label="Loading repositories" aria-busy="true">
      <ListSkeleton rows={3} />
    </div>
  )
}
