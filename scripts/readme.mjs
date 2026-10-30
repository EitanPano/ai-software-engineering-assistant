// The Configuration table of a project's README, generated from its tracked example env files.
// `node scripts/readme.mjs --configuration [--root <dir>]` rewrites the block between the two
// marker lines in <root>/README.md; the full `verify` run fails when the block is stale.
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { isMain } from './verify/main.mjs'

export const START = '<!-- configuration:start -->'
export const END = '<!-- configuration:end -->'
const USAGE = 'usage: node scripts/readme.mjs --configuration [--root <dir>]'
const EXAMPLE = '.env.example'
const NONE = 'This project reads no environment variables.'
const OPTIONAL = /^#\s?([A-Z][A-Z0-9_]*)=(.*)$/
const ASSIGNMENT = /^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/

// A value that is empty or a `change-me` placeholder is not a default worth showing.
function cleanValue(raw) {
  let value = raw.trim()
  if (/^(['"]).*\1$/.test(value) && value.length >= 2) value = value.slice(1, -1)
  return value === '' || value.startsWith('change-me') ? undefined : value
}

// Comment lines directly above a variable describe it; a blank line turns them into a header.
export function parseEnvExample(text) {
  const variables = []
  let pending = []
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim()
    const optional = OPTIONAL.exec(trimmed)
    const assignment = ASSIGNMENT.exec(trimmed)
    if (trimmed === '') pending = []
    else if (optional || assignment) {
      const [, name, raw] = optional ?? assignment
      const description = pending.join(' ')
      variables.push({ name, description, value: cleanValue(raw), optional: Boolean(optional) })
      pending = []
    } else if (trimmed.startsWith('#')) {
      const text = trimmed.replace(/^#\s?/, '').trim()
      if (text !== '') pending.push(text)
    } else pending = []
  }
  return variables
}

function trackedExamples(root) {
  // Untracked files that are not ignored count too: verify judges the tree as `git add -A` sees it.
  const run = spawnSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'], {
    cwd: root,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  })
  if (run.status !== 0) throw new Error(`git could not list files in ${root}`)
  return [...new Set(run.stdout.split('\0'))]
    .filter((file) => file === EXAMPLE || file.endsWith(`/${EXAMPLE}`))
    // A file deleted from the working tree but not yet staged is still listed.
    .filter((file) => existsSync(path.join(root, file)))
    .sort()
}

const cell = (text) => text.replaceAll('|', '\\|')

export function renderConfiguration(root) {
  const files = trackedExamples(root)
  if (files.length === 0) return [START, NONE, END].join('\n')
  const rows = ['| Variable | Description | Default |', '| --- | --- | --- |']
  for (const file of files) {
    const dir = path.posix.dirname(file)
    const prefix = files.length > 1 && dir !== '.' ? `${dir}: ` : ''
    const text = readFileSync(path.join(root, file), 'utf8')
    for (const v of parseEnvExample(text)) {
      const shown = v.value === undefined ? undefined : `\`${cell(v.value)}\``
      let fallback = shown ?? '—'
      if (v.optional) fallback = shown === undefined ? 'optional' : `optional (example ${shown})`
      rows.push(`| \`${v.name}\` | ${cell(prefix + v.description)} | ${fallback} |`)
    }
  }
  return [START, ...rows, END].join('\n')
}

function markerLines(lines) {
  const at = (marker) => lines.flatMap((l, i) => (l.trim() === marker ? [i] : []))
  const starts = at(START)
  const ends = at(END)
  if (starts.length !== 1 || ends.length !== 1) {
    throw new Error(`README.md needs exactly one ${START} and one ${END} marker line`)
  }
  if (ends[0] < starts[0]) throw new Error(`the ${END} marker comes before ${START}: wrong order`)
  return [starts[0], ends[0]]
}

// The block as it stands in the README, line endings normalised to LF.
export function extractConfiguration(readmeText) {
  const lines = readmeText.split(/\r?\n/)
  const [from, to] = markerLines(lines)
  return lines.slice(from, to + 1).join('\n')
}

export function replaceConfiguration(readmeText, block) {
  const eol = readmeText.includes('\r\n') ? '\r\n' : '\n'
  const lines = readmeText.split(/\r?\n/)
  const [from, to] = markerLines(lines)
  lines.splice(from, to - from + 1, ...block.split('\n'))
  return lines.join(eol)
}

function main(argv) {
  let root = process.cwd()
  let configuration = false
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--configuration') configuration = true
    else if (argv[i] === '--root' && argv[i + 1] !== undefined) root = path.resolve(argv[++i])
    else return fail(2, `unknown or incomplete argument ${argv[i]}\n${USAGE}`)
  }
  if (!configuration) return fail(2, USAGE)
  const file = path.join(root, 'README.md')
  try {
    const next = replaceConfiguration(readFileSync(file, 'utf8'), renderConfiguration(root))
    writeFileSync(file, next)
  } catch (error) {
    const reason = error.code === 'ENOENT' ? `${error.path ?? file} does not exist` : error.message
    return fail(1, reason.split('\n')[0])
  }
  return 0
}

function fail(code, message) {
  console.error(message)
  return code
}

if (isMain(import.meta.url, process.argv[1])) process.exit(main(process.argv.slice(2)))
