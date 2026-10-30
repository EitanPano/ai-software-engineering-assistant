import { Suspense } from 'react'
import { useParams } from 'react-router'

import { Page } from '@/shared/ui/pattern/page-layout'
import {
  ConversationHeader,
  ConversationHeaderSkeleton,
} from '@/widget/conversation-history/ui/conversation-header'
import { ConversationHistory } from '@/widget/conversation-history/ui/conversation-history'
import { ConversationHistorySkeleton } from '@/widget/conversation-history/ui/conversation-history-skeleton'

// One conversation: its title, the history and the send form. Behind `requireAccount`
// (routes.tsx). The id keys the widget, so opening another conversation starts its state clean.
export default function ConversationPage() {
  const { id = '' } = useParams()
  return (
    <Page>
      <title>Conversation · AI Software Engineering Assistant</title>
      <meta name="robots" content="noindex" />
      <Suspense fallback={<ConversationHeaderSkeleton />}>
        <ConversationHeader conversationId={id} />
      </Suspense>
      <Suspense fallback={<ConversationHistorySkeleton />}>
        <ConversationHistory key={id} conversationId={id} />
      </Suspense>
    </Page>
  )
}
