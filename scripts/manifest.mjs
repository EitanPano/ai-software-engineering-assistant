import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { toRegExp } from './verify/glob.mjs'

export const GROUPS = ['harness', 'project', 'dev']
// The shape of .claude/harness.json and of the project record; the updater refuses another.
export const FORMAT = 1
const REQUIRED = [
  'format',
  'version',
  'repository',
  'rootCommit',
  'minCatalog',
  'groups',
  'references',
]
const MANIFEST_FILE = '.claude/harness.json'
const RECORD_FILE = '.fullstack/harness.json'

// Windows editors write a BOM, which JSON.parse rejects.
export const readJson = (file) => JSON.parse(readFileSync(file, 'utf8').replace(/^\uFEFF/, ''))

export function loadManifest(root) {
  const file = join(root, MANIFEST_FILE)
  if (!existsSync(file)) throw new Error(`Missing ${MANIFEST_FILE} in ${root}`)
  const manifest = readJson(file)
  for (const field of REQUIRED) {
    if (manifest[field] === undefined) throw new Error(`${MANIFEST_FILE}: missing field "${field}"`)
  }
  if (manifest.format !== FORMAT) {
    throw new Error(
      `${MANIFEST_FILE}: unknown format ${manifest.format} (this tool reads ${FORMAT})`,
    )
  }
  if (
    manifest.groups === null ||
    typeof manifest.groups !== 'object' ||
    Array.isArray(manifest.groups)
  ) {
    throw new Error(`${MANIFEST_FILE}: "groups" must be an object of glob lists`)
  }
  const wellFormed = (ref) =>
    ref !== null &&
    typeof ref === 'object' &&
    typeof ref.file === 'string' &&
    Array.isArray(ref.names) &&
    ref.names.every((name) => typeof name === 'string')
  if (!Array.isArray(manifest.references) || !manifest.references.every(wellFormed)) {
    throw new Error(`${MANIFEST_FILE}: "references" must be a list of { file, names }`)
  }
  for (const group of Object.keys(manifest.groups)) {
    if (!GROUPS.includes(group)) throw new Error(`${MANIFEST_FILE}: unknown group "${group}"`)
  }
  for (const group of GROUPS) {
    if (!Array.isArray(manifest.groups[group])) {
      throw new Error(`${MANIFEST_FILE}: group "${group}" must be a list of globs`)
    }
  }
  return manifest
}

function inGroup(entries, path) {
  const hit = (list) => list.some((glob) => toRegExp(glob).test(path))
  const exclude = entries.filter((glob) => glob.startsWith('!')).map((glob) => glob.slice(1))
  return hit(entries.filter((glob) => !glob.startsWith('!'))) && !hit(exclude)
}

export function groupsOf(manifest, path) {
  const normal = path.replaceAll('\\', '/')
  return GROUPS.filter((group) => inGroup(manifest.groups[group] ?? [], normal))
}

export function trackedFiles(root) {
  const out = execFileSync('git', ['ls-files', '-z'], { cwd: root, encoding: 'utf8' })
  return out
    .split('\0')
    .filter(Boolean)
    .map((file) => file.replaceAll('\\', '/'))
}

export function filesIn(manifest, group, files) {
  return files.filter((file) => groupsOf(manifest, file).includes(group))
}

export function hashFile(file) {
  return createHash('sha256').update(readFileSync(file)).digest('hex')
}

// `files` is the explicit list of shipped harness paths: a project's own files under a harness
// glob (a skill it added, say) must never be recorded as harness-owned, so nothing is discovered.
export function buildRecord(root, manifest, { commit = null, files } = {}) {
  if (!Array.isArray(files)) throw new Error('buildRecord needs the list of harness files')
  const hashes = {}
  for (const file of files) {
    if (!groupsOf(manifest, file).includes('harness')) {
      throw new Error(`${file} is not a harness file`)
    }
    const path = join(root, file)
    if (!existsSync(path)) throw new Error(`Harness file is missing: ${file}`)
    hashes[file] = hashFile(path)
  }
  const settings = readJson(join(root, '.claude', 'settings.json'))
  return { format: FORMAT, version: manifest.version, commit, files: sorted(hashes), settings }
}

function sorted(object) {
  return Object.fromEntries(Object.entries(object).sort(([a], [b]) => (a < b ? -1 : 1)))
}

export function readRecord(root) {
  const file = join(root, RECORD_FILE)
  return existsSync(file) ? readJson(file) : null
}

export function writeRecord(root, record) {
  const file = join(root, RECORD_FILE)
  mkdirSync(dirname(file), { recursive: true })
  writeFileSync(file, `${JSON.stringify(record, null, 2)}\n`)
}

function names(text, name) {
  const escaped = name.replace(/[.+?^${}()|[\]\\*]/g, '\\$&')
  return new RegExp(`(?<![\\w./-])${escaped}(?![\\w/-]|\\.\\w)`).test(text)
}

export function danglingReferences(root, manifest, files) {
  const allowed = new Map(manifest.references.map((ref) => [ref.file, new Set(ref.names)]))
  const dev = filesIn(manifest, 'dev', files)
  const found = []
  for (const file of filesIn(manifest, 'harness', files)) {
    const path = join(root, file)
    if (!existsSync(path)) continue
    const text = readFileSync(path, 'utf8')
    for (const name of dev) {
      if (!allowed.get(file)?.has(name) && names(text, name)) found.push({ file, name })
    }
  }
  return found
}
