import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'
import { loadManifest, trackedFiles } from './manifest.mjs'

// The instruction files are prompts: every word is re-read on each turn of each agent that loads
// it, and a broken pointer fails silently in a loop run. These checks read the real tree.
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

// Ceilings just above the topic-word text measured in real sessions (plan 018). Topic words fire
// a skill, not length.
const DESCRIPTION_LIMIT = { skill: 480, agent: 280 }
const LISTING_LIMIT = 3800
const STARTUP_LIMIT = 7300 // words, largest role's always-loaded files + body + preloaded skills
const WORD_LIMIT = { 'AGENTS.md': 1200, '.claude/skills/dev-loop/SKILL.md': 2600 }
// What every session and sub-agent loads before its own prompt.
const ALWAYS_LOADED = [
  'CLAUDE.md',
  'AGENTS.md',
  '.doc/conventions.md',
  '.claude/rules/git-workflow.md',
  '.claude/rules/naming.md',
]

// `.claude/README.md` names old catalogs on purpose: it says which projects stay behind.
const VERSION_EXEMPT = new Set(['.claude/README.md'])
// Ignored or generated paths a doc may name that no clone tracks.
const PATH_EXEMPT = new Set(['.claude/settings.local.json'])

const files = trackedFiles(repoRoot)
const read = (file) => readFileSync(join(repoRoot, file), 'utf8').replace(/\r\n/g, '\n')
const words = (text) => text.split(/\s+/).filter(Boolean).length
const body = (text) => text.replace(/^---\n[\s\S]*?\n---\n/, '')
const docs = files.filter((f) => f.endsWith('.md') && !/^\.plan\/\d{3}-\d/.test(f))
const skills = files.filter((f) => /^\.claude\/skills\/[^/]+\/SKILL\.md$/.test(f))
const agents = files.filter((f) => /^\.claude\/agents\/[^/]+\.md$/.test(f))
const skillNames = new Set(skills.map((f) => f.split('/')[2]))
const skillFile = (name) => `.claude/skills/${name}/SKILL.md`

function frontmatter(file) {
  const block = /^---\n([\s\S]*?)\n---/.exec(read(file))?.[1] ?? ''
  const pairs = block.split('\n').map((line) => /^([\w-]+):\s*(.*)$/.exec(line))
  return Object.fromEntries(pairs.filter(Boolean).map(([, key, value]) => [key, value]))
}
const preloaded = (agent) =>
  /^\[(.*)\]$/
    .exec(frontmatter(agent).skills ?? '[]')[1]
    .split(',')
    .map((name) => name.trim())
    .filter(Boolean)

// Every match of a pattern across the docs, as `file: match`, filtered by `bad`.
function hits(pattern, bad, from = docs) {
  const found = []
  for (const file of from) {
    for (const match of read(file).matchAll(pattern)) {
      if (bad(match, file)) found.push(`${file}: ${match[0]}`)
    }
  }
  return found
}

const headings = (file) =>
  [...read(file).matchAll(/^#{1,4} +(.+)$/gm)].map((match) => match[1].trim().toLowerCase())

describe('descriptions', () => {
  it('names each skill after its directory', () => {
    for (const file of skills) assert.equal(frontmatter(file).name, file.split('/')[2], file)
  })
  it('keeps each description within its limit', () => {
    const over = (list, limit) =>
      list.filter((file) => frontmatter(file).description.length > limit)
    assert.deepEqual(over(skills, DESCRIPTION_LIMIT.skill), [])
    assert.deepEqual(over(agents, DESCRIPTION_LIMIT.agent), [])
  })
  it('keeps the listing every session pays for within its limit', () => {
    const size = skills.reduce((n, file) => n + frontmatter(file).description.length, 0)
    assert.ok(size <= LISTING_LIMIT, `${size} > ${LISTING_LIMIT}`)
  })
  // Topic words stay: a session decides to invoke from them. Only a spelled-out pipeline goes.
  it('spells no pipeline, which an agent then follows instead of the body', () => {
    const narrated = [...skills, ...agents].filter((f) => frontmatter(f).description.includes('→'))
    assert.deepEqual(narrated, [])
  })
})

describe('budgets', () => {
  it('keeps the size-limited files within their limits', () => {
    for (const [file, limit] of Object.entries(WORD_LIMIT)) {
      const size = words(read(file))
      assert.ok(size <= limit, `${file}: ${size} > ${limit}`)
    }
  })
  it('keeps each role startup prompt within the limit', () => {
    for (const agent of agents) {
      const parts = [...ALWAYS_LOADED.map(read), body(read(agent))]
      parts.push(...preloaded(agent).map((name) => body(read(skillFile(name)))))
      const size = words(parts.join(' '))
      assert.ok(size <= STARTUP_LIMIT, `${agent}: ${size} > ${STARTUP_LIMIT}`)
    }
  })
})

describe('pointers', () => {
  it('preloads only skills that exist', () => {
    for (const agent of agents) {
      for (const name of preloaded(agent)) assert.ok(skillNames.has(name), `${agent}: ${name}`)
    }
  })
  it('names only paths that exist', () => {
    const pattern = /`((?:\.claude|\.doc|\.github|\.orchestrate\/README|scripts)[^`\s]*\.(?:md|mjs|json))`/g
    const missing = hits(pattern, ([, path]) => {
      if (/[<*{]/.test(path) || PATH_EXEMPT.has(path)) return false
      return !existsSync(join(repoRoot, path))
    })
    assert.deepEqual(missing, [])
  })
  it('names only skills that exist', () => {
    const pattern = /`([a-z][a-z-]+)` skill\b/g
    assert.deepEqual(hits(pattern, ([, name]) => !skillNames.has(name)), [])
  })
  it('points only at numbered sections that exist', () => {
    const pattern = /`([a-z][a-z-]+)`(?: skill)?,? \(?section (\d+)/g
    const missing = hits(pattern, ([, name, number]) => {
      if (!skillNames.has(name)) return false
      return !headings(skillFile(name)).some((heading) => heading.startsWith(`${number}.`))
    })
    assert.deepEqual(missing, [])
  })
  // The first segment is a heading; a deeper one may be a list item, and only backticked
  // pointers are seen.
  it('points only at headings that exist', () => {
    const pattern = /`((?:\.doc\/)?[a-z][a-z-]*(?:\.md)?)\s›\s([^`›]+?)(?:\s›\s[^`]+)?`/g
    const missing = hits(pattern, ([, name, heading]) => {
      const file = name.startsWith('.doc/') ? name : skillFile(name)
      if (!name.startsWith('.doc/') && !skillNames.has(name)) return false
      return !headings(file).includes(heading.replace(/\s+/g, ' ').trim().toLowerCase())
    })
    assert.deepEqual(missing, [])
  })
})

describe('staleness', () => {
  it('names no catalog older than the oldest one this harness accepts', () => {
    const version = (text) => text.split('.').map(Number)
    const [major, minor] = version(loadManifest(repoRoot).minCatalog.slice(1))
    // Only a version the word `catalog` introduces: a harness tag reads the same.
    const pattern = /\bcatalog\s+(?:before\s+)?v(\d+)\.(\d+)\.\d+\b/gi
    const older = hits(pattern, ([, a, b], file) => {
      if (VERSION_EXEMPT.has(file)) return false
      return Number(a) < major || (Number(a) === major && Number(b) < minor)
    })
    assert.deepEqual(older, [])
  })
  it('names no internal proof run, which means nothing in a project', () => {
    const shipped = docs.filter((f) => f !== 'CONTRIBUTING.md')
    assert.deepEqual(hits(/\bproof prompt\b|\bP[3-9][a-z]?\b/g, () => true, shipped), [])
  })
})
