import { CardSkeleton } from '@/shared/ui/pattern/skeletons'

// The tools' cards while the live server is asked.
export function ListingReviewSkeleton() {
  return (
    <div
      className="flex max-w-3xl flex-col gap-6"
      role="status"
      aria-label="Reading the server's listing"
      aria-busy="true"
    >
      <CardSkeleton />
      <CardSkeleton />
    </div>
  )
}
