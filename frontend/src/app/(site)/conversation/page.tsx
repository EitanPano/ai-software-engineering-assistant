import { Suspense } from 'react'

import { StartConversationButton } from '@/feature/start-conversation/ui/start-conversation-button'
import { Page, PageHeader } from '@/shared/ui/pattern/page-layout'
import { ConversationList } from '@/widget/conversation-list/ui/conversation-list'
import { ConversationListSkeleton } from '@/widget/conversation-list/ui/conversation-list-skeleton'

// The caller's conversations, behind `requireAccount` (routes.tsx). Starting one is the page's
// one primary action.
export default function ConversationListPage() {
  return (
    <Page>
      <title>Conversations · AI Software Engineering Assistant</title>
      <meta name="robots" content="noindex" />
      <PageHeader title="Conversations" actions={<StartConversationButton />} />
      <Suspense fallback={<ConversationListSkeleton />}>
        <ConversationList />
      </Suspense>
    </Page>
  )
}
