import { ArrowLeftIcon } from 'lucide-react'
import { Suspense } from 'react'
import { Link, useParams } from 'react-router'

import { Button } from '@/shared/ui/button'
import { Page, PageHeader } from '@/shared/ui/pattern/page-layout'
import { McpServerDetail } from '@/widget/mcp-server-detail/ui/mcp-server-detail'
import { McpServerDetailSkeleton } from '@/widget/mcp-server-detail/ui/mcp-server-detail-skeleton'

// One MCP server, behind `requireRole(…, 'admin')` (routes.tsx). It reads the stored state and
// calls no server; the review page is the one that does.
export default function McpServerPage() {
  const { id = '' } = useParams()
  return (
    <Page>
      <title>MCP server · AI Software Engineering Assistant</title>
      <meta name="robots" content="noindex" />
      <PageHeader
        title="MCP server"
        actions={
          <Button asChild variant="outline">
            <Link to="/mcp-server">
              <ArrowLeftIcon aria-hidden />
              All MCP servers
            </Link>
          </Button>
        }
      />
      <Suspense fallback={<McpServerDetailSkeleton />}>
        <McpServerDetail key={id} id={id} />
      </Suspense>
    </Page>
  )
}
