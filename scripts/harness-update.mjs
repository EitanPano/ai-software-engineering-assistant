#!/usr/bin/env node
// Takes a newer harness release into a generated project: replaces only the files the version
// record (.fullstack/harness.json) lists, merges the project's own permission entries into the
// release's settings, rewrites the .gitignore harness block and re-records the new version.
// Exit codes follow verify.mjs: 0 done, 1 refused or failed (nothing left half-applied), 2 usage.
import { execFileSync, spawnSync } from 'node:child_process'
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  rmdirSync,
  writeFileSync,
} from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import {
  FORMAT,
  buildRecord,
  filesIn,
  hashFile,
  loadManifest,
  readJson,
  readRecord,
  trackedFiles,
  writeRecord,
} from './manifest.mjs'

const USAGE = `Usage: node scripts/harness-update.mjs (--version <tag|commit> | --from <path>)
  [--overwrite] [--root <dir>]

  --version <tag|commit>  fetch that harness release into the cache
                          (~/.cache/fullstack-dev-harness, or $FULLSTACK_HARNESS_CACHE)
  --from <path>           use a local harness checkout as it is
  --overwrite             replace harness files that were edited in this project
  --root <dir>            the project (default: the repository this script sits in)`

const BLOCK_START = '# >>> harness:'
const BLOCK_END = '# <<< harness'
const SETTINGS = '.claude/settings.json'
const GITIGNORE = '.gitignore'
const RECORD = '.fullstack/harness.json'

class Refusal extends Error {}

function git(cwd, args) {
  return execFileSync('git', args, {
    cwd,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    maxBuffer: 1 << 28,
  })
}

function gitOk(cwd, args) {
  return spawnSync('git', args, { cwd, stdio: 'ignore' }).status === 0
}

export function parseArgs(argv) {
  const parsed = { overwrite: false }
  const value = (name, i) => {
    const next = argv[i]
    if (next === undefined || next.startsWith('--')) throw new Error(`${name} needs a value`)
    return next
  }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '--help') parsed.help = true
    else if (arg === '--overwrite') parsed.overwrite = true
    else if (arg === '--version') parsed.version = value(arg, ++i)
    else if (arg === '--from') parsed.from = value(arg, ++i)
    else if (arg === '--root') parsed.root = value(arg, ++i)
    else throw new Error(`unknown argument ${arg}`)
  }
  if (parsed.help) return parsed
  if ((parsed.version === undefined) === (parsed.from === undefined)) {
    throw new Error('give exactly one of --version and --from')
  }
  return parsed
}

const semver = (tag) => {
  const match = /^v?(\d+)\.(\d+)\.(\d+)/.exec(tag)
  return match ? match.slice(1).map(Number) : null
}

function compare(a, b) {
  const x = semver(a)
  const y = semver(b)
  for (let i = 0; i < 3; i += 1) if (x[i] !== y[i]) return x[i] - y[i]
  return 0
}

// Mirrors bootstrap.mjs's catalog cache, but a full clone: the compatibility check reads old tags.
function fetchRelease(version, repository) {
  if (!/^[\w][\w.+-]*$/.test(version)) throw new Refusal(`"${version}" is not a tag or commit`)
  const cache =
    process.env.FULLSTACK_HARNESS_CACHE ?? join(homedir(), '.cache', 'fullstack-dev-harness')
  const dir = join(cache, version)
  try {
    if (existsSync(dir)) git(dir, ['fetch', '--quiet', '--tags', 'origin'])
    else {
      mkdirSync(cache, { recursive: true })
      console.log(`cloning ${repository} into ${dir}`)
      git(cache, ['clone', '--quiet', '--', repository, dir])
    }
    git(dir, [
      '-c',
      'advice.detachedHead=false',
      'checkout',
      '--quiet',
      '--force',
      '--detach',
      version,
    ])
  } catch (error) {
    const why = String(error.stderr ?? error.message).trim()
    throw new Refusal(
      `could not fetch ${version} from ${repository} into ${dir} (it needs the network): ${why}`,
    )
  }
  return dir
}

function newestCompatible(source, lockVersion) {
  const tags = git(source, ['tag', '--list', 'v*'])
    .split(/\r?\n/)
    .filter((tag) => semver(tag))
  tags.sort((a, b) => compare(b, a))
  for (const tag of tags) {
    try {
      const manifest = JSON.parse(git(source, ['show', `${tag}:.claude/harness.json`]))
      if (compare(manifest.minCatalog, lockVersion) <= 0) return tag
    } catch {
      // A tag from before the manifest existed is not a candidate.
    }
  }
  return null
}

const stable = (value) =>
  JSON.stringify(value, (_, v) =>
    v && typeof v === 'object' && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => (a < b ? -1 : 1)))
      : v,
  )

function loadOrRefuse(root, what) {
  try {
    return loadManifest(root)
  } catch (error) {
    throw new Refusal(`${what}: ${error.message}`)
  }
}
const ENTRY_LISTS = ['allow', 'deny']

// Entries in permissions.allow/deny that the recorded release did not ship belong to the project.
function projectEntries(current, recorded) {
  const found = {}
  for (const list of ENTRY_LISTS) {
    const known = new Set(recorded?.permissions?.[list] ?? [])
    found[list] = (current?.permissions?.[list] ?? []).filter((entry) => !known.has(entry))
  }
  return found
}

function withoutProjectEntries(current, recorded) {
  const copy = structuredClone(current)
  for (const list of ENTRY_LISTS) {
    if (!copy.permissions?.[list]) continue
    const known = new Set(recorded?.permissions?.[list] ?? [])
    copy.permissions[list] = copy.permissions[list].filter((entry) => known.has(entry))
  }
  return copy
}

function mergeSettings(release, entries) {
  const merged = structuredClone(release)
  for (const list of ENTRY_LISTS) {
    if (entries[list].length === 0) continue
    merged.permissions ??= {}
    const base = merged.permissions[list] ?? []
    merged.permissions[list] = [...base, ...entries[list].filter((entry) => !base.includes(entry))]
  }
  return `${JSON.stringify(merged, null, 2)}\n`
}

function localEdits(root, record) {
  const edits = []
  for (const [file, hash] of Object.entries(record.files)) {
    const path = join(root, file)
    if (!existsSync(path)) edits.push(`${file} (missing)`)
    else if (file === SETTINGS && record.settings) {
      // Project permission entries are expected here; every other change is an edit.
      let current
      try {
        current = readJson(path)
      } catch {
        edits.push(`${file} (not valid JSON)`)
        continue
      }
      if (stable(withoutProjectEntries(current, record.settings)) !== stable(record.settings)) {
        edits.push(`${file} (modified)`)
      }
    } else if (hashFile(path) !== hash) edits.push(`${file} (modified)`)
  }
  return edits
}

function gitignoreBlock(text) {
  const lines = text.split(/\r?\n/)
  const start = lines.findIndex((line) => line.startsWith(BLOCK_START))
  const end = lines.findIndex((line, i) => i > start && line.trimEnd() === BLOCK_END)
  return start === -1 || end === -1 ? null : { lines, start, end }
}

function rewriteGitignore(root, sourceText) {
  const release = gitignoreBlock(sourceText)
  if (!release) return
  const block = release.lines.slice(release.start, release.end + 1)
  const file = join(root, GITIGNORE)
  const current = existsSync(file) ? readFileSync(file, 'utf8') : ''
  const eol = current.includes('\r\n') ? '\r\n' : '\n'
  const found = gitignoreBlock(current)
  let lines
  if (found)
    lines = [...found.lines.slice(0, found.start), ...block, ...found.lines.slice(found.end + 1)]
  else lines = current === '' ? [...block, ''] : [...block, '', ...current.split(/\r?\n/)]
  writeFileSync(file, lines.join(eol))
}

function copyTo(from, to) {
  mkdirSync(dirname(to), { recursive: true })
  copyFileSync(from, to)
}

function ancestors(root, rel) {
  const dirs = []
  for (let dir = dirname(rel); dir !== '.' && dir !== ''; dir = dirname(dir))
    dirs.push(join(root, dir))
  return dirs
}

function pruneEmpty(dirs) {
  for (const dir of [...dirs].sort((a, b) => b.length - a.length)) {
    try {
      if (existsSync(dir) && readdirSync(dir).length === 0) rmdirSync(dir)
    } catch {
      // Not empty or already gone.
    }
  }
}

// Best effort per file: one failing restore must not stop the others. Returns what failed.
function restore(root, backup, touched, newDirs) {
  const failed = []
  for (const rel of touched) {
    try {
      const saved = join(backup, rel)
      if (existsSync(saved)) copyTo(saved, join(root, rel))
      else rmSync(join(root, rel), { force: true })
    } catch (error) {
      failed.push(`${rel} (${error.message})`)
    }
  }
  pruneEmpty(newDirs)
  return failed
}

function hookRuns(settings, root) {
  const sub = (text) => String(text).replaceAll('${CLAUDE_PROJECT_DIR}', root)
  const runs = []
  // PreToolUse is the only event the harness wires; the payload below is that event's shape.
  for (const group of settings.hooks?.PreToolUse ?? []) {
    for (const hook of group.hooks ?? []) {
      if (hook.type && hook.type !== 'command') continue
      runs.push({
        name: [hook.command, ...(hook.args ?? [])].join(' '),
        file: sub(hook.command),
        args: hook.args?.map(sub),
        timeout: (hook.timeout ?? 10) * 1000,
      })
    }
  }
  return runs
}

// Three benign PreToolUse calls, the shape Claude Code sends to every hook: a hook that refuses
// a plain read, a status check or an edit of the README would lock the project out.
function probePayloads(root) {
  const readme = join(root, 'README.md')
  const call = (tool_name, tool_input) => JSON.stringify({ cwd: root, tool_name, tool_input })
  return [
    call('Read', { file_path: readme }),
    call('Bash', { command: 'git status' }),
    call('Edit', { file_path: readme, old_string: 'a', new_string: 'b' }),
  ]
}

export function failingHook(settings, root) {
  for (const run of hookRuns(settings, root)) {
    for (const input of probePayloads(root)) {
      const result = spawnSync(run.file, run.args ?? [], {
        cwd: root,
        input,
        encoding: 'utf8',
        timeout: run.timeout,
        shell: run.args === undefined,
        env: { ...process.env, CLAUDE_PROJECT_DIR: root },
      })
      if (result.error || result.status !== 0) {
        const why = result.error
          ? result.error.message
          : `exit ${result.status} ${result.stderr ?? ''}`.trim()
        return { name: run.name, why }
      }
    }
  }
  return null
}

// Returns the text; it is printed only once the update has been applied.
function adviceText(source, record, commit, manifest, files) {
  const seeds = filesIn(manifest, 'project', files).filter((file) => file !== 'README.md')
  const resolves = (rev) => gitOk(source, ['cat-file', '-e', `${rev}^{commit}`])
  // A "Use this template" project records no commit; its version's tag is the next best base.
  const since = [record.commit, `v${record.version}`, record.version].find(
    (rev) => rev && resolves(rev),
  )
  const known = since && commit
  if (!known) {
    const list = seeds.map((file) => `  ${file}`).join('\n')
    return (
      '\nProject files the release seeds (upstream changes cannot be shown, ' +
      `the old commit is unknown here):\n${list}`
    )
  }
  const diff = seeds.length === 0 ? '' : git(source, ['diff', since, commit, '--', ...seeds])
  const head = `\nUpstream changes to project files since ${since.slice(0, 7)} (advice only):`
  return `${head}\n${diff.trim() === '' ? '  none' : diff}`
}

export function update({ source, root, overwrite, fetched }) {
  const projectManifest = loadOrRefuse(root, 'this project')
  const lock = readJson(join(root, 'catalog.lock'))
  const src = fetched ?? resolve(source)
  if (!existsSync(join(src, '.claude', 'harness.json')))
    throw new Refusal(`${src} is not a harness checkout`)
  const release = loadOrRefuse(src, 'the release')

  for (const [what, tag] of [
    ['minCatalog', release.minCatalog],
    ['catalog.lock version', lock.version],
  ]) {
    if (!semver(tag)) throw new Refusal(`${what} "${tag}" is not a version such as v1.5.0`)
  }
  if (compare(release.minCatalog, lock.version) > 0) {
    const tag = newestCompatible(src, lock.version)
    const hint = tag
      ? `the newest release your catalog ${lock.version} satisfies is ${tag}`
      : 'no release of this harness fits it'
    throw new Refusal(
      `release ${release.version} needs catalog ${release.minCatalog}, ` +
        `this project is on ${lock.version}; ${hint}`,
    )
  }

  const record = readRecord(root)
  if (!record) {
    throw new Refusal(
      `${RECORD} is missing, so the harness files cannot be told from project files; ` +
        'follow the manual update in .claude/README.md',
    )
  }
  if (record.format !== FORMAT) {
    throw new Refusal(
      `${RECORD}: unknown format ${record.format} (this tool reads ${FORMAT}); ` +
        'follow the manual update in .claude/README.md',
    )
  }
  if (!record.settings || typeof record.settings !== 'object') {
    throw new Refusal(
      `${RECORD} has no "settings", so project permission entries cannot be told from ` +
        'shipped ones; restore the file or follow the manual update in .claude/README.md',
    )
  }
  const edits = localEdits(root, record)
  if (edits.length > 0 && !overwrite) {
    throw new Refusal(
      'harness files were edited in this project (use --overwrite to replace them):\n  ' +
        edits.join('\n  '),
    )
  }

  const tracked = trackedFiles(src)
  const files = filesIn(release, 'harness', tracked).filter((file) => existsSync(join(src, file)))
  const collisions = files.filter((file) => existsSync(join(root, file)) && !(file in record.files))
  if (collisions.length > 0) {
    throw new Refusal(
      'the release ships files that already exist in this project as project files:\n  ' +
        collisions.join('\n  '),
    )
  }
  // A file the release still tracks (reclassified as project, say) is the project's now.
  const dropped = Object.keys(record.files).filter((file) => !tracked.includes(file))

  const currentSettings = existsSync(join(root, SETTINGS)) ? readJson(join(root, SETTINGS)) : null
  const entries = projectEntries(currentSettings, record.settings)
  const releaseSettings = readJson(join(src, SETTINGS))

  const touched = [...new Set([...files, ...dropped, GITIGNORE, SETTINGS, RECORD])]
  const backup = mkdtempSync(join(tmpdir(), 'harness-update-'))
  const newDirs = new Set()
  for (const rel of touched) {
    const path = join(root, rel)
    if (existsSync(path)) copyTo(path, join(backup, rel))
    else for (const dir of ancestors(root, rel)) if (!existsSync(dir)) newDirs.add(dir)
  }

  let text
  let commit = null
  try {
    for (const file of files) copyTo(join(src, file), join(root, file))
    for (const file of dropped) rmSync(join(root, file), { force: true })
    pruneEmpty(dropped.flatMap((file) => ancestors(root, file)))
    if (existsSync(join(src, GITIGNORE)))
      rewriteGitignore(root, readFileSync(join(src, GITIGNORE), 'utf8'))
    if (entries.allow.length + entries.deny.length > 0) {
      writeFileSync(join(root, SETTINGS), mergeSettings(releaseSettings, entries))
    }
    const bad = failingHook(readJson(join(root, SETTINGS)), root)
    if (bad) throw new Refusal(`hook "${bad.name}" failed on the new files (${bad.why})`)
    try {
      commit = git(src, ['rev-parse', 'HEAD']).trim()
    } catch {
      // Not a git checkout of its own: the commit stays unrecorded.
    }
    text = adviceText(src, record, commit, release, tracked)
    const next = buildRecord(root, release, { commit, files })
    next.settings = releaseSettings
    writeRecord(root, next)
  } catch (error) {
    let failed
    try {
      failed = restore(root, backup, touched, newDirs)
    } catch (restoreError) {
      failed = [restoreError.message]
    }
    const state =
      failed.length === 0 ? 'everything is restored' : `not restored: ${failed.join(', ')}`
    // The original error is rethrown whatever the restore did; the backup path is always printed.
    if (error instanceof Refusal) error.message += `; ${state}, backup in ${backup}`
    else console.error(`harness-update: the update failed; ${state}, backup in ${backup}`)
    throw error
  }

  console.log(text)
  if (dropped.length > 0) console.log(`removed:\n  ${dropped.join('\n  ')}`)
  const at = commit ? ` (${commit.slice(0, 7)})` : ''
  console.log(
    `\nharness-update: ${projectManifest.version} -> ${release.version}${at}; ` +
      `${files.length} files written, ${dropped.length} removed; backup in ${backup}`,
  )
}

function main() {
  let options
  try {
    options = parseArgs(process.argv.slice(2))
  } catch (error) {
    console.error(`harness-update: ${error.message}\n${USAGE}`)
    process.exit(2)
  }
  if (options.help) {
    console.log(USAGE)
    process.exit(0)
  }
  const root = resolve(options.root ?? join(dirname(fileURLToPath(import.meta.url)), '..'))
  try {
    let status
    try {
      status = git(root, ['status', '--porcelain'])
    } catch {
      throw new Refusal(`${root} is not a git repository`)
    }
    if (status.trim() !== '') {
      throw new Refusal('the working tree is dirty; commit or stash your changes first')
    }
    const current = loadManifest(root)
    const fetched = options.version ? fetchRelease(options.version, current.repository) : undefined
    update({ source: options.from, root, overwrite: options.overwrite, fetched })
  } catch (error) {
    if (!(error instanceof Refusal)) console.error(error.stack ?? error.message)
    else console.error(`harness-update: ${error.message}`)
    process.exit(1)
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main()
