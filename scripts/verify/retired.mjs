import { readFileSync } from 'node:fs'
import path from 'node:path'
import { git } from './git.mjs'
import { matching } from './glob.mjs'
import { EXCLUDED } from './review.mjs'

// The review package's exclusions, plus migrations and the loop's own folders. A retired name
// may stay in history; it may not stay in the code.
const SKIP = [
  ...EXCLUDED,
  '**/migrations/**',
  '**/*.sql',
  '.plan/**',
  '.orchestrate/**',
]

// The first plan line starting `Retired:` is the source; each backtick span is one term. `none`,
// no span or no line means the check does not run.
export function parseRetired(text) {
  const line = /^Retired:(.*)$/m.exec(text)?.[1] ?? ''
  return [...new Set([...line.matchAll(/`([^`]+)`/g)].map((match) => match[1]))]
}

// Hits as [{ file, line, text }] for the terms (fixed strings, case-insensitive) in the files of
// the working copy inside `dirs`: tracked plus untracked, not ignored. A term also matches a
// file's repository path (line 0). A failed git call throws: the check must not pass blind.
export function retiredHits(root, dirs, terms) {
  const list = git(root, ['ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', ...dirs])
  if (!list.ok) throw new Error(`git ls-files failed: ${list.err.trim()}`)
  const files = list.out
    .split('\0')
    .filter(Boolean)
    .filter((file) => matching([file], SKIP).length === 0)
  const needles = terms.map((term) => [term, term.toLowerCase()])
  const hits = []
  for (const file of [...new Set(files)]) {
    const named = needles.find(([, needle]) => file.toLowerCase().includes(needle))
    if (named !== undefined) hits.push({ file, line: 0, text: `\`${named[0]}\` in the path` })
    let body
    try {
      body = readFileSync(path.join(root, file), 'utf8')
    } catch {
      continue // deleted in the working copy
    }
    if (body.includes('\0')) continue
    body.split(/\r?\n/).forEach((text, index) => {
      const lower = text.toLowerCase()
      const found = needles.find(([, needle]) => lower.includes(needle))
      if (found !== undefined) {
        hits.push({ file, line: index + 1, text: `\`${found[0]}\` ${text.trim().slice(0, 100)}` })
      }
    })
  }
  return hits
}
