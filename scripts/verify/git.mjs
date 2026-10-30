import { spawnSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

// No optional locks, no fsmonitor daemon and no untracked cache: each can write the real index
// or start a process that outlives verify. The real index must stay as it was.
const QUIET = [
  ...['-c', 'core.quotepath=false', '-c', 'core.fsmonitor=false'],
  ...['-c', 'core.untrackedCache=false'],
]
export function git(root, args, env = {}) {
  const run = spawnSync('git', [...QUIET, ...args], {
    cwd: root,
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
    env: { ...process.env, GIT_OPTIONAL_LOCKS: '0', ...env },
  })
  return { ok: run.status === 0, out: run.stdout ?? '', err: run.stderr ?? '' }
}

// The tree of the working copy as `git add -A` would stage it, built in a temporary copy of the
// index so the real one is never written. Ignored files do not count.
export function treeHash(root) {
  const real = git(root, ['rev-parse', '--git-path', 'index'])
  const dir = mkdtempSync(path.join(tmpdir(), 'verify-index-'))
  const index = path.join(dir, 'index')
  try {
    const source = path.resolve(root, real.out.trim())
    if (real.ok && existsSync(source)) copyFileSync(source, index)
    const env = { GIT_INDEX_FILE: index }
    const add = git(root, ['add', '-A'], env)
    const tree = add.ok ? git(root, ['write-tree'], env) : add
    if (!tree.ok) throw new Error(`git could not hash the tree: ${tree.err.trim()}`)
    return tree.out.trim()
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

// `dirs` limits the diff to those directories (git pathspecs); a partial run reads its own
// packages only, so a sibling's concurrent edit never fails it.
const scope = (dirs) => (dirs?.length > 0 ? ['--', ...dirs] : [])

export function changedFiles(root, from, to, dirs) {
  const range = to ? [from, to] : [from]
  const diff = git(root, ['diff', '--name-only', '--no-renames', ...range, ...scope(dirs)])
  return diff.out.split(/\r?\n/).filter(Boolean)
}

// Added lines between a base commit and a tree from `treeHash`, as [{ file, line, text }]. The
// tree already holds the untracked files, and diffing trees never refreshes the real index, which
// `git diff <base>` against the working copy does.
export function addedLines(root, base, tree, dirs) {
  const added = []
  const args = ['diff', '--unified=0', '--no-color', '--no-renames', base, tree, ...scope(dirs)]
  const diff = git(root, args)
  let file = ''
  let line = 0
  for (const text of diff.out.split(/\r?\n/)) {
    const header = /^\+\+\+ (?:b\/(.*)|\/dev\/null)$/.exec(text)
    const hunk = /^@@ -\S+ \+(\d+)/.exec(text)
    if (header !== null) file = header[1] ?? ''
    else if (hunk !== null) line = Number(hunk[1])
    else if (text.startsWith('+') && file !== '') {
      added.push({ file, line: line++, text: text.slice(1) })
    }
  }
  return added
}
