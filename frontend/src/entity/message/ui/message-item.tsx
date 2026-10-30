import { cn } from '@/shared/lib/cn'
import { Markdown } from '@/shared/ui/markdown'

import type { Message } from '../model'

// One turn. The person's own words are plain text; the agent's are sanitised Markdown. The
// speaker is named for assistive technology, and the bubble's side and fill tell it apart by eye.
export function MessageItem({ message }: { message: Pick<Message, 'role' | 'text'> }) {
  const mine = message.role === 'user'
  return (
    <li className={cn('flex flex-col gap-1', mine ? 'items-end' : 'items-start')}>
      <span className="sr-only">{mine ? 'You' : 'Agent'}</span>
      <div
        className={cn(
          'max-w-[90%] rounded-lg px-4 py-3 text-sm',
          mine ? 'bg-primary text-primary-foreground' : 'border border-border bg-card',
        )}
      >
        {mine ? <p className="break-words whitespace-pre-wrap">{message.text}</p> : null}
        {mine ? null : <Markdown>{message.text}</Markdown>}
      </div>
    </li>
  )
}
