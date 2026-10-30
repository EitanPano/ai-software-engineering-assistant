import { spawn, spawnSync } from 'node:child_process'

const QUERY_LIMIT = 10_000

// FILETIME is 100 ns ticks since 1601; BigInt keeps the 18-digit values exact.
const filetime = (ms) => (BigInt(Math.trunc(ms)) + 11644473600000n) * 10000n
const QUERY =
  'Get-CimInstance Win32_Process | ForEach-Object { if ($_.CreationDate) { ' +
  '"$($_.ProcessId) $($_.ParentProcessId) $($_.CreationDate.ToFileTimeUtc())" } }'

// pid -> { ppid, created } for every process now running. A query that fails or outlives the
// limit gives an empty map with `error` set, and the PowerShell child is killed.
export function processTable(limit = QUERY_LIMIT) {
  return new Promise((resolve) => {
    let text = ''
    let settled = false
    const ps = spawn('powershell', ['-NoProfile', '-NonInteractive', '-Command', QUERY], {
      stdio: ['ignore', 'pipe', 'ignore'],
      windowsHide: true,
    })
    const finish = (error) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      const table = new Map()
      if (error !== undefined) table.error = error
      else {
        for (const line of text.split(/\r?\n/)) {
          const [pid, ppid, created] = line.trim().split(' ')
          if (created === undefined) continue
          table.set(Number(pid), { ppid: Number(ppid), created: BigInt(created) })
        }
      }
      resolve(table)
    }
    const timer = setTimeout(() => {
      spawnSync('taskkill', ['/PID', String(ps.pid), '/T', '/F'], { stdio: 'ignore' })
      finish(`query timed out after ${limit} ms`)
    }, limit)
    ps.stdout.on('data', (chunk) => (text += chunk))
    ps.on('error', (error) => finish(`query failed: ${error.message}`))
    ps.on('close', () => finish())
  })
}

const killTree = (pid) =>
  spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true })

// Windows keeps no process group, and a parent that exits leaves its children running, so the
// descendants of a step are recorded as (pid, creation time) while it runs. Only a process whose
// pid and creation time both still match is killed: a reused pid has a different creation time.
// The root counts only once a table has shown it with a creation time at or after the spawn, and
// nothing is a descendant before that. A query is bounded by `limit`, so a stuck process table
// never holds the step; the failure is kept in `error`.
// Known limit: a descendant is recorded only if a snapshot saw it while its parent lived. A step
// that exits within one interval and leaves an orphan behind is missed, because the orphan's
// parent is gone before any table shows the link. The orphan then outlives the run.
export function startReaper(rootPid, spawnedAt, interval, options = {}) {
  const { query = processTable, kill = killTree, limit = QUERY_LIMIT } = options
  const earliest = filetime(spawnedAt - 2000)
  const known = new Map()
  let stopped = false
  let busy = false
  let error
  const bounded = async () => {
    let timer
    const cutoff = new Promise((resolve) => {
      timer = setTimeout(() => {
        const empty = new Map()
        empty.error = `query timed out after ${limit} ms`
        resolve(empty)
      }, limit)
    })
    try {
      const table = await Promise.race([query(), cutoff])
      if (table.error !== undefined) error ??= table.error
      return table
    } finally {
      clearTimeout(timer)
    }
  }
  const scan = (table) => {
    const root = table.get(rootPid)
    if (!known.has(rootPid) && root !== undefined && root.created >= earliest) {
      known.set(rootPid, { created: root.created })
    }
    if (!known.has(rootPid)) return
    let grew = true
    while (grew) {
      grew = false
      for (const [pid, row] of table) {
        const parent = known.get(row.ppid)
        if (known.has(pid) || parent === undefined || row.created < parent.created) continue
        // A live process on the parent's pid with another creation time is a reused pid.
        const owner = table.get(row.ppid)
        if (owner !== undefined && owner.created !== parent.created) continue
        known.set(pid, { created: row.created })
        grew = true
      }
    }
  }
  const snapshot = async () => {
    if (busy || stopped) return
    busy = true
    try {
      const table = await bounded()
      if (!stopped) scan(table)
    } finally {
      busy = false
    }
  }
  const timer = setInterval(snapshot, interval)
  timer.unref()
  return {
    snapshot,
    async stop() {
      stopped = true
      clearInterval(timer)
      const table = await bounded()
      scan(table)
      let killed = 0
      for (const [pid, { created }] of known) {
        if (pid === rootPid || table.get(pid)?.created !== created) continue
        kill(pid)
        killed++
      }
      return { killed, error }
    },
  }
}
