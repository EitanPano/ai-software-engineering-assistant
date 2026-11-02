import { CircleAlertIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { Badge } from '@/shared/ui/badge'

import { errorReason, repositoryName, statusLabel, statusTone, type Source } from '../model'

const plural = (count: number, noun: string) => `${String(count)} ${noun}${count === 1 ? '' : 's'}`

// One source: the repository, its status in words, the ref and what was indexed, or why it
// failed. `action` is the row's end slot (the retry button, composed by the widget).
export function SourceRow({ source, action }: { source: Source; action?: ReactNode }) {
  const reason = errorReason(source.errorCode)
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card px-4 py-3 text-card-foreground sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="min-w-0 truncate font-medium">{repositoryName(source.url)}</span>
          {source.status === 'failed' ? (
            // The filled destructive badge fails the dark-mode contrast scan on a card, so a
            // failure is an outline in the destructive text colour, with an icon.
            <Badge variant="outline" className="border-destructive text-destructive">
              <CircleAlertIcon aria-hidden />
              {statusLabel(source.status)}
            </Badge>
          ) : (
            <Badge variant={statusTone(source.status)}>{statusLabel(source.status)}</Badge>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          <span className="break-all">{source.ref}</span>
          {source.status === 'ready'
            ? ` · ${plural(source.documentCount, 'document')} · ${plural(source.chunkCount, 'chunk')}`
            : null}
        </p>
        {source.status === 'failed' && reason ? (
          <p className="text-sm text-destructive">{reason}</p>
        ) : null}
      </div>
      {action}
    </div>
  )
}
