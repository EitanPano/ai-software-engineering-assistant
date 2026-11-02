import { ListSkeleton } from '@/shared/ui/pattern/skeletons'

// The list's shape while it loads: a few two-line rows in the same column.
export function EvalRunListSkeleton() {
  return (
    <div className="max-w-3xl" role="status" aria-label="Loading eval runs" aria-busy="true">
      <ListSkeleton rows={3} rowClassName="h-20" />
    </div>
  )
}
