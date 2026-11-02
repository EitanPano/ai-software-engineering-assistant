import { Suspense } from 'react'

import { Page, PageHeader } from '@/shared/ui/pattern/page-layout'
import { MemoryList } from '@/widget/memory-list/ui/memory-list'
import { MemoryListSkeleton } from '@/widget/memory-list/ui/memory-list-skeleton'

// What the agent remembers about the caller, behind `requireAccount` (routes.tsx). Nothing is
// created here, so the page header has no action.
export default function MemoryPage() {
  return (
    <Page>
      <title>Memory · AI Software Engineering Assistant</title>
      <meta name="robots" content="noindex" />
      <PageHeader
        title="Memory"
        description="Facts the agent remembers from your messages. It reads them in new conversations."
      />
      <Suspense fallback={<MemoryListSkeleton />}>
        <MemoryList />
      </Suspense>
    </Page>
  )
}
