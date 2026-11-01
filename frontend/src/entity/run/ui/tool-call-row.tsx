import { BanIcon, CheckIcon, LoaderCircleIcon, XIcon, type LucideIcon } from 'lucide-react'

import { visibleText } from '@/shared/lib/visible-text'
import { Badge } from '@/shared/ui/badge'

import { TOOL_STATUS_LABEL, type RunBlock, type ToolStatus } from '../model'

const STATUS: Record<
  ToolStatus,
  { variant: 'info' | 'success' | 'destructive' | 'warning'; icon: LucideIcon }
> = {
  running: { variant: 'info', icon: LoaderCircleIcon },
  succeeded: { variant: 'success', icon: CheckIcon },
  failed: { variant: 'destructive', icon: XIcon },
  denied: { variant: 'warning', icon: BanIcon },
}

// A tool's status, in words and an icon, never colour alone.
export function ToolStatusBadge({ status }: { status: ToolStatus }) {
  const { variant, icon: Icon } = STATUS[status]
  return (
    <Badge variant={variant}>
      <Icon aria-hidden className={status === 'running' ? 'motion-safe:animate-spin' : undefined} />
      {TOOL_STATUS_LABEL[status]}
    </Badge>
  )
}

// One tool call in place in the answer: its name and status, the input it was given and, once it
// finished, its output. Input and output are plain text, never rendered as Markdown or HTML.
export function ToolCallRow({ call }: { call: Extract<RunBlock, { kind: 'tool' }> }) {
  return (
    <li className="flex max-w-[90%] flex-col gap-2 rounded-lg border border-dashed border-border bg-muted/40 px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono font-medium">{call.name}</span>
        <ToolStatusBadge status={call.status} />
      </div>
      <pre className="font-mono text-xs break-words whitespace-pre-wrap text-muted-foreground">
        {visibleText(JSON.stringify(call.input))}
      </pre>
      {call.output === undefined ? null : (
        // A long output scrolls inside its own box, which the keyboard can reach and scroll.
        <div
          role="group"
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scroll box must take focus
          tabIndex={0}
          aria-label={`Output of ${call.name}`}
          className="max-h-64 overflow-auto rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <pre className="font-mono text-xs break-words whitespace-pre-wrap">
            {visibleText(call.output)}
          </pre>
        </div>
      )}
    </li>
  )
}
