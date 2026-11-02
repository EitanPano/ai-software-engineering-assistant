import { ListSkeleton } from '@/shared/ui/pattern/skeletons'

// The results' shape while a search runs: a few hit cards in the same column.
export function SearchResultSkeleton() {
  return (
    <div className="max-w-3xl" role="status" aria-label="Searching" aria-busy="true">
      <ListSkeleton rows={3} rowClassName="h-32" />
    </div>
  )
}
