// The gate the dev loop branches on: contract freshness, check, testDb, testE2e, the diff
// checks and (full run) the README configuration table over one working tree, with a tree hash
// at both ends. Exit 0 pass, 1 fail, 2 usage or environment error.
// `node scripts/verify.mjs --plan <plan> [--package <dir>]... [--no-e2e] [--reuse]`, or
// `[--base <commit>] --out <dir>` outside the loop.
// With --reuse a passing step whose key (package subtree, shared inputs, command, Base) is
// unchanged is taken from an earlier result instead of re-run. A full run with a Base also
// writes review.diff; --round <n> --round-base <tree> adds review-fix-<n>.diff.
import { mkdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { readProvenance } from './provenance.mjs'
import { check as hitCheck, diffChecks } from './verify/checks.mjs'
import { addedLines, changedFiles, git, treeHash } from './verify/git.mjs'
import { isMain } from './verify/main.mjs'
import { portStatus, runCommand } from './verify/proc.mjs'
import { readmeCheck } from './verify/readme.mjs'
import {
  KEYED,
  carriedPackages,
  completeKey,
  findReusable,
  keyFactory,
  readSources,
  sameKey,
  writeJsonAtomic,
} from './verify/reuse.mjs'
import { writeReviewPackage } from './verify/review.mjs'
import { parseRetired, retiredHits } from './verify/retired.mjs'
import { securityFor } from './verify/security.mjs'
import { parseSummary, tail } from './verify/summary.mjs'

const MIN = 60_000
const TIMEOUTS = { contract: 3 * MIN, check: 10 * MIN, testDb: 15 * MIN, testE2e: 20 * MIN }
const USAGE =
  'usage: node scripts/verify.mjs --plan <plan> [--package <dir>]... [--no-e2e] [--reuse]\n' +
  '       node scripts/verify.mjs [--base <commit>] --out <dir> [--reuse]\n' +
  '       add --round <n> --round-base <tree> to a full run for a fix-round review package'

export function parseArgs(argv) {
  const options = { packages: [], noE2e: false, reuse: false }
  const takes = {
    '--plan': 'plan',
    '--base': 'base',
    '--out': 'out',
    '--root': 'root',
    '--round': 'round',
    '--round-base': 'roundBase',
  }
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    if (arg === '--package') options.packages.push(argv[++i])
    else if (arg in takes) options[takes[arg]] = argv[++i]
    else if (arg === '--no-e2e') options.noE2e = true
    else if (arg === '--reuse') options.reuse = true
    else throw new Error(`unknown argument ${arg}\n${USAGE}`)
  }
  if (options.packages.includes(undefined) || Object.values(options).includes(undefined)) {
    throw new Error(`a flag is missing its value\n${USAGE}`)
  }
  if (options.plan === undefined && options.out === undefined) throw new Error(USAGE)
  return options
}

// `Base:` is the first token after it, which must be a hex commit (a later word such as
// "defaced" is not one); `Branch:` the first word with a slash, usually in backticks. The slug is
// the branch after its first slash.
export function parsePlan(text) {
  const base = /^Base:[ \t]*`?([0-9a-f]{7,40})\b/m.exec(text)?.[1]
  const line = /^Branch:(.*)$/m.exec(text)?.[1] ?? ''
  const quoted = [...line.matchAll(/`([^`]+)`/g)].map((match) => match[1])
  const words = line.split(/\s+/).map((word) => word.replace(/[,.;]$/, ''))
  const branch = [...quoted, ...words].find((word) => /^[\w.-]+\/[\w./-]+$/.test(word))
  const slug = branch?.slice(branch.indexOf('/') + 1).replaceAll('/', '-')
  return { base, branch, slug }
}

function stepOutcome(name, run) {
  const counts = parseSummary(run.output)
  const reasons = []
  if (run.timedOut) reasons.push(`timed out after ${Math.round(run.limit / 1000)}s`)
  else if (run.exit !== 0) reasons.push(`exit ${run.exit}`)
  if (counts.failed > 0) reasons.push(`${counts.failed} failed`)
  if (counts.flaky > 0) reasons.push(`${counts.flaky} flaky`)
  if (name === 'testDb' && counts.skipped > 0) reasons.push(`${counts.skipped} skipped`)
  const ok = reasons.length === 0
  const step = { exit: run.exit, ...counts, ms: run.ms, log: ok ? null : tail(run.output), ok }
  if (!ok) step.reason = reasons.join(', ')
  // A failed process-table query only weakens orphan reaping, so it is recorded, not failed.
  if (run.reap !== undefined) step.reap = run.reap
  return step
}

export async function runVerify(options) {
  const root = path.resolve(options.root ?? process.cwd())
  const out = options.log ?? console.log
  const timeouts = { ...TIMEOUTS, ...options.timeouts }
  const docker = options.docker ?? 'docker'
  const platform = options.platform ?? process.platform
  const chosen = options.packages ?? []
  // A run narrowed by --package or --no-e2e must never stand in for the full gate under --reuse.
  const partial = chosen.length > 0 || options.noE2e === true
  const round = options.round === undefined ? undefined : String(options.round)
  const result = { startedAt: new Date().toISOString(), plan: options.plan, ok: false }
  // `--out` is known before the plan is read, so even an unreadable plan leaves its reason there.
  let outDir = options.out === undefined ? undefined : path.resolve(root, options.out)

  const finish = (exit, extra = {}) => {
    Object.assign(result, extra, { finishedAt: new Date().toISOString() })
    if (outDir !== undefined) {
      mkdirSync(outDir, { recursive: true })
      const file = partial ? 'verify-partial.json' : 'verify.json'
      if (partial && result.packages !== undefined) {
        const carried = carriedPackages(outDir, result.packages)
        const merged = {}
        for (const dir of new Set([...Object.keys(carried), ...Object.keys(result.packages)])) {
          merged[dir] = { ...carried[dir], ...result.packages[dir] }
        }
        result.packages = merged
      }
      writeJsonAtomic(path.join(outDir, file), result)
    }
    return { exit, result }
  }
  const fail2 = (reason) => finish(2, { reason, ok: false })

  let base = options.base
  let retired = []
  if (options.plan !== undefined) {
    let text
    try {
      text = readFileSync(path.resolve(root, options.plan), 'utf8')
    } catch {
      return fail2(`cannot read the plan ${options.plan}`)
    }
    const plan = parsePlan(text)
    retired = parseRetired(text)
    if (plan.slug === undefined) return fail2(`${options.plan} has no Branch: line with a slug`)
    outDir ??= path.resolve(root, path.join('.orchestrate', plan.slug))
    base ??= plan.base
  }
  result.base = base

  const catalog = readProvenance(path.join(root, '.fullstack', 'catalog.yaml'))
  if (catalog.packages.length === 0) return fail2('.fullstack/catalog.yaml lists no packages')
  for (const dir of chosen) {
    if (!catalog.packages.some((pkg) => pkg.dir === dir)) return fail2(`no package ${dir}`)
  }
  if (!git(root, ['rev-parse', '--git-dir']).ok) return fail2(`${root} is not a git repository`)
  const isCommit = () => git(root, ['rev-parse', '--verify', '--quiet', `${base}^{commit}`]).ok
  if (base !== undefined && !isCommit()) return fail2(`base ${base} is not a commit`)

  if ((round === undefined) !== (options.roundBase === undefined)) {
    return fail2('--round and --round-base go together')
  }
  if (round !== undefined) {
    if (base === undefined) return fail2('--round needs a base (a plan Base or --base)')
    if (!/^[1-9]\d*$/.test(round)) return fail2('--round must be a positive integer')
    if (partial) return fail2('--round needs a full run, without --package or --no-e2e')
    if (!git(root, ['rev-parse', '--verify', '--quiet', `${options.roundBase}^{tree}`]).ok) {
      return fail2(`round base ${options.roundBase} is not a tree or commit`)
    }
  }

  // Windows runs a command line through cmd, which stops at the first newline.
  if (platform === 'win32') {
    for (const pkg of catalog.packages) {
      if (chosen.length > 0 && !chosen.includes(pkg.dir)) continue
      for (const [name, line] of Object.entries(pkg.commands)) {
        if (!line.includes('\n')) continue
        return fail2(`${pkg.dir} ${name} is a multi-line command, which Windows cannot run`)
      }
    }
  }

  try {
    return await execute()
  } catch (error) {
    return fail2(`verify crashed: ${error.message}`)
  }

  async function execute() {
    const startTree = treeHash(root)
    // A fix round must write its package, so it never takes the whole-run shortcut.
    if (options.reuse && !partial && round === undefined) {
      try {
        const last = JSON.parse(readFileSync(path.join(outDir, 'verify.json'), 'utf8'))
        const same = last.base === base && last.plan === options.plan
        if (last.ok === true && last.tree === startTree && same) {
          out(`verify: PASS (unchanged since ${last.finishedAt})`)
          return { exit: 0, result: last, reused: true }
        }
      } catch {
        // No earlier run, or an unreadable one: run everything.
      }
    }

    Object.assign(result, { startTree, packages: {}, checks: [] })
    const isFrontend = (pkg) => pkg.template.startsWith('frontend/') || 'testE2e' in pkg.commands
    // The server goes first so its contract is regenerated before the frontend's types.
    const selected = catalog.packages
      .filter((pkg) => chosen.length === 0 || chosen.includes(pkg.dir))
      .sort((a, b) => Number(isFrontend(a)) - Number(isFrontend(b)))
    const has = (pkg, name) => name in pkg.commands
    // A partial run answers for its own packages; a sibling's concurrent edit is not its failure.
    const scope = partial ? selected.map((pkg) => pkg.dir) : undefined
    let failed = false

    const record = (label, ok, text) => {
      out(`${ok ? 'ok  ' : 'FAIL'} ${label.padEnd(24)} ${text}`)
      if (!ok) failed = true
    }
    const addCheck = (name, ok, detail = '') => {
      result.checks.push({ name, ok, detail })
      record(name, ok, detail)
    }
    const store = (pkg, name, outcome) => {
      const entry = (result.packages[pkg.dir] ??= {})
      entry[name] = outcome
    }
    // The keys come from the start tree; the end tree's must match for a result to be reusable.
    const startKey = keyFactory(root, startTree, catalog.packages, isFrontend, base)
    const sources = options.reuse ? readSources(outDir) : []
    const lookup = (pkg, name) => findReusable(sources, pkg.dir, name, startKey(pkg, name))
    const step = async (pkg, name, hit) => {
      if (hit !== undefined) {
        const reused = { file: hit.file, finishedAt: hit.finishedAt }
        const entry = { ...hit.entry, reused }
        delete entry.carried
        store(pkg, name, entry)
        const { passed, failed: bad, skipped, flaky } = hit.entry
        const counts = `${passed} passed, ${bad} failed, ${skipped} skipped`
        const note = `reused (${hit.file}, ${hit.finishedAt})`
        record(`${pkg.dir} ${name}`, true, `${counts}${flaky > 0 ? `, ${flaky} flaky` : ''}, ${note}`)
        return true
      }
      const limit = timeouts[name] ?? timeouts.check
      const cwd = path.join(root, pkg.dir)
      const run = await runCommand(pkg.commands[name], {
        cwd,
        timeout: limit,
        reap: options.reap,
        reapInterval: options.reapInterval,
      })
      const outcome = stepOutcome(name, { ...run, limit })
      if (KEYED.includes(name)) outcome.key = startKey(pkg, name)
      outcome.finishedAt = new Date().toISOString()
      store(pkg, name, outcome)
      const { passed, failed: bad, skipped } = outcome
      const counts = `${passed} passed, ${bad} failed, ${skipped} skipped`
      const flaky = outcome.flaky > 0 ? `, ${outcome.flaky} flaky` : ''
      const why = outcome.ok ? '' : ` (${outcome.reason})`
      const seconds = (outcome.ms / 1000).toFixed(1)
      record(`${pkg.dir} ${name}`, outcome.ok, `${counts}${flaky}, ${seconds}s${why}`)
      return outcome.ok
    }
    // A step that could not start: recorded as failed with the reason, no command run.
    const refuse = (pkg, name, reason) => {
      const none = { exit: null, passed: 0, failed: 0, skipped: 0, flaky: 0, ms: 0, log: null }
      store(pkg, name, { ...none, ok: false, reason })
      record(`${pkg.dir} ${name}`, false, reason)
    }

    // A step with nothing to run, for a command the template does not define.
    const skip = (pkg, name, reason) => {
      const none = { exit: null, passed: 0, failed: 0, skipped: 0, flaky: 0, ms: 0, log: null }
      store(pkg, name, { ...none, ok: true, reason })
      record(`${pkg.dir} ${name}`, true, reason)
    }

    // The database service is listed once, and started once, for testDb and the e2e migration.
    let listed
    const hasDatabase = async () => {
      listed ??= await runCommand(`${docker} compose config --services`, { cwd: root, timeout: MIN })
      return listed.exit === 0 && listed.output.split(/\s+/).includes('database')
    }
    // POSIX shells exit 127 for a missing command; cmd.exe says "not recognized".
    const dockerMissing = (run) =>
      run.exit === 127 || /not recognized|command not found|ENOENT/i.test(run.output)
    let database
    const ensureDatabase = async () => {
      if (database !== undefined) return database
      if (!(await hasDatabase())) {
        const reason = 'no database service in `docker compose config --services`'
        database = { ok: false, reason }
      } else {
        const up = await runCommand(`${docker} compose up -d --wait database`, {
          cwd: root,
          timeout: 5 * MIN,
        })
        database = up.exit === 0 ? { ok: true } : { ok: false, reason: tail(up.output, 5) }
      }
      addCheck('database', database.ok, database.reason ?? 'started')
      return database
    }

    const needsDocker =
      !partial ||
      selected.some((p) => has(p, 'testDb')) ||
      (!options.noE2e && selected.some((p) => has(p, 'testE2e')))
    if (needsDocker) {
      await hasDatabase()
      if (dockerMissing(listed)) return fail2('docker unavailable')
    }

    // Steps 2 to 5, in the plan's order.
    // The first failed contract or check decides the run, so the long suites are not started.
    let blocker
    for (const pkg of selected) {
      if (!has(pkg, 'contract')) skip(pkg, 'contract', 'skipped: no contract command')
      else if (!(await step(pkg, 'contract', lookup(pkg, 'contract')))) {
        blocker ??= `${pkg.dir} contract`
      }
    }
    if (selected.some((pkg) => has(pkg, 'contract'))) {
      const afterContract = treeHash(root)
      const stale =
        afterContract === startTree ? [] : changedFiles(root, startTree, afterContract, scope)
      addCheck('contract-fresh', stale.length === 0, stale.join(', '))
    }
    for (const pkg of selected) {
      if (has(pkg, 'check')) {
        if (!(await step(pkg, 'check', lookup(pkg, 'check')))) blocker ??= `${pkg.dir} check`
      } else if (!partial) {
        refuse(pkg, 'check', 'no check command in .fullstack/catalog.yaml')
        blocker ??= `${pkg.dir} check`
      }
    }
    const withDb = selected.filter((p) => has(p, 'testDb'))
    for (const pkg of withDb) {
      if (blocker !== undefined) refuse(pkg, 'testDb', `skipped: ${blocker} failed`)
      else if (lookup(pkg, 'testDb') !== undefined) await step(pkg, 'testDb', lookup(pkg, 'testDb'))
      else {
        const db = await ensureDatabase()
        if (db.ok) await step(pkg, 'testDb')
        else refuse(pkg, 'testDb', db.reason)
      }
    }
    // A database in the Compose file with no testDb command would leave its suites unrun.
    if (!partial && withDb.length === 0 && (await hasDatabase())) {
      addCheck('testdb-defined', false, 'the database service exists but no package has testDb')
    }
    const e2e = options.noE2e ? [] : selected.filter((pkg) => has(pkg, 'testE2e'))
    if (blocker !== undefined) {
      for (const pkg of e2e) refuse(pkg, 'testE2e', `skipped: ${blocker} failed`)
    } else if (e2e.length > 0) {
      // Reused e2e steps need no database, migration or free port; only a step that runs does.
      const pending = []
      for (const pkg of e2e) {
        const hit = lookup(pkg, 'testE2e')
        if (hit !== undefined) await step(pkg, 'testE2e', hit)
        else pending.push(pkg)
      }
      if (pending.length > 0) {
        let ready = true
        // Every server's migrate runs, not only the selected ones: a frontend-only run still
        // needs the backend's database migrated.
        // A server with `e2eDb` prepares its own database in the e2e chain, so its dev
        // migrate is skipped; a 1.x server without it keeps the step.
        for (const pkg of catalog.packages.filter((p) => !isFrontend(p) && has(p, 'migrate'))) {
          const db = await ensureDatabase()
          if (!db.ok) refuse(pkg, 'migrate', db.reason)
          else if (has(pkg, 'e2eDb')) skip(pkg, 'migrate', 'skipped: e2eDb prepares the e2e database')
          ready = db.ok && (has(pkg, 'e2eDb') || (await step(pkg, 'migrate'))) && ready
        }
        // Every package's port, not only the frontend's: the e2e config starts all the servers.
        const busy = []
        for (const other of catalog.packages.filter((pkg) => pkg.port !== undefined)) {
          const status = await portStatus(other.port)
          if (!status.busy) continue
          busy.push(`port ${other.port} (${other.dir}) is in use by PID ${status.pid ?? 'unknown'}`)
        }
        for (const pkg of pending) {
          if (busy.length > 0) refuse(pkg, 'testE2e', busy.join('; '))
          else if (ready) await step(pkg, 'testE2e')
        }
      }
    }

    // Steps 6 and 7 share one tree: the diff checks read it, and it must equal the start.
    const endTree = treeHash(root)
    if (base === undefined) addCheck('diff-checks', true, 'skipped: no base')
    else {
      for (const c of diffChecks(addedLines(root, base, endTree, scope))) {
        addCheck(c.name, c.ok, c.detail)
      }
    }
    if (retired.length > 0) {
      const dirs = (scope ?? catalog.packages.map((pkg) => pkg.dir)).filter(Boolean)
      try {
        const c = hitCheck('retired-terms', retiredHits(root, dirs, retired))
        addCheck(c.name, c.ok, c.detail)
      } catch (error) {
        addCheck('retired-terms', false, error.message)
      }
    }
    // A partial run is the implementers' run; they cannot write README.md, so only a full
    // run checks it.
    if (!partial) {
      const c = readmeCheck(root)
      addCheck(c.name, c.ok, c.detail)
    }
    const moved = endTree === startTree ? [] : changedFiles(root, startTree, endTree, scope)
    addCheck('tree-unchanged', moved.length === 0, moved.join(', '))

    // The security trigger is a property of the whole change, so only a full run states it.
    if (!partial && base !== undefined) {
      const files = changedFiles(root, base, endTree)
      const patch = git(root, ['diff', '--unified=0', '--no-color', '--no-renames', base, endTree])
      result.security = securityFor(files, patch)
    }
    // A step is reusable only if it passed and its inputs were the same when the run ended.
    const endKey = keyFactory(root, endTree, catalog.packages, isFrontend, base)
    for (const pkg of selected) {
      for (const name of KEYED) {
        const entry = result.packages[pkg.dir]?.[name]
        if (entry?.key === undefined) continue
        entry.reusable =
          entry.ok && completeKey(entry.key) && sameKey(entry.key, endKey(pkg, name))
      }
    }

    if (!partial && base !== undefined) {
      const fix = round === undefined ? undefined : { n: Number(round), base: options.roundBase }
      const names = writeReviewPackage(root, outDir, { base, tree: endTree, round: fix })
      result.review = names
      for (const name of names) out(`review: ${path.join(outDir, name)}`)
    }
    const done = finish(failed ? 1 : 0, { tree: endTree, ok: !failed })
    out(`verify: ${failed ? 'FAIL' : 'PASS'} ${endTree}`)
    return done
  }
}

if (isMain(import.meta.url, process.argv[1])) {
  let options
  try {
    options = parseArgs(process.argv.slice(2))
  } catch (error) {
    console.error(error.message)
    process.exit(2)
  }
  const { exit, result } = await runVerify(options)
  if (exit === 2) console.error(`verify: ${result.reason}`)
  process.exit(exit)
}
