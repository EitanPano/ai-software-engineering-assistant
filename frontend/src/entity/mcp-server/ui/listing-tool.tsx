import { visibleText } from '@/shared/lib/visible-text'
import { Badge } from '@/shared/ui/badge'

import { changeLabel, changeTone, type ListingTool as ListingToolData } from '../model'

// Third-party text is what the model will read, so it is shown whole, as plain text, with hidden
// characters made visible. It wraps: no inner scroll and no height cap, so nothing is out of sight
// above the accept. The input schemas are strings the server printed; they are shown as they came
// and never parsed or reformatted here, because the browser would print 1 and 1.0 alike.
function Version({
  label,
  description,
  schema,
}: {
  label: string
  description: string | null
  schema: string | null
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <h4 className="text-sm font-medium text-muted-foreground">{label}</h4>
      <p className="text-sm break-words whitespace-pre-wrap">{visibleText(description ?? '')}</p>
      <pre className="rounded-md bg-muted p-3 font-mono text-xs break-words whitespace-pre-wrap text-foreground">
        {visibleText(schema ?? '')}
      </pre>
    </div>
  )
}

// `policyNote` is the tool's stored policy in words, composed by the widget; the review shows it
// so an admin sees what a changed tool would do once accepted.
export function ListingTool({
  tool,
  policyNote,
}: {
  tool: ListingToolData
  policyNote?: string | null
}) {
  const pinned = tool.change === 'changed' || tool.change === 'removed'
  const live = tool.change !== 'removed'
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card px-4 py-3 text-card-foreground">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="min-w-0 font-medium break-all">{visibleText(tool.name)}</h3>
        <Badge variant={changeTone(tool.change)}>{changeLabel(tool.change)}</Badge>
      </div>
      {policyNote ? <p className="text-sm text-muted-foreground">{policyNote}</p> : null}
      {pinned ? (
        <Version
          label="Accepted version"
          description={tool.pinnedDescription}
          schema={tool.pinnedInputSchema}
        />
      ) : null}
      {live ? (
        <Version
          label={tool.change === 'changed' ? 'Live version' : 'Definition'}
          description={tool.description}
          schema={tool.inputSchema}
        />
      ) : null}
    </div>
  )
}
