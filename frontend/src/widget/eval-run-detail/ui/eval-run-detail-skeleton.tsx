import { CardSkeleton, ListSkeleton } from '@/shared/ui/pattern/skeletons'

// The record's shape while it loads, and while a run is active: summary cards, then a table.
export function EvalRunDetailSkeleton({ label = 'Loading eval run' }: { label?: string }) {
  return (
    <div className="flex flex-col gap-6" role="status" aria-label={label} aria-busy="true">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {Array.from({ length: 5 }, (_, index) => (
          <CardSkeleton key={index} />
        ))}
      </div>
      <ListSkeleton rows={4} />
    </div>
  )
}
