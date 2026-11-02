import { useSuspenseQuery } from '@tanstack/react-query'
import { SearchIcon, SearchXIcon, TriangleAlertIcon } from 'lucide-react'

import { searchQuery } from '@/entity/chunk/api/chunk'
import { SearchHitRow } from '@/entity/chunk/ui/search-hit-row'
import { repositoryName } from '@/entity/source/model'
import { MAX_QUERY, searchSchema } from '@/feature/search/model'
import { Alert, AlertDescription, AlertTitle } from '@/shared/ui/alert'
import { EmptyState } from '@/shared/ui/pattern/empty-state'

// The results for the URL's text. No text, or text over the limit, asks nothing.
export function SearchResult({ q }: { q: string }) {
  if (q === '') {
    return (
      <EmptyState
        icon={SearchIcon}
        title="Search the knowledge base"
        description="Search every ready repository by identifier or by what the code does. Each result shows its file and lines."
      />
    )
  }
  if (!searchSchema.safeParse({ q }).success) {
    return (
      <EmptyState
        icon={SearchXIcon}
        title="Search text is too long"
        description={`Use ${String(MAX_QUERY)} characters or fewer, then search again.`}
      />
    )
  }
  return <Hits q={q} />
}

function Hits({ q }: { q: string }) {
  const { data } = useSuspenseQuery(searchQuery(q))

  if (data.items.length === 0) {
    return (
      <div className="flex max-w-3xl flex-col gap-3">
        {data.incomplete ? <IncompleteAlert /> : null}
        <EmptyState
          icon={SearchXIcon}
          title="No matches"
          description="Nothing in the connected repositories matched. Try an identifier, or describe what the code does."
        />
      </div>
    )
  }

  return (
    <div className="flex max-w-3xl flex-col gap-3">
      {data.incomplete ? <IncompleteAlert /> : null}
      <ul className="flex flex-col gap-3">
        {data.items.map((hit) => (
          <li key={hit.chunkId}>
            <SearchHitRow hit={hit} repository={repositoryName(hit.url)} />
          </li>
        ))}
      </ul>
    </div>
  )
}

function IncompleteAlert() {
  return (
    <Alert>
      <TriangleAlertIcon aria-hidden />
      <AlertTitle>Some results may be missing</AlertTitle>
      <AlertDescription>
        The search reached a limit, so a better match may not be shown. Try a more specific search.
      </AlertDescription>
    </Alert>
  )
}
