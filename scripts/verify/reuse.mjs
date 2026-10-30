import { createHash } from 'node:crypto'
import { readFileSync, renameSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { git } from './git.mjs'

// The steps whose passing result a later run may reuse. `migrate` is not one of them: it
// prepares the database the e2e run uses, so it runs exactly when a testE2e step runs.
export const KEYED = ['contract', 'check', 'testDb', 'testE2e']
const RESULT_FILES = ['verify.json', 'verify-partial.json']
const MISSING = 'missing'
const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value)

const hashAt = (root, tree, file) => {
  const run = git(root, ['rev-parse', '--verify', '--quiet', `${tree}:${file}`])
  return run.ok ? run.out.trim() : MISSING
}

// The key covers tracked and untracked tree content only, not environment variables (e.g.
// `E2E_BASE_URL`, `NODE_OPTIONS`, `PYTEST_ADDOPTS`), git-ignored files the suites read (`.env*`)
// or installed toolchains and browsers. After changing any of them, run without `--reuse`.
// Builds `keyOf(pkg, name)` for one tree. `frontend` says which packages are not servers: the
// shared inputs include every server's contract file, which the frontend's types come from.
export function keyFactory(root, tree, packages, isFrontend, base) {
  const dirs = packages.map((pkg) => pkg.dir).sort()
  const subtree = Object.fromEntries(dirs.map((dir) => [dir, hashAt(root, tree, dir)]))
  const shared = [
    'docker-compose.yml',
    'db',
    '.fullstack/catalog.yaml',
    '.editorconfig',
    ...packages
      .filter((pkg) => !isFrontend(pkg))
      .map((pkg) => `${pkg.dir}/openapi.json`)
      .sort(),
  ]
  const digest = createHash('sha256')
  for (const file of shared) digest.update(`${file}=${hashAt(root, tree, file)}\n`)
  const sharedHash = digest.digest('hex')
  return (pkg, name) => {
    // The e2e config starts every server, so any package's change invalidates it.
    const own = name === 'testE2e' ? dirs : [pkg.dir]
    return {
      packages: Object.fromEntries(own.map((dir) => [dir, subtree[dir]])),
      shared: sharedHash,
      command: pkg.commands[name],
      base: base ?? null,
    }
  }
}

// A package missing from the tree would match `missing` forever, so such a key is never reusable.
export const completeKey = (key) => Object.values(key.packages).every((hash) => hash !== MISSING)

export const sameKey = (a, b) =>
  a !== undefined && b !== undefined && JSON.stringify(a) === JSON.stringify(b)

// The earlier results in the output directory; an unreadable or missing file is no source.
export function readSources(outDir) {
  const sources = []
  for (const file of RESULT_FILES) {
    try {
      const data = JSON.parse(readFileSync(path.join(outDir, file), 'utf8'))
      if (isObject(data) && isObject(data.packages)) sources.push({ file, data })
    } catch {
      // No such run yet, or a torn file.
    }
  }
  return sources
}

// The most recent passing, reusable step with an equal key, as `{ entry, file, finishedAt }`.
export function findReusable(sources, pkgDir, name, key) {
  let best
  for (const { file, data } of sources) {
    const entry = data.packages[pkgDir]?.[name]
    if (entry?.ok !== true || entry.reusable !== true || !sameKey(entry.key, key)) continue
    const finishedAt = entry.finishedAt ?? data.finishedAt ?? ''
    if (best === undefined || finishedAt > best.finishedAt) best = { entry, file, finishedAt }
  }
  return best
}

// The earlier partial file's step entries that `produced` (this run's packages) does not hold,
// marked carried, in whatever package they sit: a backend run, then a frontend run that only
// re-runs the server's `migrate`, still leaves the backend's other steps for a later full run.
export function carriedPackages(outDir, produced) {
  const carried = {}
  const earlier = readSources(outDir).find((source) => source.file === 'verify-partial.json')
  for (const [dir, steps] of Object.entries(earlier?.data.packages ?? {})) {
    if (!isObject(steps)) continue
    for (const [name, entry] of Object.entries(steps)) {
      if (!isObject(entry) || produced[dir]?.[name] !== undefined) continue
      ;(carried[dir] ??= {})[name] = { ...entry, carried: true }
    }
  }
  return carried
}

// Temp file, then rename: a reader sees the old file or the new one, never half of one.
export function writeJsonAtomic(file, value) {
  const temp = `${file}.${process.pid}.tmp`
  writeFileSync(temp, `${JSON.stringify(value, null, 2)}\n`)
  renameSync(temp, file)
}
