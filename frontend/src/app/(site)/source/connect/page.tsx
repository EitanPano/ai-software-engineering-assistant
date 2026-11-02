import { ConnectForm } from '@/feature/connect/ui/connect-form'
import { Page, PageHeader } from '@/shared/ui/pattern/page-layout'

// Connect a public GitHub repository, behind `requireRole(…, 'admin')` (routes.tsx).
export default function ConnectSourcePage() {
  return (
    <Page>
      <title>Connect repository · AI Software Engineering Assistant</title>
      <meta name="robots" content="noindex" />
      <PageHeader
        title="Connect repository"
        description="Index a public GitHub repository so the knowledge base can use its code."
      />
      <ConnectForm />
    </Page>
  )
}
