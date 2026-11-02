import { Suspense } from 'react'

import { Page, PageHeader } from '@/shared/ui/pattern/page-layout'
import { McpServerList } from '@/widget/mcp-server-list/ui/mcp-server-list'
import { McpServerListSkeleton } from '@/widget/mcp-server-list/ui/mcp-server-list-skeleton'

// The MCP servers, behind `requireRole(…, 'admin')` (routes.tsx). Reads only; no server is called.
export default function McpServerListPage() {
  return (
    <Page>
      <title>MCP servers · AI Software Engineering Assistant</title>
      <meta name="robots" content="noindex" />
      <PageHeader
        title="MCP servers"
        description="Review what each server offers, turn it on or off, and set what each tool may do."
      />
      <Suspense fallback={<McpServerListSkeleton />}>
        <McpServerList />
      </Suspense>
    </Page>
  )
}
