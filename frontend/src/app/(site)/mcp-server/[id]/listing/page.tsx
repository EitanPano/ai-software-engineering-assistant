import { ArrowLeftIcon } from 'lucide-react'
import { Suspense } from 'react'
import { Link, useParams } from 'react-router'

import { Button } from '@/shared/ui/button'
import { Page, PageHeader } from '@/shared/ui/pattern/page-layout'
import { ListingReview } from '@/widget/listing-review/ui/listing-review'
import { ListingReviewSkeleton } from '@/widget/listing-review/ui/listing-review-skeleton'

// The review of a server's live listing, behind `requireRole(…, 'admin')` (routes.tsx). Its loader
// prefetches nothing: this is the one page that calls a live server, and only when it opens.
export default function ListingPage() {
  const { id = '' } = useParams()
  return (
    <Page>
      <title>Review listing · AI Software Engineering Assistant</title>
      <meta name="robots" content="noindex" />
      <PageHeader
        title="Review listing"
        description="Read every definition below. The model reads exactly this text."
        actions={
          <Button asChild variant="outline">
            <Link to={`/mcp-server/${id}`}>
              <ArrowLeftIcon aria-hidden />
              Back to server
            </Link>
          </Button>
        }
      />
      <Suspense fallback={<ListingReviewSkeleton />}>
        <ListingReview key={id} id={id} />
      </Suspense>
    </Page>
  )
}
