import { Suspense } from 'react'

import { MeasureButton } from '@/feature/measure/ui/measure-button'
import { Page, PageHeader } from '@/shared/ui/pattern/page-layout'
import { EvalRunList } from '@/widget/eval-run-list/ui/eval-run-list'
import { EvalRunListSkeleton } from '@/widget/eval-run-list/ui/eval-run-list-skeleton'

// The eval runs, behind `requireRole(…, 'admin')` (routes.tsx). Starting one is the page's one
// primary action, and the only thing that sends a start.
export default function EvalRunListPage() {
  return (
    <Page>
      <title>Eval runs · AI Software Engineering Assistant</title>
      <meta name="robots" content="noindex" />
      <PageHeader
        title="Eval runs"
        description="Measure how well search finds the labelled cases."
        actions={<MeasureButton />}
      />
      <Suspense fallback={<EvalRunListSkeleton />}>
        <EvalRunList />
      </Suspense>
    </Page>
  )
}
