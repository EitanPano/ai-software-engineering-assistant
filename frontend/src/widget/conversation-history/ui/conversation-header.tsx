import { useSuspenseQuery } from '@tanstack/react-query'
import { ArrowLeftIcon } from 'lucide-react'
import { Link } from 'react-router'

import { conversationQuery } from '@/entity/conversation/api/conversation'
import { conversationTitle } from '@/entity/conversation/model'
import { Button } from '@/shared/ui/button'
import { PageHeader } from '@/shared/ui/pattern/page-layout'
import { Skeleton } from '@/shared/ui/skeleton'

// The page's `h1`: the conversation's title, with the way back to the list.
export function ConversationHeader({ conversationId }: { conversationId: string }) {
  const { data } = useSuspenseQuery(conversationQuery(conversationId))
  return (
    <PageHeader
      title={conversationTitle(data)}
      actions={
        <Button asChild variant="outline">
          <Link to="/conversation">
            <ArrowLeftIcon aria-hidden />
            All conversations
          </Link>
        </Button>
      }
    />
  )
}

export function ConversationHeaderSkeleton() {
  return <Skeleton className="h-8 w-1/2" />
}
