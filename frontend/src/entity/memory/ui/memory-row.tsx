import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { formatDateTime } from '@/shared/lib/date'
import { visibleText } from '@/shared/lib/visible-text'

import type { Memory } from '../model'

// One memory: what the person said, as plain text that wraps, when it was saved and a link to
// the conversation it came from. `action` is the delete, which a feature supplies.
export function MemoryRow({ memory, action }: { memory: Memory; action?: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card px-4 py-3 text-card-foreground sm:flex-row sm:items-start sm:gap-4">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-sm break-words whitespace-pre-wrap">{visibleText(memory.content)}</p>
        <p className="flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
          <time dateTime={memory.createdAt}>{formatDateTime(memory.createdAt, 'UTC')} UTC</time>
          <Link
            to={`/conversation/${memory.conversationId}`}
            className="rounded-xs underline underline-offset-4 outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            Conversation
          </Link>
        </p>
      </div>
      {action}
    </div>
  )
}
