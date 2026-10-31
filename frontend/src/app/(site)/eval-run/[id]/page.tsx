import { ArrowLeftIcon } from 'lucide-react'
import { Suspense } from 'react'
import { Link, useParams } from 'react-router'

import { Button } from '@/shared/ui/button'
import { Page, PageHeader } from '@/shared/ui/pattern/page-layout'
import { EvalRunDetailView } from '@/widget/eval-run-detail/ui/eval-run-detail'
import { EvalRunDetailSkeleton } from '@/widget/eval-run-detail/ui/eval-run-detail-skeleton'

// One eval run's record, behind `requireRole(…, 'admin')` (routes.tsx). Read only: no action on
// this page starts a run.
export default function EvalRunPage() {
  const { id = '' } = useParams()
  return (
    <Page>
      <title>Eval run · AI Software Engineering Assistant</title>
      <meta name="robots" content="noindex" />
      <PageHeader
        title="Eval run"
        actions={
          <Button asChild variant="outline">
            <Link to="/eval-run">
              <ArrowLeftIcon aria-hidden />
              All eval runs
            </Link>
          </Button>
        }
      />
      <Suspense fallback={<EvalRunDetailSkeleton />}>
        <EvalRunDetailView key={id} id={id} />
      </Suspense>
    </Page>
  )
}
