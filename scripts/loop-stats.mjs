// Measures a dev-loop run from Claude Code's own transcripts: per sub-agent minutes, tool calls
// and tokens, then totals per slug, per model and for the driver. Read-only; it only prints.
// `node scripts/loop-stats.mjs [--project <repo dir>] [--project-dir <transcript dir>]
// [--session <id> | --latest] [--json]`
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { isMain } from './verify/main.mjs'

const USAGE =
  'usage: node scripts/loop-stats.mjs [--project <repo dir>] [--project-dir <transcript dir>] ' +
  '[--session <id> | --latest] [--json] [--help]'

export function encodeProjectPath(dir) {
  return dir.replace(/[^A-Za-z0-9-]/g, '-')
}

export function projectDirFor(repo, projectsRoot = path.join(homedir(), '.claude', 'projects')) {
  return path.join(projectsRoot, encodeProjectPath(path.resolve(repo)))
}

const minutesBetween = (from, to) =>
  from === undefined ? 0 : Math.round(((Date.parse(to) - Date.parse(from)) / 60_000) * 100) / 100

// One assistant message is written as one line per content block with the same id and usage, so
// usage counts once per id and tool calls once per tool_use id. Minutes run from the first to the
// last assistant line: whatever an orphaned background process logs after that is ignored.
// A SendMessage continuation is a user line with string (or text-block) content that starts with
// CONTINUATION; it opens a new segment, so one agent row splits into the dispatch and each
// continuation, each with its own start, minutes and tool count.
const CONTINUATION = /^The coordinator sent a message while you were working:/

function continuationTime(event) {
  if (event.type !== 'user') return undefined
  const content = event.message?.content
  const body =
    typeof content === 'string'
      ? content
      : Array.isArray(content)
        ? content.find((block) => block?.type === 'text')?.text
        : undefined
  return typeof body === 'string' && CONTINUATION.test(body) ? (event.timestamp ?? null) : undefined
}

export function readTranscript(file) {
  const seen = new Map()
  const tools = new Set()
  let start
  let firstAssistant
  let lastAssistant
  let model
  const segments = [{ start: undefined, first: undefined, last: undefined, tools: 0 }]
  for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
    let event
    try {
      event = JSON.parse(line)
    } catch {
      continue
    }
    if (event === null || typeof event !== 'object') continue
    if (event.timestamp !== undefined) start ??= event.timestamp
    const resumedAt = continuationTime(event)
    if (resumedAt !== undefined) {
      segments.push({ start: resumedAt ?? undefined, first: undefined, last: undefined, tools: 0 })
      continue
    }
    if (event.type !== 'assistant') continue
    const segment = segments[segments.length - 1]
    segment.first ??= event.timestamp
    segment.last = event.timestamp ?? segment.last
    firstAssistant ??= event.timestamp
    lastAssistant = event.timestamp ?? lastAssistant
    model ??= event.message?.model
    const id = event.message?.id ?? `line-${seen.size}`
    seen.set(id, event.message?.usage ?? seen.get(id) ?? {})
    for (const block of event.message?.content ?? []) {
      if (block?.type !== 'tool_use') continue
      const toolId = block.id ?? `${id}-${tools.size}`
      if (!tools.has(toolId)) segment.tools += 1
      tools.add(toolId)
    }
  }
  let outputTokens = 0
  let contextTokens = 0
  for (const usage of seen.values()) {
    outputTokens += usage.output_tokens ?? 0
    contextTokens +=
      (usage.input_tokens ?? 0) +
      (usage.cache_read_input_tokens ?? 0) +
      (usage.cache_creation_input_tokens ?? 0)
  }
  const minutes = minutesBetween(firstAssistant, lastAssistant)
  const parts = segments
    .filter((part) => part.first !== undefined)
    .map((part, index) => ({
      kind: index === 0 && part === segments[0] ? 'dispatch' : 'continuation',
      start: part.start ?? part.first,
      minutes: minutesBetween(part.start ?? part.first, part.last),
      tools: part.tools,
    }))
  return { start, minutes, model, tools: tools.size, outputTokens, contextTokens, segments: parts }
}

function total(rows) {
  const sum = { agents: rows.length, minutes: 0, tools: 0, outputTokens: 0, contextTokens: 0 }
  for (const row of rows) {
    sum.minutes += row.minutes
    sum.tools += row.tools
    sum.outputTokens += row.outputTokens
    sum.contextTokens += row.contextTokens
  }
  sum.minutes = Math.round(sum.minutes * 100) / 100
  return sum
}

function groupBy(agents, key) {
  const groups = {}
  for (const agent of agents) (groups[key(agent)] ??= []).push(agent)
  return Object.fromEntries(Object.entries(groups).map(([name, rows]) => [name, total(rows)]))
}

const slugOf = ({ description }) =>
  description.includes(':') ? description.split(':')[0] : '(no slug)'

export function sessionStats(projectDir, session) {
  const subagents = path.join(projectDir, session, 'subagents')
  const agents = []
  const names = existsSync(subagents) ? readdirSync(subagents).sort() : []
  for (const name of names.filter((n) => /^agent-.+\.jsonl$/.test(n))) {
    const id = name.slice('agent-'.length, -'.jsonl'.length)
    let meta = {}
    try {
      meta = JSON.parse(readFileSync(path.join(subagents, `agent-${id}.meta.json`), 'utf8'))
    } catch {
      // A transcript without a readable meta file is still counted, under no type.
    }
    const read = readTranscript(path.join(subagents, name))
    agents.push({
      id,
      agentType: meta.agentType ?? '(unknown)',
      description: meta.description ?? '',
      ...read,
      model: read.model ?? meta.model ?? '(unknown)',
    })
  }
  agents.sort((a, b) => String(a.start).localeCompare(String(b.start)))
  const own = path.join(projectDir, `${session}.jsonl`)
  const driver = existsSync(own) ? readTranscript(own) : total([])
  return {
    session,
    agents,
    bySlug: groupBy(agents, slugOf),
    byModel: groupBy(agents, (a) => a.model),
    driver: {
      minutes: driver.minutes,
      tools: driver.tools,
      outputTokens: driver.outputTokens,
      contextTokens: driver.contextTokens,
    },
  }
}

const mega = (tokens) => `${(tokens / 1e6).toFixed(2)}M`
const kilo = (tokens) => `${(tokens / 1e3).toFixed(1)}k`

export function formatStats(stats) {
  const lines = [`session ${stats.session}`, '']
  lines.push('start     min   tools  out      context  type             description        model')
  for (const a of stats.agents) {
    // With continuations the row shows the dispatch alone; tokens and the totals stay per agent.
    const dispatch = a.segments?.length > 1 && a.segments[0].kind === 'dispatch' ? a.segments[0] : a
    const time = a.start === undefined ? '--:--:--' : a.start.slice(11, 19)
    lines.push(
      [
        time.padEnd(9),
        dispatch.minutes.toFixed(1).padStart(5),
        String(dispatch.tools).padStart(7),
        kilo(a.outputTokens).padStart(8),
        mega(a.contextTokens).padStart(9),
        `  ${a.agentType.padEnd(16)}`,
        `${a.description}  ${a.model}`,
      ].join(' '),
    )
    for (const part of (a.segments ?? []).filter((p) => p.kind === 'continuation')) {
      const at = part.start === undefined ? '--:--:--' : part.start.slice(11, 19)
      lines.push(
        `  + ${at}`.padEnd(9 + 2) +
          ` ${part.minutes.toFixed(1).padStart(5)} ${String(part.tools).padStart(7)}  continuation`,
      )
    }
  }
  const row = (name, t) =>
    `  ${name.padEnd(24)} ${t.agents} agents  ${t.minutes.toFixed(1)} min  ${t.tools} tools  ` +
    `${kilo(t.outputTokens)} out  ${mega(t.contextTokens)} context`
  lines.push('', 'by slug')
  for (const [name, t] of Object.entries(stats.bySlug)) lines.push(row(name, t))
  lines.push('', 'by model')
  for (const [name, t] of Object.entries(stats.byModel)) lines.push(row(name, t))
  const d = stats.driver
  lines.push(
    '',
    `driver: ${d.minutes.toFixed(1)} min  ${d.tools} tools  ${kilo(d.outputTokens)} out  ` +
      `${mega(d.contextTokens)} context`,
  )
  return lines.join('\n')
}

// A value that is missing, or is the next flag, is a usage error.
function valueAfter(argv, index, flag) {
  const value = argv[index]
  if (value === undefined || value.startsWith('--')) {
    throw new Error(`${flag} needs a value\n${USAGE}`)
  }
  return value
}

export function parseArgs(argv) {
  const options = {
    project: undefined,
    projectDir: undefined,
    session: undefined,
    latest: false,
    json: false,
    help: false,
  }
  const takes = { '--project': 'project', '--project-dir': 'projectDir', '--session': 'session' }
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    if (arg in takes) options[takes[arg]] = valueAfter(argv, ++i, arg)
    else if (arg === '--latest') options.latest = true
    else if (arg === '--json') options.json = true
    else if (arg === '--help') options.help = true
    else throw new Error(USAGE)
  }
  return options
}

function latestSession(projectDir) {
  const sessions = readdirSync(projectDir)
    .filter((name) => name.endsWith('.jsonl'))
    .map((name) => ({ name, mtime: statSync(path.join(projectDir, name)).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime)
  return sessions[0]?.name.slice(0, -'.jsonl'.length)
}

if (isMain(import.meta.url, process.argv[1])) {
  try {
    const options = parseArgs(process.argv.slice(2))
    if (options.help) {
      console.log(USAGE)
      process.exit(0)
    }
    const projectDir = options.projectDir ?? projectDirFor(options.project ?? process.cwd())
    if (!existsSync(projectDir)) throw new Error(`no transcript folder at ${projectDir}`)
    const session = options.session ?? latestSession(projectDir)
    if (session === undefined) throw new Error(`no session transcript in ${projectDir}`)
    const found =
      existsSync(path.join(projectDir, `${session}.jsonl`)) ||
      existsSync(path.join(projectDir, session))
    if (!found) throw new Error(`no session ${session} in ${projectDir}`)
    const stats = sessionStats(projectDir, session)
    console.log(options.json ? JSON.stringify(stats, null, 2) : formatStats(stats))
  } catch (error) {
    console.error(error.message)
    process.exit(2)
  }
}
