import type { SearchHit, SearchResult } from '@/shared/api'
import { visibleText } from '@/shared/lib/visible-text'

export type { SearchHit, SearchResult }

// A chunk's text, path and symbol come from a repository anyone can publish; they are shown
// through `visibleText` (shared/lib), as is a tool call's input and output.
export { visibleText }

// `path:start-end`, with one number for a piece of a single line.
export function chunkLabel(hit: Pick<SearchHit, 'path' | 'startLine' | 'endLine'>): string {
  const lines =
    hit.startLine === hit.endLine
      ? String(hit.startLine)
      : `${String(hit.startLine)}-${String(hit.endLine)}`
  return `${visibleText(hit.path)}:${lines}`
}

// Whether full-text or trigram search returned the chunk, which is what an exact name or call
// produces; a hit only the semantic search found has neither rank.
export const matchedKeyword = (hit: Pick<SearchHit, 'fullTextRank' | 'trigramRank'>): boolean =>
  hit.fullTextRank !== null || hit.trigramRank !== null
