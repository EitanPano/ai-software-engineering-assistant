import { PlusIcon } from 'lucide-react'
import { Suspense } from 'react'
import { Link } from 'react-router'

import { Button } from '@/shared/ui/button'
import { Page, PageHeader } from '@/shared/ui/pattern/page-layout'
import { SourceList } from '@/widget/source-list/ui/source-list'
import { SourceListSkeleton } from '@/widget/source-list/ui/source-list-skeleton'

// The connected repositories, behind `requireRole(…, 'admin')` (routes.tsx). Connecting one is
// the page's one primary action.
export default function SourceListPage() {
  return (
    <Page>
      <title>Sources · AI Software Engineering Assistant</title>
      <meta name="robots" content="noindex" />
      <PageHeader
        title="Sources"
        actions={
          <Button asChild>
            <Link to="/source/connect">
              <PlusIcon aria-hidden />
              Connect repository
            </Link>
          </Button>
        }
      />
      <Suspense fallback={<SourceListSkeleton />}>
        <SourceList />
      </Suspense>
    </Page>
  )
}
