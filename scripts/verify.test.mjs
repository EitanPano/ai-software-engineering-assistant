import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import net from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { after, describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'
import { renderConfiguration, replaceConfiguration } from './readme.mjs'
import { parseArgs, runVerify } from './verify.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const bases = []
// Every test builds its own fixture, so they run side by side to keep the file fast.
const tests = []
const test = (name, run) => tests.push([name, run])

// One stub drives every gate command: pass, fail, skip, flake, rewrite a file, or hang with a
// child. It logs each run outside the repository so a test can count what verify executed.
const STUB = `
import { spawn } from 'node:child_process'
import { appendFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
const [mode, file, text] = process.argv.slice(2)
appendFileSync(path.resolve(import.meta.dirname, '..', 'runs.log'), mode + '\\n')
if (mode === 'pass') console.log('3 pass\\n0 fail')
else if (mode === 'fail') { console.log('1 fail'); process.exit(1) }
else if (mode === 'skip') console.log('2 pass\\n1 skip\\n0 fail')
else if (mode === 'flaky') console.log('  3 passed (2s)\\n  1 flaky')
else if (mode === 'stable') writeFileSync(file, text)
else if (mode === 'write') writeFileSync(file, text + Date.now())
else if (mode === 'orphan') {
  // A detached grandchild that outlives this command, which lingers long enough to be seen.
  const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
    detached: true,
    stdio: 'ignore',
  })
  child.unref()
  writeFileSync(file, String(child.pid))
  setTimeout(() => {}, 1500)
} else if (mode === 'hang') {
  const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' })
  console.log('child ' + child.pid)
  setInterval(() => {}, 1000)
}
`

const DOCKER = `
import { appendFileSync, existsSync } from 'node:fs'
import path from 'node:path'
const args = process.argv.slice(2).join(' ')
appendFileSync(path.resolve(import.meta.dirname, '..', 'docker.log'), args + '\\n')
if (args === 'compose config --services') {
  const noDb = existsSync(path.resolve(import.meta.dirname, '..', 'no-db'))
  console.log(noDb ? 'backend' : 'backend\\ndatabase')
}
`

function git(cwd, ...args) {
  // The fsmonitor daemon would outlive the test and hold the fixture folder open.
  const config = ['-c', 'commit.gpgsign=false', '-c', 'core.fsmonitor=false']
  const run = spawnSync('git', [...config, ...args], { cwd, encoding: 'utf8' })
  assert.equal(run.status, 0, run.stderr)
  return run.stdout.trim()
}

// Where no PID lookup tool exists the reason says so instead of naming the PID.
const canFindPid =
  process.platform === 'win32' ||
  ['lsof', 'ss'].some((tool) => spawnSync(tool, ['-V'], { stdio: 'ignore' }).error === undefined)
const pidPattern = new RegExp(canFindPid ? `PID ${process.pid}\\b` : 'PID unknown')

// Tests run side by side, so a port is never handed out twice and comes from a block below the
// operating system's ephemeral range, where the port-0 listeners of the busy-port tests live.
let nextPort = 20000 + (process.pid % 500) * 10
async function freePort() {
  for (;;) {
    const port = nextPort++
    const free = await new Promise((resolve) => {
      const server = net.createServer()
      server.once('error', () => resolve(false))
      server.listen(port, '127.0.0.1', () => server.close(() => resolve(true)))
    })
    if (free) return port
  }
}

// A repository with a server package (`backend`) and a frontend, committed, with a plan whose
// Base is that commit. `commands` overrides one command of one package.
async function fixture({ commands = {}, ports, noDb = false, plan = true } = {}) {
  const base = mkdtempSync(path.join(tmpdir(), 'verify-'))
  bases.push(base)
  const root = path.join(base, 'repo')
  mkdirSync(path.join(root, 'backend'), { recursive: true })
  mkdirSync(path.join(root, 'frontend'), { recursive: true })
  mkdirSync(path.join(root, '.fullstack'))
  mkdirSync(path.join(root, '.plan'))
  const [backendPort, frontendPort] = ports ?? [await freePort(), await freePort()]
  const stub = (mode, ...rest) => `node ../stub.mjs ${mode} ${rest.join(' ')}`.trim()
  const defaults = {
    backend: {
      contract: stub('stable', '../backend/contract.json', 'v1'),
      check: stub('pass'),
      testDb: stub('pass'),
      migrate: stub('pass'),
    },
    frontend: { contract: stub('pass'), check: stub('pass'), testE2e: stub('pass') },
  }
  const lines = ['deploy: split', 'packages:']
  for (const [dir, template, port] of [
    ['frontend', 'frontend/react', frontendPort],
    ['backend', 'server/python-fastapi', backendPort],
  ]) {
    lines.push(`  ${dir}:`, `    template: ${template}`, '    http:', `      port: ${port}`)
    lines.push('    commands:')
    for (const [name, line] of Object.entries({ ...defaults[dir], ...commands[dir] })) {
      if (line === null) continue
      // The folded form is what the generator writes for a long command.
      const block = (style) => `${style}\n        ${line.replaceAll('\n', '\n        ')}`
      const value = name === 'testDb' ? block('>-') : line.includes('\n') ? block('|-') : line
      lines.push(`      ${name}: ${value}`)
    }
  }
  writeFileSync(path.join(root, '.fullstack', 'catalog.yaml'), `${lines.join('\n')}\n`)
  writeFileSync(path.join(root, 'stub.mjs'), STUB)
  writeFileSync(path.join(root, 'docker-stub.mjs'), DOCKER)
  writeFileSync(path.join(root, '.gitignore'), '.orchestrate/\n')
  // The generated Configuration table of a project with no example env files.
  const none = [
    '<!-- configuration:start -->',
    'This project reads no environment variables.',
    '<!-- configuration:end -->',
  ].join('\n')
  writeFileSync(path.join(root, 'README.md'), `# Fixture\n\n${none}\n`)
  writeFileSync(path.join(root, 'backend', 'contract.json'), 'v1')
  writeFileSync(path.join(root, 'backend', 'app.ts'), 'export const a = 1\n')
  writeFileSync(path.join(root, 'frontend', 'app.ts'), 'export const b = 1\n')
  if (noDb) writeFileSync(path.join(base, 'no-db'), '')
  git(root, 'init', '-q')
  git(root, 'config', 'user.email', 't@example.com')
  git(root, 'config', 'user.name', 't')
  git(root, 'add', '-A')
  git(root, 'commit', '-qm', 'init')
  const sha = git(root, 'rev-parse', '--short', 'HEAD')
  if (plan) {
    const text = `Branch: harness \`feat/lean-loop\`, cut from dev\nBase: ${sha} (\`dev\`)\n`
    writeFileSync(path.join(root, '.plan', '001-test.md'), text)
  }
  return { root, base, sha }
}

function opts(fx, extra = {}) {
  const lines = []
  return {
    lines,
    options: {
      root: fx.root,
      plan: '.plan/001-test.md',
      docker: `node "${path.join(fx.root, 'docker-stub.mjs')}"`,
      timeouts: { contract: 20000, check: 20000, testDb: 20000, testE2e: 20000 },
      // The process-table queries cost about 0.6 s a step on Windows; one test turns them on.
      reap: false,
      log: (line) => lines.push(line),
      ...extra,
    },
  }
}

const read = (fx, name = 'verify.json') =>
  JSON.parse(readFileSync(path.join(fx.root, '.orchestrate', 'lean-loop', name), 'utf8'))
const runs = (fx) =>
  existsSync(path.join(fx.base, 'runs.log'))
    ? readFileSync(path.join(fx.base, 'runs.log'), 'utf8').split('\n').filter(Boolean)
    : []

after(() => {
  for (const dir of bases) rmSync(dir, { recursive: true, force: true })
})

test('a clean fixture passes with exit 0 and records every step', async () => {
  const fx = await fixture()
  const { options, lines } = opts(fx)
  const { exit } = await runVerify(options)
  const result = read(fx)
  assert.equal(exit, 0)
  assert.equal(result.ok, true)
  assert.equal(result.tree, result.startTree)
  assert.equal(result.base, fx.sha)
  for (const step of ['contract', 'check', 'testDb', 'migrate']) {
    assert.equal(result.packages.backend[step].exit, 0, step)
  }
  assert.equal(result.packages.backend.check.passed, 3)
  assert.equal(result.packages.frontend.testE2e.exit, 0)
  assert.ok(result.checks.every((check) => check.ok))
  assert.match(lines.at(-1), /^verify: PASS [0-9a-f]{40}$/)
  assert.ok(lines.some((line) => /^ok\s+backend check/.test(line)))
})

test('a failing check fails with the step and the log tail', async () => {
  const fx = await fixture({ commands: { backend: { check: 'node ../stub.mjs fail' } } })
  const { options, lines } = opts(fx)
  const { exit } = await runVerify(options)
  const result = read(fx)
  assert.equal(exit, 1)
  assert.equal(result.ok, false)
  assert.equal(result.packages.backend.check.exit, 1)
  assert.equal(result.packages.backend.check.failed, 1)
  assert.match(result.packages.backend.check.log, /1 fail/)
  assert.match(lines.at(-1), /^verify: FAIL /)
  assert.ok(lines.some((line) => /^FAIL\s+backend check/.test(line)))
})

test('a skipped testDb suite fails, a skipped check suite does not', async () => {
  const fx = await fixture({
    commands: { backend: { testDb: 'node ../stub.mjs skip', check: 'node ../stub.mjs skip' } },
  })
  const { exit } = await runVerify(opts(fx).options)
  const result = read(fx)
  assert.equal(exit, 1)
  assert.equal(result.packages.backend.testDb.skipped, 1)
  assert.equal(result.packages.backend.testDb.ok, false)
  assert.match(result.packages.backend.testDb.reason, /skipped/)
  assert.equal(result.packages.backend.check.ok, true)
})

test('a Playwright flaky count fails the step', async () => {
  const fx = await fixture({ commands: { frontend: { testE2e: 'node ../stub.mjs flaky' } } })
  const { exit } = await runVerify(opts(fx).options)
  const result = read(fx)
  assert.equal(exit, 1)
  assert.equal(result.packages.frontend.testE2e.exit, 0)
  assert.equal(result.packages.frontend.testE2e.flaky, 1)
  assert.equal(result.packages.frontend.testE2e.ok, false)
})

test('a stale contract fails and names the rewritten file', async () => {
  const fx = await fixture()
  writeFileSync(path.join(fx.root, 'backend', 'contract.json'), 'hand edited')
  git(fx.root, 'commit', '-qam', 'stale')
  const { exit } = await runVerify(opts(fx).options)
  const check = read(fx).checks.find((entry) => entry.name === 'contract-fresh')
  assert.equal(exit, 1)
  assert.equal(check.ok, false)
  assert.match(check.detail, /backend\/contract\.json/)
})

test('an added .only fails the diff checks, naming file and line', async () => {
  const fx = await fixture()
  writeFileSync(path.join(fx.root, 'backend', 'app.test.ts'), 'export const a = 1\ntest.only("x")\n')
  const { exit } = await runVerify(opts(fx).options)
  const check = read(fx).checks.find((entry) => entry.name === 'no-focused-or-skipped-test')
  assert.equal(exit, 1)
  assert.equal(check.ok, false)
  assert.match(check.detail, /backend\/app\.test\.ts:2/)
})

test('an untracked file with a skip is found too, and a python skip', async () => {
  const fx = await fixture()
  writeFileSync(path.join(fx.root, 'frontend', 'new.test.ts'), 'it.skip("x", () => {})\n')
  writeFileSync(path.join(fx.root, 'backend', 'test_a.py'), '@pytest.mark.skipif(True)\n')
  const { exit } = await runVerify(opts(fx).options)
  const check = read(fx).checks.find((entry) => entry.name === 'no-focused-or-skipped-test')
  assert.equal(exit, 1)
  assert.match(check.detail, /frontend\/new\.test\.ts:1/)
  assert.match(check.detail, /backend\/test_a\.py:1/)
})

test('an axe .exclude( in an e2e spec fails, in another file it does not', async () => {
  const fx = await fixture()
  mkdirSync(path.join(fx.root, 'frontend', 'e2e'))
  writeFileSync(path.join(fx.root, 'frontend', 'app.ts'), 'list.exclude(1)\n')
  const clean = await runVerify(opts(fx).options)
  assert.equal(clean.exit, 0)
  writeFileSync(path.join(fx.root, 'frontend', 'e2e', 'a11y.spec.ts'), 'axe.exclude(".x")\n')
  const { exit } = await runVerify(opts(fx).options)
  const check = read(fx).checks.find((entry) => entry.name === 'no-axe-exclude')
  assert.equal(exit, 1)
  assert.match(check.detail, /frontend\/e2e\/a11y\.spec\.ts:1/)
})

test('a gate that rewrites a tracked file fails and lists it', async () => {
  const fx = await fixture({
    commands: { frontend: { check: 'node ../stub.mjs write ../backend/app.ts export' } },
  })
  const { exit } = await runVerify(opts(fx).options)
  const result = read(fx)
  const check = result.checks.find((entry) => entry.name === 'tree-unchanged')
  assert.equal(exit, 1)
  assert.notEqual(result.tree, result.startTree)
  assert.equal(check.ok, false)
  assert.match(check.detail, /backend\/app\.ts/)
})

test('a step past its timeout fails and the child it spawned is gone', async () => {
  const fx = await fixture({ commands: { backend: { check: 'node ../stub.mjs hang' } } })
  const { options } = opts(fx, { timeouts: { check: 3000, contract: 20000, testDb: 20000 } })
  const started = Date.now()
  const { exit } = await runVerify(options)
  const step = read(fx).packages.backend.check
  assert.equal(exit, 1)
  assert.ok(Date.now() - started < 15000)
  assert.equal(step.ok, false)
  assert.match(step.reason, /timed out/)
  const pid = Number(/child (\d+)/.exec(step.log)[1])
  assert.throws(() => process.kill(pid, 0), /ESRCH/)
})

test('a missing database service fails testDb with the reason and starts nothing', async () => {
  const fx = await fixture({ noDb: true })
  const { exit } = await runVerify(opts(fx).options)
  const result = read(fx)
  const docker = readFileSync(path.join(fx.base, 'docker.log'), 'utf8')
  assert.equal(exit, 1)
  assert.equal(result.packages.backend.testDb.ok, false)
  assert.match(result.packages.backend.testDb.reason, /database/)
  assert.doesNotMatch(docker, /up -d/)
})

test('the database is started once, before testDb and migrate', async () => {
  const fx = await fixture()
  await runVerify(opts(fx).options)
  const docker = readFileSync(path.join(fx.base, 'docker.log'), 'utf8').split('\n').filter(Boolean)
  assert.deepEqual(docker, ['compose config --services', 'compose up -d --wait database'])
})

test('--reuse on an unchanged passing tree runs nothing, on a changed tree runs everything', async () => {
  const fx = await fixture()
  const index = readFileSync(path.join(fx.root, '.git', 'index'))
  assert.equal((await runVerify(opts(fx).options)).exit, 0)
  const ran = runs(fx).length
  const again = opts(fx, { reuse: true })
  const reused = await runVerify(again.options)
  assert.equal(reused.exit, 0)
  assert.equal(runs(fx).length, ran)
  assert.match(again.lines.at(-1), /^verify: PASS \(unchanged since \d{4}-/)
  writeFileSync(path.join(fx.root, 'backend', 'app.ts'), 'export const a = 2\n')
  assert.equal((await runVerify(opts(fx, { reuse: true }).options)).exit, 0)
  assert.ok(runs(fx).length > ran)
  assert.deepEqual(readFileSync(path.join(fx.root, '.git', 'index')), index)
  assert.equal(git(fx.root, 'stash', 'list'), '')
})

test('--reuse does not skip a run whose last result failed', async () => {
  const fx = await fixture({ commands: { backend: { check: 'node ../stub.mjs fail' } } })
  assert.equal((await runVerify(opts(fx).options)).exit, 1)
  const ran = runs(fx).length
  assert.equal((await runVerify(opts(fx, { reuse: true }).options)).exit, 1)
  assert.ok(runs(fx).length > ran)
})

test('a partial run writes verify-partial.json and never satisfies --reuse', async () => {
  const fx = await fixture()
  const partial = await runVerify(opts(fx, { packages: ['backend'] }).options)
  assert.equal(partial.exit, 0)
  const result = read(fx, 'verify-partial.json')
  assert.deepEqual(Object.keys(result.packages), ['backend'])
  assert.equal(existsSync(path.join(fx.root, '.orchestrate', 'lean-loop', 'verify.json')), false)
  const ran = runs(fx).length
  // Its passing steps are reused per package, but it still leaves no verify.json behind.
  assert.equal((await runVerify(opts(fx, { packages: ['backend'], reuse: true }).options)).exit, 0)
  assert.equal(runs(fx).length, ran)
  assert.ok(read(fx, 'verify-partial.json').packages.backend.check.reused)
  assert.equal(existsSync(path.join(fx.root, '.orchestrate', 'lean-loop', 'verify.json')), false)
  assert.equal((await runVerify(opts(fx, { reuse: true }).options)).exit, 0)
  assert.ok(existsSync(path.join(fx.root, '.orchestrate', 'lean-loop', 'verify.json')))
  const noE2e = await runVerify(opts(fx, { noE2e: true }).options)
  assert.equal(noE2e.exit, 0)
  assert.equal(read(fx, 'verify-partial.json').packages.frontend.testE2e, undefined)
})

test('a busy port fails the e2e step with the PID and leaves the listener alone', async () => {
  const fx = await fixture()
  const server = net.createServer()
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const { port } = server.address()
  try {
    const busy = await fixture({
      ports: [port, await freePort()],
      commands: { frontend: { testE2e: 'node ../stub.mjs marker' } },
    })
    const { exit } = await runVerify(opts(busy).options)
    const step = read(busy).packages.frontend.testE2e
    assert.equal(exit, 1)
    assert.equal(step.ok, false)
    assert.match(step.reason, new RegExp(`port ${port}.*${pidPattern.source}`))
    assert.ok(!runs(busy).includes('marker'))
    const probe = await new Promise((resolve) => {
      const socket = net.connect(port, '127.0.0.1')
      socket.on('connect', () => (socket.destroy(), resolve(true)))
      socket.on('error', () => resolve(false))
    })
    assert.equal(probe, true)
  } finally {
    await new Promise((resolve) => server.close(resolve))
  }
  assert.equal((await runVerify(opts(fx).options)).exit, 0)
})

test('--no-e2e skips migrate and the port check', async () => {
  const fx = await fixture()
  const { exit } = await runVerify(opts(fx, { noE2e: true }).options)
  assert.equal(exit, 0)
  assert.equal(read(fx, 'verify-partial.json').packages.backend.migrate, undefined)
})

test('a repository with no base records the diff checks as skipped', async () => {
  const fx = await fixture({ plan: false })
  const out = path.join(fx.root, '.orchestrate', 'lean-loop')
  const { exit } = await runVerify({ ...opts(fx).options, plan: undefined, out })
  const check = read(fx).checks.find((entry) => entry.name === 'diff-checks')
  assert.equal(exit, 0)
  assert.equal(check.ok, true)
  assert.equal(check.detail, 'skipped: no base')
})

test('usage and environment errors exit 2 and write the reason', async () => {
  const fx = await fixture()
  rmSync(path.join(fx.root, '.fullstack'), { recursive: true, force: true })
  const { exit, result } = await runVerify(opts(fx).options)
  assert.equal(exit, 2)
  assert.match(result.reason, /catalog/)
  assert.equal(read(fx).reason, result.reason)
  assert.equal(read(fx).ok, false)
  const noPlanBranch = await fixture()
  writeFileSync(path.join(noPlanBranch.root, '.plan', '001-test.md'), 'Base: abc1234\n')
  assert.match((await runVerify(opts(noPlanBranch).options)).result.reason, /Branch/)
  const unknown = await fixture()
  const pkg = await runVerify(opts(unknown, { packages: ['nope'] }).options)
  assert.equal(pkg.exit, 2)
  assert.match(pkg.result.reason, /nope/)
})

test('the CLI exits 0 on a pass and 2 without a plan or out', async () => {
  const fx = await fixture()
  const script = path.join(here, 'verify.mjs')
  const bad = spawnSync(process.execPath, [script], { cwd: fx.root, encoding: 'utf8' })
  assert.equal(bad.status, 2)
  assert.match(bad.stderr, /usage/)
  const ok = spawnSync(
    process.execPath,
    [script, '--plan', '.plan/001-test.md', '--package', 'frontend', '--no-e2e'],
    { cwd: fx.root, encoding: 'utf8' },
  )
  assert.equal(ok.status, 0, ok.stdout + ok.stderr)
  assert.match(ok.stdout, /verify: PASS/)
})

test('a full run fails when a package has no check command', async () => {
  const fx = await fixture({ commands: { frontend: { check: null } } })
  const { exit } = await runVerify(opts(fx).options)
  const step = read(fx).packages.frontend.check
  assert.equal(exit, 1)
  assert.equal(step.ok, false)
  assert.match(step.reason, /no check command/)
})

test('a partial run keeps passing when a package has no check command', async () => {
  const fx = await fixture({ commands: { frontend: { check: null } } })
  const partial = opts(fx, { packages: ['frontend'], noE2e: true })
  assert.equal((await runVerify(partial.options)).exit, 0)
})

test('a package without a contract command is skipped, not failed', async () => {
  const fx = await fixture({ commands: { frontend: { contract: null } } })
  const { exit } = await runVerify(opts(fx).options)
  const step = read(fx).packages.frontend.contract
  assert.equal(exit, 0)
  assert.equal(step.ok, true)
  assert.match(step.reason, /skipped: no contract command/)
})

test('a full run fails when the database service exists and no package has testDb', async () => {
  const fx = await fixture({ commands: { backend: { testDb: null } } })
  const { exit } = await runVerify(opts(fx).options)
  const check = read(fx).checks.find((entry) => entry.name === 'testdb-defined')
  assert.equal(exit, 1)
  assert.equal(check.ok, false)
  const none = { testDb: null, migrate: null }
  const noDb = await fixture({ commands: { backend: none }, noDb: true })
  assert.equal((await runVerify(opts(noDb).options)).exit, 0)
})

test('--reuse re-runs when the Base or the plan changed on the same tree', async () => {
  const fx = await fixture()
  const planFile = path.join(fx.root, '.plan', '001-test.md')
  const copy = path.join(fx.root, '.plan', '002-test.md')
  writeFileSync(copy, readFileSync(planFile, 'utf8'))
  const reuse = (extra) => runVerify(opts(fx, { reuse: true, ...extra }).options)
  assert.equal((await reuse({ plan: '.plan/001-test.md' })).exit, 0)
  const ran = runs(fx).length
  await reuse({ plan: '.plan/001-test.md' })
  assert.equal(runs(fx).length, ran, 'same tree, base and plan: reused')
  await reuse({ plan: '.plan/001-test.md', base: git(fx.root, 'rev-parse', 'HEAD') })
  assert.ok(runs(fx).length > ran, 'a changed Base re-runs')
  const again = runs(fx).length
  await reuse({ plan: '.plan/002-test.md' })
  assert.ok(runs(fx).length > again, 'a different plan re-runs')
})

test('exit 2 with an unreadable plan still writes the JSON to --out', async () => {
  const fx = await fixture()
  const out = path.join(fx.root, '.orchestrate', 'elsewhere')
  const { exit, result } = await runVerify({ ...opts(fx).options, plan: '.plan/nope.md', out })
  assert.equal(exit, 2)
  const written = JSON.parse(readFileSync(path.join(out, 'verify.json'), 'utf8'))
  assert.equal(written.reason, result.reason)
  const none = await runVerify({ ...opts(fx).options, plan: '.plan/nope.md' })
  assert.equal(none.exit, 2)
  assert.equal(existsSync(path.join(fx.root, '.orchestrate', 'lean-loop')), false)
})

test('a failed check skips testDb and testE2e, the diff checks and end tree still run', async () => {
  const fx = await fixture({ commands: { backend: { check: 'node ../stub.mjs fail' } } })
  const { exit } = await runVerify(opts(fx).options)
  const result = read(fx)
  assert.equal(exit, 1)
  for (const [dir, step] of [
    ['backend', 'testDb'],
    ['frontend', 'testE2e'],
  ]) {
    assert.equal(result.packages[dir][step].ok, false)
    assert.match(result.packages[dir][step].reason, /skipped: backend check failed/)
  }
  assert.equal(result.packages.backend.migrate, undefined)
  assert.ok(result.checks.some((entry) => entry.name === 'tree-unchanged'))
  assert.ok(result.checks.some((entry) => entry.name === 'no-axe-exclude'))
  // contract x2 and check x2 ran; testDb, migrate and the e2e command did not.
  assert.equal(runs(fx).length, 4)
})

test('a failed contract step also skips the expensive steps', async () => {
  const fx = await fixture({ commands: { backend: { contract: 'node ../stub.mjs fail' } } })
  assert.equal((await runVerify(opts(fx).options)).exit, 1)
  assert.match(read(fx).packages.backend.testDb.reason, /skipped: backend contract failed/)
})

test('a dirty tree and an untracked file leave the real index and stash alone', async () => {
  const fx = await fixture()
  writeFileSync(path.join(fx.root, 'backend', 'app.ts'), 'export const a = 3\n')
  writeFileSync(path.join(fx.root, 'backend', 'fresh.ts'), 'export const f = 1\n')
  const index = readFileSync(path.join(fx.root, '.git', 'index'))
  assert.equal((await runVerify(opts(fx).options)).exit, 0)
  assert.deepEqual(readFileSync(path.join(fx.root, '.git', 'index')), index)
  assert.equal(git(fx.root, 'stash', 'list'), '')
})

test('a grandchild left behind by a normal exit is reaped', async (t) => {
  if (process.platform !== 'win32') return t.skip('POSIX reaps through the process group')
  const fx = await fixture({
    commands: { backend: { check: 'node ../stub.mjs orphan ../../orphan.pid' } },
  })
  let pid
  try {
    const { exit } = await runVerify(opts(fx, { reap: true, reapInterval: 300 }).options)
    pid = Number(readFileSync(path.join(fx.base, 'orphan.pid'), 'utf8'))
    assert.equal(exit, 0)
    assert.throws(() => process.kill(pid, 0), /ESRCH/)
  } finally {
    try {
      process.kill(pid, 'SIGKILL')
    } catch {
      // Already gone, as it should be.
    }
  }
})

test('a busy IPv6 loopback port names the PID', async (t) => {
  const server = net.createServer()
  const listening = await new Promise((resolve) => {
    server.once('error', () => resolve(false))
    server.listen(0, '::1', () => resolve(true))
  })
  if (!listening) return t.skip('no IPv6 loopback on this host')
  try {
    const { port } = server.address()
    const busy = await fixture({ ports: [port, await freePort()] })
    await runVerify(opts(busy).options)
    const reason = read(busy).packages.frontend.testE2e.reason
    assert.match(reason, pidPattern)
  } finally {
    await new Promise((resolve) => server.close(resolve))
  }
})

test('the CLI runs through a directory link instead of exiting 0 silently', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'verify-link-'))
  bases.push(dir)
  const link = path.join(dir, 'scripts')
  symlinkSync(here, link, 'junction')
  const run = spawnSync(process.execPath, [path.join(link, 'verify.mjs')], { encoding: 'utf8' })
  assert.equal(run.status, 2)
  assert.match(run.stderr, /usage/)
})

test('a partial run ignores an edit outside its package and fails on one inside', async () => {
  const outside = await fixture({
    commands: { backend: { contract: 'node ../stub.mjs write ../frontend/app.ts export' } },
  })
  const partial = opts(outside, { packages: ['backend'], noE2e: true })
  assert.equal((await runVerify(partial.options)).exit, 0)
  const checks = read(outside, 'verify-partial.json').checks
  assert.ok(checks.every((entry) => entry.ok))
  const inside = await fixture({
    commands: { backend: { contract: 'node ../stub.mjs write ../backend/app.ts export' } },
  })
  const bad = opts(inside, { packages: ['backend'], noE2e: true })
  assert.equal((await runVerify(bad.options)).exit, 1)
  const names = read(inside, 'verify-partial.json').checks.filter((entry) => !entry.ok)
  assert.ok(names.some((entry) => entry.name === 'contract-fresh'))
  const full = await fixture({
    commands: { backend: { contract: 'node ../stub.mjs write ../frontend/app.ts export' } },
  })
  assert.equal((await runVerify(opts(full).options)).exit, 1)
})

test('a partial diff check reads only the selected packages', async () => {
  const fx = await fixture()
  writeFileSync(path.join(fx.root, 'frontend', 'a.test.ts'), 'it.only("x", f)\n')
  const partial = opts(fx, { packages: ['backend'], noE2e: true })
  assert.equal((await runVerify(partial.options)).exit, 0)
  assert.equal((await runVerify(opts(fx).options)).exit, 1)
})

test('a frontend-only e2e run still starts the database and migrates the server', async () => {
  const fx = await fixture({ commands: { backend: { migrate: 'node ../stub.mjs marker' } } })
  const { exit } = await runVerify(opts(fx, { packages: ['frontend'] }).options)
  const docker = readFileSync(path.join(fx.base, 'docker.log'), 'utf8')
  assert.equal(exit, 0)
  assert.ok(runs(fx).includes('marker'))
  assert.match(docker, /up -d --wait database/)
  assert.equal(read(fx, 'verify-partial.json').packages.backend.migrate.ok, true)
})

test('a missing docker is an environment error, exit 2', async () => {
  const fx = await fixture()
  const { exit, result } = await runVerify(opts(fx, { docker: 'no-such-docker-binary-xyz' }).options)
  assert.equal(exit, 2)
  assert.equal(result.reason, 'docker unavailable')
  assert.equal(read(fx).reason, 'docker unavailable')
})

test('on Windows a multi-line command is refused with exit 2', async () => {
  const fx = await fixture({ commands: { backend: { check: 'node ../stub.mjs pass\nnode ../stub.mjs fail' } } })
  const win = await runVerify(opts(fx, { platform: 'win32' }).options)
  assert.equal(win.exit, 2)
  assert.match(win.result.reason, /backend check.*multi-line/)
  assert.equal(runs(fx).length, 0)
  assert.notEqual((await runVerify(opts(fx, { platform: 'linux' }).options)).exit, 2)
})

test('a full run records whether the change touches security paths', async () => {
  const fx = await fixture()
  await runVerify(opts(fx).options)
  assert.deepEqual(read(fx).security, { triggered: false, paths: [] })
  mkdirSync(path.join(fx.root, 'backend', 'auth'))
  writeFileSync(path.join(fx.root, 'backend', 'auth', 'gate.ts'), 'export const g = 1\n')
  writeFileSync(path.join(fx.root, 'frontend', 'app.ts'), 'export const b = 2\n')
  await runVerify(opts(fx).options)
  assert.deepEqual(read(fx).security, { triggered: true, paths: ['backend/auth/gate.ts'] })
  await runVerify(opts(fx, { packages: ['backend'], noE2e: true }).options)
  assert.equal(read(fx, 'verify-partial.json').security, undefined)
})

const withRetired = (fx, line) =>
  writeFileSync(
    path.join(fx.root, '.plan', '001-test.md'),
    'Branch: harness `feat/lean-loop`, cut from dev\nBase: ' + fx.sha + '\n' + line + '\n',
  )
const retiredCheck = (fx, name = 'verify.json') => read(fx, name).checks.find((c) => c.name === 'retired-terms')

test('retired-terms fails on a leftover in package source and in AGENTS.md', async () => {
  const fx = await fixture()
  withRetired(fx, 'Retired: `OldName`, `legacy_x`')
  writeFileSync(path.join(fx.root, 'backend', 'app.ts'), 'export const a = oldname\n')
  writeFileSync(path.join(fx.root, 'frontend', 'AGENTS.md'), '# x\nuse legacy_x here\n')
  const { exit } = await runVerify(opts(fx).options)
  const check = retiredCheck(fx)
  assert.equal(exit, 1)
  assert.equal(check.ok, false)
  assert.match(check.detail, /backend\/app\.ts:1/)
  assert.match(check.detail, /frontend\/AGENTS\.md:2/)
})

test('retired-terms passes when the only hit is in a migration, the plan or .orchestrate', async () => {
  const fx = await fixture()
  withRetired(fx, 'Retired: `OldName`')
  mkdirSync(path.join(fx.root, 'backend', 'migrations'))
  writeFileSync(path.join(fx.root, 'backend', 'migrations', '0002_drop.ts'), 'OldName\n')
  writeFileSync(path.join(fx.root, 'backend', '0003.sql'), 'drop table OldName;\n')
  const { exit } = await runVerify(opts(fx).options)
  assert.equal(exit, 0)
  assert.equal(retiredCheck(fx).ok, true)
})

test('retired-terms does not run without a Retired: term', async () => {
  const fx = await fixture()
  writeFileSync(path.join(fx.root, 'backend', 'app.ts'), 'OldName\n')
  for (const line of ['Retired: none', 'Retired: nothing quoted', '']) {
    withRetired(fx, line)
    assert.equal((await runVerify(opts(fx).options)).exit, 0)
    assert.equal(retiredCheck(fx), undefined)
  }
})

test('a partial run scans only its own packages for retired terms', async () => {
  const fx = await fixture()
  withRetired(fx, 'Retired: `OldName`')
  writeFileSync(path.join(fx.root, 'backend', 'app.ts'), 'OldName\n')
  const mine = opts(fx, { packages: ['frontend'], noE2e: true })
  assert.equal((await runVerify(mine.options)).exit, 0)
  assert.equal(retiredCheck(fx, 'verify-partial.json').ok, true)
  const theirs = opts(fx, { packages: ['backend'], noE2e: true })
  assert.equal((await runVerify(theirs.options)).exit, 1)
  assert.equal(retiredCheck(fx, 'verify-partial.json').ok, false)
})

test('a swallowed assertion fails the diff checks on a test path', async () => {
  const fx = await fixture()
  mkdirSync(path.join(fx.root, 'frontend', 'tests'))
  const line = 'await expect(x).toBeFocused().catch(() => undefined)\n'
  writeFileSync(path.join(fx.root, 'frontend', 'app.ts'), line)
  assert.equal((await runVerify(opts(fx).options)).exit, 0)
  writeFileSync(path.join(fx.root, 'frontend', 'tests', 'a.test.ts'), line)
  const { exit } = await runVerify(opts(fx).options)
  const check = read(fx).checks.find((entry) => entry.name === 'no-swallowed-assertion')
  assert.equal(exit, 1)
  assert.match(check.detail, /frontend\/tests\/a\.test\.ts:1/)
})

test('a server with e2eDb skips the dev migrate before e2e, one without keeps it', async () => {
  const marker = 'node ../stub.mjs marker'
  const fx = await fixture({ commands: { backend: { migrate: marker, e2eDb: 'node ../stub.mjs prep' } } })
  const { exit } = await runVerify(opts(fx).options)
  assert.equal(exit, 0)
  assert.equal(runs(fx).includes('marker'), false)
  assert.equal(read(fx).packages.backend.migrate.ok, true)
  assert.match(read(fx).packages.backend.migrate.reason, /e2eDb/)
  const old = await fixture({ commands: { backend: { migrate: marker } } })
  await runVerify(opts(old).options)
  assert.ok(runs(old).includes('marker'))
})

test('a gate line in a changed file triggers the security review, a login form alone does not', async () => {
  const fx = await fixture()
  mkdirSync(path.join(fx.root, 'backend', 'api'))
  mkdirSync(path.join(fx.root, 'frontend', 'feature', 'auth', 'ui'), { recursive: true })
  writeFileSync(path.join(fx.root, 'frontend', 'feature', 'auth', 'ui', 'login-form.tsx'), 'export const f = 1\n')
  await runVerify(opts(fx).options)
  assert.equal(read(fx).security.triggered, false)
  writeFileSync(path.join(fx.root, 'backend', 'api', 'routes.ts'), 'router.use(requireRole(admin))\n')
  await runVerify(opts(fx).options)
  assert.deepEqual(read(fx).security, { triggered: true, paths: ['backend/api/routes.ts'] })
})

// Reuse tests: `lines` are the log lines of a run, `reusedLines` the steps it took from a file.
const reusedLines = (lines) => lines.filter((line) => line.includes('reused ('))
const stepLine = (lines, label) => lines.find((line) => line.includes(label))
const outDir = (fx) => path.join(fx.root, '.orchestrate', 'lean-loop')

test('a partial backend run and a partial frontend run are both reused by the full run', async () => {
  const fx = await fixture()
  assert.equal((await runVerify(opts(fx, { packages: ['backend'], noE2e: true }).options)).exit, 0)
  assert.equal((await runVerify(opts(fx, { packages: ['frontend'], noE2e: true }).options)).exit, 0)
  const partial = read(fx, 'verify-partial.json')
  assert.deepEqual(Object.keys(partial.packages).sort(), ['backend', 'frontend'])
  assert.equal(partial.packages.backend.check.carried, true)
  assert.equal(partial.packages.frontend.check.carried, undefined)
  const ran = runs(fx).length
  const full = opts(fx, { reuse: true })
  assert.equal((await runVerify(full.options)).exit, 0)
  // Only testE2e (and the migrate it needs) ran; every other step came from the partial file.
  assert.equal(runs(fx).length - ran, 2)
  assert.equal(reusedLines(full.lines).length, 5)
  assert.match(stepLine(full.lines, 'backend check'), /reused \(verify-partial\.json, \d{4}-/)
  const result = read(fx)
  assert.equal(result.packages.backend.check.reused.file, 'verify-partial.json')
  assert.equal(result.packages.backend.check.reusable, true)
  assert.ok(result.packages.backend.check.key)
  assert.equal(result.packages.frontend.testE2e.reused, undefined)
})

test('a frontend e2e partial run keeps the backend partial steps and adds migrate', async () => {
  const fx = await fixture()
  assert.equal((await runVerify(opts(fx, { packages: ['backend'], reuse: true }).options)).exit, 0)
  assert.equal((await runVerify(opts(fx, { packages: ['frontend'], reuse: true }).options)).exit, 0)
  const { backend } = read(fx, 'verify-partial.json').packages
  for (const name of ['contract', 'check', 'testDb']) assert.equal(backend[name].carried, true)
  assert.equal(backend.migrate.ok, true)
  assert.equal(backend.migrate.carried, undefined)
  const ran = runs(fx).length
  const full = opts(fx, { reuse: true })
  assert.equal((await runVerify(full.options)).exit, 0)
  for (const name of ['contract', 'check', 'testDb']) {
    assert.match(stepLine(full.lines, `backend ${name}`), /reused \(verify-partial\.json/)
  }
  assert.ok(runs(fx).length >= ran)
})

test('a --no-e2e frontend run keeps the earlier testE2e entry, reused only on a matching key', async () => {
  const fx = await fixture()
  assert.equal((await runVerify(opts(fx, { packages: ['frontend'] }).options)).exit, 0)
  assert.equal((await runVerify(opts(fx, { packages: ['frontend'], noE2e: true }).options)).exit, 0)
  const kept = read(fx, 'verify-partial.json').packages.frontend.testE2e
  assert.equal(kept.ok, true)
  assert.equal(kept.carried, true)
  const same = opts(fx, { reuse: true })
  assert.equal((await runVerify(same.options)).exit, 0)
  assert.match(stepLine(same.lines, 'frontend testE2e'), /reused \(verify-partial\.json/)
  writeFileSync(path.join(fx.root, 'backend', 'app.ts'), 'export const a = 3\n')
  const changed = opts(fx, { reuse: true })
  assert.equal((await runVerify(changed.options)).exit, 0)
  assert.doesNotMatch(reusedLines(changed.lines).join('\n'), /testE2e/)
})

test('without --reuse everything runs and the keys are still recorded', async () => {
  const fx = await fixture()
  await runVerify(opts(fx).options)
  const ran = runs(fx).length
  const again = opts(fx)
  await runVerify(again.options)
  assert.equal(runs(fx).length, ran * 2)
  assert.equal(reusedLines(again.lines).length, 0)
  const { key, reusable } = read(fx).packages.backend.check
  assert.deepEqual(Object.keys(key), ['packages', 'shared', 'command', 'base'])
  assert.deepEqual(Object.keys(key.packages), ['backend'])
  assert.equal(key.base, fx.sha)
  assert.equal(key.command, 'node ../stub.mjs pass')
  assert.equal(reusable, true)
})

test('a docs-only change reuses every step and starts no database or migration', async () => {
  const fx = await fixture()
  await runVerify(opts(fx).options)
  const ran = runs(fx).length
  const dockerLog = path.join(fx.base, 'docker.log')
  const before = readFileSync(dockerLog, 'utf8').split('\n').length
  mkdirSync(path.join(fx.root, 'notes'))
  writeFileSync(path.join(fx.root, 'notes', 'a.md'), 'words\n')
  const again = opts(fx, { reuse: true })
  assert.equal((await runVerify(again.options)).exit, 0)
  assert.equal(runs(fx).length, ran)
  assert.equal(reusedLines(again.lines).length, 6)
  const docker = readFileSync(dockerLog, 'utf8').split('\n')
  assert.equal(docker.filter((line) => line.startsWith('compose up')).length, 1)
  assert.equal(docker.length, before + 1)
  assert.equal(read(fx).packages.backend.migrate, undefined)
})

test('a package change re-runs that package and the e2e, not the other package', async () => {
  const fx = await fixture()
  await runVerify(opts(fx).options)
  writeFileSync(path.join(fx.root, 'backend', 'app.ts'), 'export const a = 2\n')
  const again = opts(fx, { reuse: true })
  assert.equal((await runVerify(again.options)).exit, 0)
  const reused = reusedLines(again.lines).join('\n')
  assert.doesNotMatch(reused, /backend (contract|check|testDb)/)
  assert.doesNotMatch(reused, /testE2e/)
  assert.match(reused, /frontend contract/)
  assert.match(reused, /frontend check/)
})

test('a frontend change leaves the backend steps reused and re-runs the e2e', async () => {
  const fx = await fixture()
  await runVerify(opts(fx).options)
  writeFileSync(path.join(fx.root, 'frontend', 'app.ts'), 'export const b = 2\n')
  const again = opts(fx, { reuse: true })
  await runVerify(again.options)
  const reused = reusedLines(again.lines).join('\n')
  assert.match(reused, /backend contract/)
  assert.match(reused, /backend check/)
  assert.match(reused, /backend testDb/)
  assert.doesNotMatch(reused, /frontend check/)
  assert.doesNotMatch(reused, /testE2e/)
})

test('a shared-input change re-runs every step', async () => {
  const fx = await fixture()
  await runVerify(opts(fx).options)
  mkdirSync(path.join(fx.root, 'db'))
  writeFileSync(path.join(fx.root, 'db', 'init.sql'), 'select 1\n')
  const again = opts(fx, { reuse: true })
  await runVerify(again.options)
  assert.equal(reusedLines(again.lines).length, 0)
})

test('a changed command line re-runs that step', async () => {
  const fx = await fixture()
  await runVerify(opts(fx).options)
  const file = path.join(fx.root, '.fullstack', 'catalog.yaml')
  const text = readFileSync(file, 'utf8')
  writeFileSync(file, text.replace('check: node ../stub.mjs pass', 'check: node ../stub.mjs skip'))
  const again = opts(fx, { reuse: true })
  await runVerify(again.options)
  assert.doesNotMatch(stepLine(again.lines, 'backend check'), /reused/)
})

test('a changed Base re-runs every step, the same Base reuses them', async () => {
  const fx = await fixture()
  await runVerify(opts(fx).options)
  writeFileSync(path.join(fx.root, 'backend', 'extra.ts'), 'export const e = 1\n')
  git(fx.root, 'add', '-A')
  git(fx.root, 'commit', '-qm', 'extra')
  const second = git(fx.root, 'rev-parse', '--short', 'HEAD')
  const other = opts(fx, { reuse: true, base: second })
  await runVerify(other.options)
  assert.equal(reusedLines(other.lines).length, 0)
  // A docs file moves the tree, so the whole-run shortcut does not answer for the third run.
  writeFileSync(path.join(fx.root, 'notes.md'), 'words\n')
  const again = opts(fx, { reuse: true, base: second })
  await runVerify(again.options)
  assert.equal(reusedLines(again.lines).length, 6)
})

test('a failing step is never reused', async () => {
  const fx = await fixture({ commands: { backend: { check: 'node ../stub.mjs fail' } } })
  assert.equal((await runVerify(opts(fx).options)).exit, 1)
  const ran = runs(fx).filter((mode) => mode === 'fail').length
  const again = opts(fx, { reuse: true })
  assert.equal((await runVerify(again.options)).exit, 1)
  assert.equal(runs(fx).filter((mode) => mode === 'fail').length, ran + 1)
  assert.doesNotMatch(stepLine(again.lines, 'backend check'), /reused/)
  assert.match(stepLine(again.lines, 'frontend check'), /reused/)
  const entry = read(fx).packages.backend.check
  assert.equal(entry.ok, false)
  assert.equal(entry.reusable, false)
})

test('a step whose inputs moved during its run is recorded as not reusable', async () => {
  const fx = await fixture({
    commands: { backend: { check: 'node ../stub.mjs stable ../backend/app.ts changed' } },
  })
  assert.equal((await runVerify(opts(fx).options)).exit, 1)
  const result = read(fx)
  assert.equal(result.packages.backend.check.ok, true)
  assert.equal(result.packages.backend.check.reusable, false)
  assert.equal(result.packages.frontend.check.reusable, true)
})

test('--round and --round-base are validated together, on full runs, against a real tree', async () => {
  const fx = await fixture()
  const tree = git(fx.root, 'rev-parse', 'HEAD^{tree}')
  const cases = [
    [{ round: '1' }, /--round-base/],
    [{ roundBase: tree }, /--round/],
    [{ round: '0', roundBase: tree }, /positive integer/],
    [{ round: 'x', roundBase: tree }, /positive integer/],
    [{ round: '1', roundBase: tree, noE2e: true }, /full run/],
    [{ round: '1', roundBase: tree, packages: ['backend'] }, /full run/],
    [{ round: '1', roundBase: 'nonsense' }, /not a tree or commit/],
  ]
  for (const [extra, reason] of cases) {
    const { exit, result } = await runVerify(opts(fx, extra).options)
    assert.equal(exit, 2, JSON.stringify(extra))
    assert.match(result.reason, reason)
  }
  assert.equal(runs(fx).length, 0)
})

// A committed 30-line file, so the -U10 context is visible, on top of the fixture's commit.
async function reviewFixture() {
  const fx = await fixture()
  const body = Array.from({ length: 30 }, (_, i) => `export const v${i + 1} = ${i + 1}`)
  writeFileSync(path.join(fx.root, 'backend', 'app.ts'), `${body.join('\n')}\n`)
  git(fx.root, 'add', '-A')
  git(fx.root, 'commit', '-qm', 'long file')
  fx.base30 = git(fx.root, 'rev-parse', '--short', 'HEAD')
  fx.body = body
  return fx
}

test('review.diff holds the stat and the -U10 diff, untracked files in, lockfiles out', async () => {
  const fx = await reviewFixture()
  const edited = fx.body.map((line, i) => (i === 14 ? 'export const v15 = 999' : line))
  writeFileSync(path.join(fx.root, 'backend', 'app.ts'), `${edited.join('\n')}\n`)
  writeFileSync(path.join(fx.root, 'frontend', 'fresh.ts'), 'export const fresh = 1\n')
  writeFileSync(path.join(fx.root, 'backend', 'bun.lock'), 'LOCKFILE-BODY\n')
  writeFileSync(path.join(fx.root, 'backend', 'openapi.json'), '{"GENERATED":1}\n')
  mkdirSync(path.join(fx.root, 'frontend', 'src', 'lib', 'api'), { recursive: true })
  writeFileSync(path.join(fx.root, 'frontend', 'src', 'lib', 'api', 'schema.d.ts'), 'GENSCHEMA\n')
  const generated = path.join(fx.root, 'frontend', 'src', 'shared', 'api', 'generated')
  mkdirSync(generated, { recursive: true })
  writeFileSync(path.join(generated, 'schema.ts'), 'GENSHARED\n')
  const { options, lines } = opts(fx, { base: fx.base30 })
  await runVerify(options)
  const result = read(fx)
  const file = path.join(outDir(fx), 'review.diff')
  const text = readFileSync(file, 'utf8')
  assert.deepEqual(result.review, ['review.diff'])
  assert.ok(lines.some((line) => line === `review: ${file}`))
  assert.match(text, new RegExp(`^# review package\nbase [0-9a-f]{40}\ntree ${result.tree}\n\n`))
  const [head, rest] = text.split('\nexcluded from the diff below: ')
  for (const name of ['backend/app.ts', 'frontend/fresh.ts', 'backend/bun.lock']) {
    assert.ok(head.includes(name), `stat lists ${name}`)
  }
  assert.match(head, /files? changed/)
  const excluded = rest.split('\n')[0]
  const body = rest.slice(rest.indexOf('\n') + 1)
  assert.deepEqual(
    excluded.split(', ').sort(),
    [
      'backend/bun.lock',
      'backend/openapi.json',
      'frontend/src/lib/api/schema.d.ts',
      'frontend/src/shared/api/generated/schema.ts',
    ].sort(),
  )
  assert.doesNotMatch(body, /GENSHARED/)
  assert.match(body, /\+export const v15 = 999/)
  assert.match(body, /\+export const fresh = 1/)
  // Ten lines of context each side of line 15: lines 5 and 25 are in, 4 and 26 are not.
  assert.match(body, / export const v5 = 5\n/)
  assert.match(body, / export const v25 = 25\n/)
  assert.doesNotMatch(body, /^ export const v4 = 4$/m)
  assert.doesNotMatch(body, /^ export const v26 = 26$/m)
  assert.doesNotMatch(body, /LOCKFILE-BODY|GENERATED|GENSCHEMA/)
})

test('review.diff says none when nothing is excluded, and a partial run writes none', async () => {
  const fx = await reviewFixture()
  writeFileSync(path.join(fx.root, 'frontend', 'fresh.ts'), 'export const fresh = 1\n')
  await runVerify(opts(fx, { base: fx.base30 }).options)
  const file = path.join(outDir(fx), 'review.diff')
  assert.match(readFileSync(file, 'utf8'), /excluded from the diff below: none\n/)
  rmSync(file)
  await runVerify(opts(fx, { base: fx.base30, packages: ['backend'] }).options)
  assert.equal(existsSync(file), false)
  assert.equal(read(fx, 'verify-partial.json').review, undefined)
})

test('a failing full run still writes the review package, a run with no base does not', async () => {
  const fx = await fixture({ commands: { backend: { check: 'node ../stub.mjs fail' } } })
  assert.equal((await runVerify(opts(fx).options)).exit, 1)
  assert.ok(existsSync(path.join(outDir(fx), 'review.diff')))
  const none = await fixture({ plan: false })
  await runVerify(opts(none, { plan: undefined, out: '.orchestrate/x' }).options)
  assert.equal(existsSync(path.join(none.root, '.orchestrate', 'x', 'review.diff')), false)
})

test('--round writes review-fix-<n>.diff against the round base and rewrites review.diff', async () => {
  const fx = await reviewFixture()
  writeFileSync(path.join(fx.root, 'backend', 'one.ts'), 'export const first = 1\n')
  await runVerify(opts(fx, { base: fx.base30 }).options)
  const roundBase = read(fx).tree
  writeFileSync(path.join(fx.root, 'backend', 'two.ts'), 'export const second = 2\n')
  const { options, lines } = opts(fx, { base: fx.base30, reuse: true, round: '1', roundBase })
  assert.equal((await runVerify(options)).exit, 0)
  const fix = readFileSync(path.join(outDir(fx), 'review-fix-1.diff'), 'utf8')
  const full = readFileSync(path.join(outDir(fx), 'review.diff'), 'utf8')
  const tree = read(fx).tree
  const header = `^# review package: fix round 1\nround-base ${roundBase}\ntree ${tree}\n`
  assert.match(fix, new RegExp(header))
  assert.match(fix, /\+export const second = 2/)
  assert.doesNotMatch(fix, /first = 1/)
  assert.match(full, /first = 1/)
  assert.match(full, /second = 2/)
  assert.deepEqual(read(fx).review, ['review.diff', 'review-fix-1.diff'])
  assert.ok(lines.some((line) => line.startsWith('review: ') && line.endsWith('review-fix-1.diff')))
})

test('a round run is not short-circuited by an unchanged passing tree', async () => {
  const fx = await reviewFixture()
  await runVerify(opts(fx, { base: fx.base30 }).options)
  const roundBase = read(fx).tree
  const again = opts(fx, { base: fx.base30, reuse: true, round: '2', roundBase })
  const { reused } = await runVerify(again.options)
  assert.equal(reused, undefined)
  assert.ok(existsSync(path.join(outDir(fx), 'review-fix-2.diff')))
})

test('parseArgs reads --round and --round-base', () => {
  const options = parseArgs(['--plan', 'p.md', '--round', '2', '--round-base', 'abc'])
  assert.equal(options.round, '2')
  assert.equal(options.roundBase, 'abc')
  assert.throws(() => parseArgs(['--plan', 'p.md', '--round']), /missing its value/)
})

test('an .editorconfig change invalidates every reused step', async () => {
  const fx = await fixture()
  await runVerify(opts(fx).options)
  writeFileSync(path.join(fx.root, '.editorconfig'), 'root = true\n')
  const again = opts(fx, { reuse: true })
  await runVerify(again.options)
  assert.equal(reusedLines(again.lines).length, 0)
})

test('a package missing from the tree is never reusable', async () => {
  const fx = await fixture({
    noDb: true,
    commands: { backend: { contract: null, testDb: null, migrate: null } },
  })
  rmSync(path.join(fx.root, 'backend', 'app.ts'))
  rmSync(path.join(fx.root, 'backend', 'contract.json'))
  await runVerify(opts(fx).options)
  const { packages } = read(fx)
  assert.equal(packages.backend.check.ok, true)
  assert.equal(packages.backend.check.reusable, false)
  assert.equal(packages.frontend.testE2e.reusable, false)
  assert.equal(packages.frontend.check.reusable, true)
})

test('a reused step keeps its counts in the line', async () => {
  const fx = await fixture()
  await runVerify(opts(fx).options)
  const again = opts(fx, { reuse: true })
  writeFileSync(path.join(fx.root, 'notes.md'), 'words\n')
  await runVerify(again.options)
  const line = stepLine(again.lines, 'backend check')
  assert.match(line, /\d+ passed, \d+ failed, \d+ skipped(, \d+ flaky)?, reused \(verify\.json, /)
})

test('--round with no base exits 2 with a reason', async () => {
  const fx = await fixture()
  const roundBase = git(fx.root, 'rev-parse', 'HEAD^{tree}')
  const extra = { plan: undefined, out: '.orchestrate/x', round: '1', roundBase }
  const { exit, result } = await runVerify(opts(fx, extra).options)
  assert.equal(exit, 2)
  assert.match(result.reason, /--round needs a base/)
})

test('secret-named files stay out of the review body and are listed by name', async () => {
  const fx = await reviewFixture()
  writeFileSync(path.join(fx.root, '.npmrc'), '//registry/:_authToken=TOKEN-XYZ\n')
  writeFileSync(path.join(fx.root, 'backend', 'id_rsa'), 'PRIVATE-KEY-BODY\n')
  writeFileSync(path.join(fx.root, 'backend', '.env.example'), 'PLACEHOLDER=1\n')
  await runVerify(opts(fx, { base: fx.base30 }).options)
  const text = readFileSync(path.join(outDir(fx), 'review.diff'), 'utf8')
  const [head] = text.split('\nexcluded from the diff below: ')
  assert.ok(head.includes('.npmrc'))
  assert.match(text, /\nsecret-named, not shown: .*\.npmrc/)
  assert.match(text, /\nsecret-named, not shown: .*backend\/id_rsa/)
  assert.doesNotMatch(text, /TOKEN-XYZ|PRIVATE-KEY-BODY/)
  assert.doesNotMatch(text, /not shown: .*\.env\.example/)
  assert.match(text, /\+PLACEHOLDER=1/)
})

test('env-prefixed names and credential directories stay out of the review body', async () => {
  const fx = await reviewFixture()
  mkdirSync(path.join(fx.root, 'backend', '.ssh'))
  writeFileSync(path.join(fx.root, 'backend', '.ssh', 'config'), 'SSH-CONFIG-BODY\n')
  writeFileSync(path.join(fx.root, 'backend', '.envrc'), 'ENVRC-BODY\n')
  writeFileSync(path.join(fx.root, 'backend', '.env.example'), 'PLACEHOLDER=1\n')
  await runVerify(opts(fx, { base: fx.base30 }).options)
  const text = readFileSync(path.join(outDir(fx), 'review.diff'), 'utf8')
  assert.match(text, /\nsecret-named, not shown: .*backend\/\.envrc/)
  assert.match(text, /\nsecret-named, not shown: .*backend\/\.ssh\/config/)
  assert.doesNotMatch(text, /SSH-CONFIG-BODY|ENVRC-BODY/)
  assert.match(text, /\+PLACEHOLDER=1/)
})

test('a failing git call leaves no review package and exits 2', async () => {
  const { writeReviewPackage } = await import('./verify/review.mjs')
  const fx = await reviewFixture()
  const out = path.join(fx.base, 'pkg')
  const bad = '0'.repeat(40)
  assert.throws(() => writeReviewPackage(fx.root, out, { base: fx.base30, tree: bad }), /git/)
  assert.equal(existsSync(path.join(out, 'review.diff')), false)
  const tree = git(fx.root, 'rev-parse', 'HEAD^{tree}')
  const round = { n: 1, base: bad }
  assert.throws(() => writeReviewPackage(fx.root, out, { base: fx.base30, tree, round }), /git/)
  assert.equal(existsSync(path.join(out, 'review.diff')), false)
})

const EXAMPLE = '.env.example'
const readmeOf = (fx) => path.join(fx.root, 'README.md')
const regenerate = (fx) =>
  writeFileSync(
    readmeOf(fx),
    replaceConfiguration(readFileSync(readmeOf(fx), 'utf8'), renderConfiguration(fx.root)),
  )

test('readme fails on a variable missing from the table and passes once regenerated', async () => {
  const fx = await fixture()
  writeFileSync(path.join(fx.root, 'backend', EXAMPLE), '# Port.\nPORT=4000\n')
  const { exit, result } = await runVerify(opts(fx).options)
  assert.equal(exit, 1)
  const check = result.checks.find((c) => c.name === 'readme')
  assert.equal(check.ok, false)
  assert.match(check.detail, /node scripts\/readme\.mjs --configuration/)
  regenerate(fx)
  assert.equal((await runVerify(opts(fx).options)).exit, 0)
})

test('a deleted, unstaged example file is recorded as a readme result, not a crash', async () => {
  const fx = await fixture()
  writeFileSync(path.join(fx.root, 'backend', EXAMPLE), 'PORT=4000\n')
  git(fx.root, 'add', '-A')
  git(fx.root, 'commit', '-qm', 'example')
  regenerate(fx)
  git(fx.root, 'commit', '-qam', 'table')
  rmSync(path.join(fx.root, 'backend', EXAMPLE))
  const { exit, result } = await runVerify(opts(fx).options)
  assert.equal(exit, 1)
  assert.equal(result.checks.find((c) => c.name === 'readme').ok, false)
  regenerate(fx)
  assert.equal((await runVerify(opts(fx).options)).exit, 0)
})

test('readme fails on an extra variable in the table', async () => {
  const fx = await fixture()
  writeFileSync(path.join(fx.root, 'backend', EXAMPLE), 'PORT=4000\n')
  regenerate(fx)
  assert.equal((await runVerify(opts(fx).options)).exit, 0)
  writeFileSync(path.join(fx.root, 'backend', EXAMPLE), '')
  const { exit, result } = await runVerify(opts(fx).options)
  assert.equal(exit, 1)
  assert.equal(result.checks.find((c) => c.name === 'readme').ok, false)
})

test('readme fails on a missing README.md and on a missing block', async () => {
  const fx = await fixture()
  rmSync(readmeOf(fx))
  const missing = await runVerify(opts(fx).options)
  assert.equal(missing.exit, 1)
  assert.match(missing.result.checks.find((c) => c.name === 'readme').detail, /README\.md is missing/)
  writeFileSync(readmeOf(fx), '# No block\n')
  const bare = await runVerify(opts(fx).options)
  assert.equal(bare.exit, 1)
  assert.match(bare.result.checks.find((c) => c.name === 'readme').detail, /marker/)
})

test('a CRLF README with a correct block passes', async () => {
  const fx = await fixture()
  writeFileSync(readmeOf(fx), readFileSync(readmeOf(fx), 'utf8').replaceAll('\n', '\r\n'))
  assert.equal((await runVerify(opts(fx).options)).exit, 0)
})

test('--package and --no-e2e runs skip the readme check', async () => {
  const fx = await fixture()
  rmSync(readmeOf(fx))
  const packaged = await runVerify(opts(fx, { packages: ['backend'] }).options)
  assert.equal(packaged.exit, 0)
  assert.equal(read(fx, 'verify-partial.json').checks.some((c) => c.name === 'readme'), false)
  assert.equal((await runVerify(opts(fx, { noE2e: true }).options)).exit, 0)
})

describe('verify', { concurrency: 6 }, () => {
  for (const [name, run] of tests) it(name, run)
})
