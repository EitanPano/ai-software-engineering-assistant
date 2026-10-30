import { spawn, spawnSync } from 'node:child_process'
import net from 'node:net'
import process from 'node:process'
import { startReaper } from './reap.mjs'

const WIN = process.platform === 'win32'
const KEEP = 400_000

// Stops the process and everything it started. Windows has no process groups to signal, so
// taskkill walks the tree; elsewhere the child leads its own group (see `detached` below).
export function killTree(pid) {
  if (WIN) {
    spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true })
    return
  }
  try {
    process.kill(-pid, 'SIGKILL')
  } catch {
    // The group is already gone.
  }
}

// Runs a command line through the shell (so `.cmd` shims resolve) and resolves with its exit
// code and combined output. A timeout kills the tree; on POSIX so does the exit, for a child
// left behind.
export function runCommand(line, options) {
  const { cwd, timeout, env, reap = true, reapInterval = 3000, reapQuery, reapLimit } = options
  return new Promise((resolve) => {
    const started = Date.now()
    let output = ''
    let timedOut = false
    const child = spawn(line, {
      cwd,
      shell: true,
      detached: !WIN,
      windowsHide: true,
      env: env ?? process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    const collect = (chunk) => {
      output = (output + chunk).slice(-KEEP)
    }
    child.stdout.on('data', collect)
    child.stderr.on('data', collect)
    // Windows records the step's descendants while it runs, so they can be reaped after it ends.
    const reaper =
      WIN && reap
        ? startReaper(child.pid, started, reapInterval, { query: reapQuery, limit: reapLimit })
        : undefined
    reaper?.snapshot()
    // The root is killed first and never waits on a process-table query.
    const timer = setTimeout(() => {
      timedOut = true
      killTree(child.pid)
    }, timeout)
    let done = false
    const finish = async (code, error) => {
      if (done) return
      done = true
      clearTimeout(timer)
      // A dead Windows PID may already belong to another process, so only POSIX kills by pid
      // after exit; Windows kills the recorded (pid, creation time) pairs that still match.
      if (!WIN) killTree(child.pid)
      const reaped = await reaper?.stop()
      if (error !== undefined) output += `\n${error.message}`
      const ms = Date.now() - started
      resolve({ exit: timedOut ? null : code, timedOut, output, ms, reap: reaped?.error })
    }
    // An orphan holding the pipes would keep `close` from firing, so `exit` ends the wait too,
    // after a grace.
    child.on('error', (error) => finish(-1, error))
    child.on('close', (code) => finish(code))
    child.on('exit', (code) => setTimeout(() => finish(code), 500).unref())
  })
}

function connects(port, host) {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host })
    const done = (value) => (socket.destroy(), resolve(value))
    socket.setTimeout(750, () => done(false))
    socket.on('connect', () => done(true))
    socket.on('error', () => done(false))
  })
}

// The PID listening on a TCP port, or undefined when it cannot be found.
export function listenerPid(port) {
  const run = (cmd, args) => spawnSync(cmd, args, { encoding: 'utf8', windowsHide: true })
  if (WIN) {
    // `netstat -ano` lists IPv4 and IPv6 sockets alike; a v6 local address is bracketed.
    for (const line of run('netstat', ['-ano']).stdout?.split(/\r?\n/) ?? []) {
      const cols = line.trim().split(/\s+/)
      const tcp = cols[0] === 'TCP' || cols[0] === 'TCPv6'
      if (tcp && cols[3] === 'LISTENING' && cols[1].endsWith(`:${port}`)) return Number(cols[4])
    }
    return undefined
  }
  const lsof = run('lsof', ['-nP', `-iTCP:${port}`, '-sTCP:LISTEN', '-t']).stdout?.trim()
  if (lsof) return Number(lsof.split(/\s+/)[0])
  const ss = /pid=(\d+)/.exec(run('ss', ['-ltnpH', `sport = :${port}`]).stdout ?? '')
  return ss === null ? undefined : Number(ss[1])
}

// `{ busy: false }` for a free port, else `{ busy: true, pid }`. Both loopback families count.
export async function portStatus(port) {
  const [v4, v6] = await Promise.all([connects(port, '127.0.0.1'), connects(port, '::1')])
  return v4 || v6 ? { busy: true, pid: listenerPid(port) } : { busy: false }
}
