import { visibleText } from '@/shared/lib/visible-text'
import { Badge } from '@/shared/ui/badge'

import { chunkLabel, matchedKeyword, type SearchHit } from '../model'

// One search hit: the repository, where the chunk is, its symbol and its text. The text is plain
// (never Markdown, which would turn a chunk into links and headings) in a wrapping `pre`, so a
// long line wraps instead of scrolling the page sideways.
export function SearchHitRow({ hit, repository }: { hit: SearchHit; repository: string }) {
  return (
    <article className="flex flex-col gap-2 rounded-lg border border-border bg-card px-4 py-3 text-card-foreground">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="min-w-0 font-medium break-all">{visibleText(repository)}</span>
        {matchedKeyword(hit) ? <Badge variant="info">Keyword match</Badge> : null}
      </div>
      <p className="font-mono text-sm break-all text-muted-foreground">
        <span>{chunkLabel(hit)}</span>
        {hit.symbol === null ? null : (
          <>
            {' · '}
            <span className="text-foreground">{visibleText(hit.symbol)}</span>
          </>
        )}
      </p>
      <pre className="rounded-md bg-muted/50 p-3 font-mono text-xs break-all whitespace-pre-wrap">
        {visibleText(hit.content)}
      </pre>
    </article>
  )
}
