import { MessageSquareIcon } from 'lucide-react'
import { Link } from 'react-router'

import { conversationTitle, type Conversation } from '../model'

// One row of the list: the title, as a link to the conversation.
export function ConversationRow({ conversation }: { conversation: Conversation }) {
  return (
    <Link
      to={`/conversation/${conversation.id}`}
      className="flex min-h-12 items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 text-card-foreground outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50 pointer-coarse:min-h-14"
    >
      <MessageSquareIcon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate font-medium">{conversationTitle(conversation)}</span>
    </Link>
  )
}
