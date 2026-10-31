import type { SearchHit, SearchResult } from '@/shared/api'

export type { SearchHit, SearchResult }

// A chunk's text, path and symbol come from a repository anyone can publish, so none of it is
// trusted. Bidi controls could make a path or a line read as something else, and other invisible
// or control characters hide content, so they are shown as `[U+XXXX]` instead of obeyed: controls,
// format characters (bidi, zero width, tags), line and paragraph separators, and every
// default-ignorable code point (soft hyphen, fillers, variation selectors). Newline and tab stay,
// and a carriage return before a newline is dropped (a CRLF file), a lone one shown.
const HIDDEN = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}\p{Default_Ignorable_Code_Point}]/u

export function visibleText(text: string): string {
  let shown = ''
  for (const char of text.replace(/\r\n/g, '\n')) {
    const code = char.codePointAt(0) ?? 0
    shown +=
      char !== '\t' && char !== '\n' && HIDDEN.test(char)
        ? `[U+${code.toString(16).toUpperCase().padStart(4, '0')}]`
        : char
  }
  return shown
}

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
