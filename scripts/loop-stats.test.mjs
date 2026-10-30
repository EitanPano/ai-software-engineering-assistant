import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, utimesSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { after, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import {
  encodeProjectPath,
  formatStats,
  parseArgs,
  projectDirFor,
  readTranscript,
  sessionStats,
} from './loop-stats.mjs'

const script = path.join(path.dirname(fileURLToPath(import.meta.url)), 'loop-stats.mjs')
const roots = []

function tempRoot() {
  const dir = mkdtempSync(path.join(tmpdir(), 'loop-stats-'))
  roots.push(dir)
  return dir
}

after(() => {
  for (const dir of roots) rmSync(dir, { recursive: true, force: true })
})

const usage = (output, input, read, write) => ({
  input_tokens: input,
  output_tokens: output,
  cache_read_input_tokens: read,
  cache_creation_input_tokens: write,
})

// One assistant message is written as one line per content block, all with the same message id
// and the same usage: counting every line would multiply the tokens.
function assistant(time, id, model, usageBlock, blocks) {
  return blocks.map((content) => ({
    type: 'assistant',
    timestamp: `2026-10-26T${time}Z`,
    message: { id, model, usage: usageBlock, content: [content] },
  }))
}
const tool = (id) => ({ type: 'tool_use', id, name: 'Read', input: {} })
const text = { type: 'text', text: 'ok' }
const user = (time) => ({
  type: 'user',
  timestamp: `2026-10-26T${time}Z`,
  message: { role: 'user', content: 'go' },
})

const opusLines = [
  user('10:00:00'),
  ...assistant('10:00:10', 'm1', 'claude-opus-4-7', usage(100, 2, 1000, 500), [text, tool('t1')]),
  user('10:00:20'),
  ...assistant('10:06:10', 'm2', 'claude-opus-4-7', usage(50, 3, 2000, 0), [
    tool('t2'),
    tool('t3'),
  ]),
  // An orphaned background process reporting long after the agent finished.
  user('11:30:00'),
  { type: 'attachment', timestamp: '2026-10-26T11:31:00Z' },
]
const sonnetLines = [
  user('10:10:00'),
  ...assistant('10:10:05', 's1', 'claude-sonnet-5-5', usage(10, 1, 300, 100), [tool('t1')]),
  ...assistant('10:12:05', 's2', 'claude-sonnet-5-5', usage(20, 1, 400, 0), [text]),
]
const driverLines = [
  user('09:59:00'),
  ...assistant('09:59:30', 'd1', 'claude-opus-4-7', usage(7, 1, 100, 50), [text, tool('t1')]),
  ...assistant('10:30:30', 'd2', 'claude-opus-4-7', usage(3, 1, 200, 0), [text]),
]

const jsonl = (lines) => `${lines.map((line) => JSON.stringify(line)).join('\n')}\nnot json\n`

function fixture() {
  const home = tempRoot()
  const repo = path.join(home, 'my repo', 'x')
  const projectDir = projectDirFor(repo, path.join(home, 'projects'))
  const session = 'sess-1'
  const subagents = path.join(projectDir, session, 'subagents')
  mkdirSync(subagents, { recursive: true })
  writeFileSync(path.join(projectDir, `${session}.jsonl`), jsonl(driverLines))
  const agent = (id, lines, meta) => {
    writeFileSync(path.join(subagents, `agent-${id}.jsonl`), jsonl(lines))
    writeFileSync(path.join(subagents, `agent-${id}.meta.json`), JSON.stringify(meta))
  }
  agent('a1', opusLines, {
    agentType: 'reviewer',
    description: 'lean-loop: review H1',
    model: 'opus',
  })
  agent('a2', sonnetLines, {
    agentType: 'general-purpose',
    description: 'lean-loop: H4 diet',
    model: 'sonnet',
  })
  return { home, repo, projectDir, session }
}

test('the project folder name turns every character outside [A-Za-z0-9-] into a dash', () => {
  assert.equal(
    encodeProjectPath('C:\\Dev\\Playground\\AI\\fullstack-dev-harness'),
    'C--Dev-Playground-AI-fullstack-dev-harness',
  )
  assert.equal(encodeProjectPath('/home/a b/c_d.e'), '-home-a-b-c-d-e')
})

test('readTranscript counts a message once, tool calls once, and stops at the last assistant line', () => {
  const dir = tempRoot()
  const file = path.join(dir, 'agent-a1.jsonl')
  writeFileSync(file, jsonl(opusLines))
  const agent = readTranscript(file)
  assert.equal(agent.minutes, 6)
  assert.equal(agent.start, '2026-10-26T10:00:00Z')
  assert.equal(agent.model, 'claude-opus-4-7')
  assert.equal(agent.tools, 3)
  assert.equal(agent.outputTokens, 150)
  assert.equal(agent.contextTokens, 2 + 1000 + 500 + 3 + 2000)
})

test('sessionStats totals per slug, per model, and the driver', () => {
  const { projectDir, session } = fixture()
  const stats = sessionStats(projectDir, session)
  assert.deepEqual(
    stats.agents.map((agent) => [agent.agentType, agent.minutes, agent.tools, agent.model]),
    [
      ['reviewer', 6, 3, 'claude-opus-4-7'],
      ['general-purpose', 2, 1, 'claude-sonnet-5-5'],
    ],
  )
  assert.equal(stats.agents[0].description, 'lean-loop: review H1')
  assert.deepEqual(stats.bySlug['lean-loop'], {
    agents: 2,
    minutes: 8,
    tools: 4,
    outputTokens: 180,
    contextTokens: 3505 + 802,
  })
  assert.equal(stats.byModel['claude-opus-4-7'].agents, 1)
  assert.equal(stats.byModel['claude-sonnet-5-5'].outputTokens, 30)
  assert.equal(stats.driver.minutes, 31)
  assert.equal(stats.driver.tools, 1)
  assert.equal(stats.driver.outputTokens, 10)
})

test('sessionStats falls back to the meta model and survives a transcript with no assistant line', () => {
  const { projectDir, session } = fixture()
  const subagents = path.join(projectDir, session, 'subagents')
  writeFileSync(path.join(subagents, 'agent-a3.jsonl'), jsonl([user('10:20:00')]))
  writeFileSync(
    path.join(subagents, 'agent-a3.meta.json'),
    JSON.stringify({ agentType: 'qa', description: 'no colon here', model: 'sonnet' }),
  )
  const stats = sessionStats(projectDir, session)
  const empty = stats.agents.find((agent) => agent.agentType === 'qa')
  assert.equal(empty.minutes, 0)
  assert.equal(empty.model, 'sonnet')
  assert.equal(empty.tools, 0)
  assert.ok('(no slug)' in stats.bySlug)
})

test('formatStats prints one row per agent and the totals', () => {
  const { projectDir, session } = fixture()
  const out = formatStats(sessionStats(projectDir, session))
  assert.match(out, /reviewer\s+lean-loop: review H1/)
  assert.match(out, /by slug/i)
  assert.match(out, /lean-loop\s+2 agents/)
  assert.match(out, /by model/i)
  assert.match(out, /driver/i)
})

test('parseArgs reads the documented flags', () => {
  assert.deepEqual(parseArgs(['--project', 'r', '--session', 's', '--json']), {
    project: 'r',
    session: 's',
    latest: false,
    json: true,
    projectDir: undefined,
    help: false,
  })
  assert.equal(parseArgs(['--help']).help, true)
  assert.equal(parseArgs(['--latest']).latest, true)
  assert.equal(parseArgs(['--project-dir', 'd']).projectDir, 'd')
  assert.throws(() => parseArgs(['--nope']), /usage/)
})

test('the CLI picks the latest session of an explicit project dir and prints JSON', () => {
  const { projectDir, session } = fixture()
  const older = path.join(projectDir, 'old.jsonl')
  writeFileSync(older, jsonl(driverLines))
  const past = new Date(Date.now() - 3_600_000)
  utimesSync(older, past, past)
  const run = spawnSync(
    process.execPath,
    [script, '--project-dir', projectDir, '--latest', '--json'],
    { encoding: 'utf8' },
  )
  assert.equal(run.status, 0, run.stderr)
  const stats = JSON.parse(run.stdout)
  assert.equal(stats.session, session)
  assert.equal(stats.agents.length, 2)
})

test('the CLI exits 2 when the folder or session is missing', () => {
  const dir = tempRoot()
  const run = spawnSync(process.execPath, [script, '--project-dir', dir, '--session', 'nope'], {
    encoding: 'utf8',
  })
  assert.equal(run.status, 2)
  assert.match(run.stderr, /nope|session/)
})

test('a flag with no value is a usage error', () => {
  for (const flag of ['--session', '--project', '--project-dir']) {
    assert.throws(() => parseArgs(['--json', flag]), /usage/)
  }
  const run = spawnSync(process.execPath, [script, '--session'], { encoding: 'utf8' })
  assert.equal(run.status, 2)
  assert.match(run.stderr, /usage/)
})

test('a flag followed by another flag is missing its value', () => {
  assert.throws(() => parseArgs(['--session', '--json']), /usage/)
  assert.throws(() => parseArgs(['--project-dir', '--latest']), /usage/)
})

test('the CLI runs through a directory link instead of exiting 0 silently', () => {
  const dir = tempRoot()
  const link = path.join(dir, 'scripts')
  symlinkSync(path.dirname(script), link, 'junction')
  const run = spawnSync(process.execPath, [path.join(link, 'loop-stats.mjs'), '--session'], {
    encoding: 'utf8',
  })
  assert.equal(run.status, 2)
  assert.match(run.stderr, /usage/)
})

const resume = (time, body) => ({
  type: 'user',
  timestamp: `2026-10-26T${time}Z`,
  message: { role: 'user', content: `The coordinator sent a message while you were working: ${body}` },
})
const toolResult = (time) => ({
  type: 'user',
  timestamp: `2026-10-26T${time}Z`,
  message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: 't1', content: 'x' }] },
})

test('an agent row splits at each SendMessage continuation, not at a tool result', () => {
  const dir = tempRoot()
  const file = path.join(dir, 'agent-b1.jsonl')
  writeFileSync(
    file,
    jsonl([
      user('10:00:00'),
      ...assistant('10:00:10', 'm1', 'claude-sonnet-5-5', usage(1, 1, 1, 1), [tool('t1')]),
      toolResult('10:00:20'),
      ...assistant('10:05:10', 'm2', 'claude-sonnet-5-5', usage(1, 1, 1, 1), [tool('t2')]),
      resume('10:20:00', 'continue'),
      ...assistant('10:20:05', 'm3', 'claude-sonnet-5-5', usage(1, 1, 1, 1), [tool('t3'), tool('t4')]),
      ...assistant('10:30:00', 'm4', 'claude-sonnet-5-5', usage(1, 1, 1, 1), [text]),
      resume('10:40:00', 'fix'),
      ...assistant('10:41:00', 'm5', 'claude-sonnet-5-5', usage(1, 1, 1, 1), [tool('t5')]),
    ]),
  )
  const agent = readTranscript(file)
  assert.deepEqual(
    agent.segments.map((s) => [s.kind, s.start, s.minutes, s.tools]),
    [
      ['dispatch', '2026-10-26T10:00:10Z', 5, 2],
      ['continuation', '2026-10-26T10:20:00Z', 10, 2],
      ['continuation', '2026-10-26T10:40:00Z', 1, 1],
    ],
  )
  assert.equal(agent.tools, 5)
  const out = formatStats({
    session: 's',
    agents: [{ ...agent, agentType: 'backend', description: 'x: y', model: 'm' }],
    bySlug: {},
    byModel: {},
    driver: { minutes: 0, tools: 0, outputTokens: 0, contextTokens: 0 },
  })
  assert.equal(out.split('\n').filter((l) => l.includes('continuation')).length, 2)
})

test('an agent with no continuation has one dispatch segment', () => {
  const { projectDir, session } = fixture()
  const stats = sessionStats(projectDir, session)
  assert.deepEqual(stats.agents[0].segments.map((s) => s.kind), ['dispatch'])
})

test('--help prints the usage and exits 0', () => {
  const run = spawnSync(process.execPath, [script, '--help'], { encoding: 'utf8' })
  assert.equal(run.status, 0)
  assert.match(run.stdout, /usage/)
})
