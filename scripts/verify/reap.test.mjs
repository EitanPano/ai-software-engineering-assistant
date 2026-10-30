import assert from 'node:assert/strict'
import { test } from 'node:test'
import { runCommand } from './proc.mjs'
import { startReaper } from './reap.mjs'

const ROOT = 100
const T0 = 132_000_000_000_000_000n
// Rows are [pid, ppid, created offset]; created values sit after the spawn time given below.
const table = (rows) =>
  new Map(rows.map(([pid, ppid, at]) => [pid, { ppid, created: T0 + BigInt(at) * 10_000_000n }]))
const SPAWNED = Number((T0 / 10000n) - 11644473600000n)

function reaperWith(tables, extra = {}) {
  const killed = []
  let call = 0
  const reaper = startReaper(ROOT, SPAWNED, 3_600_000, {
    query: async () => tables[Math.min(call++, tables.length - 1)],
    kill: (pid) => killed.push(pid),
    ...extra,
  })
  return { reaper, killed }
}

test('descendants seen while the root lived are killed after it is gone, the root is not', async () => {
  const { reaper, killed } = reaperWith([
    table([[ROOT, 1, 1], [101, ROOT, 2]]),
    table([[101, ROOT, 2], [102, 101, 3]]),
    table([[101, ROOT, 2], [102, 101, 3]]),
  ])
  await reaper.snapshot()
  await reaper.snapshot()
  const { killed: count } = await reaper.stop()
  assert.deepEqual(killed.sort(), [101, 102])
  assert.equal(count, 2)
})

test('nothing is a descendant until the root has been seen in a table', async () => {
  const { reaper, killed } = reaperWith([table([[101, ROOT, 2], [102, 101, 3]])])
  await reaper.snapshot()
  await reaper.stop()
  assert.deepEqual(killed, [])
})

test('a root pid that reappears with a later creation time adopts no children', async () => {
  const { reaper, killed } = reaperWith([
    table([[ROOT, 1, 1]]),
    table([[ROOT, 1, 50], [201, ROOT, 51]]),
    table([[ROOT, 1, 50], [201, ROOT, 51]]),
  ])
  await reaper.snapshot()
  await reaper.snapshot()
  await reaper.stop()
  assert.deepEqual(killed, [])
})

test('a recorded pid whose creation time changed is not killed', async () => {
  const { reaper, killed } = reaperWith([
    table([[ROOT, 1, 1], [101, ROOT, 2]]),
    table([[101, 1, 90]]),
  ])
  await reaper.snapshot()
  await reaper.stop()
  assert.deepEqual(killed, [])
})

test('a query that never resolves is cut off at the bound and reported', async () => {
  const { reaper } = reaperWith([], { query: () => new Promise(() => {}), limit: 200 })
  const started = Date.now()
  const result = await reaper.stop()
  assert.ok(Date.now() - started < 2000)
  assert.equal(result.killed, 0)
  assert.match(result.error, /timed out/)
})

test('a hung process-table query does not delay a command or its timeout kill', async (t) => {
  if (process.platform !== 'win32') return t.skip('the process table is only read on Windows')
  const hang = () => new Promise(() => {})
  const options = { reap: true, reapInterval: 100, reapQuery: hang, reapLimit: 300 }
  const quick = await runCommand('node -e "process.exit(0)"', { timeout: 20_000, ...options })
  assert.equal(quick.exit, 0)
  assert.match(quick.reap, /timed out/)
  const started = Date.now()
  const slow = await runCommand('node -e "setInterval(() => {}, 1000)"', { timeout: 500, ...options })
  assert.equal(slow.timedOut, true)
  assert.ok(Date.now() - started < 4000)
})
