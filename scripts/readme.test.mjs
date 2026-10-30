import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { after, describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'
import {
  extractConfiguration,
  parseEnvExample,
  renderConfiguration,
  replaceConfiguration,
} from './readme.mjs'

const script = path.join(path.dirname(fileURLToPath(import.meta.url)), 'readme.mjs')
const START = '<!-- configuration:start -->'
const END = '<!-- configuration:end -->'
const EXAMPLE = '.env.example'
const bases = []
const tests = []
const test = (name, run) => tests.push([name, run])

function repo(files) {
  const root = mkdtempSync(path.join(tmpdir(), 'readme-'))
  bases.push(root)
  for (const [name, text] of Object.entries(files)) {
    mkdirSync(path.dirname(path.join(root, name)), { recursive: true })
    writeFileSync(path.join(root, name), text)
  }
  spawnSync('git', ['init', '-q'], { cwd: root })
  spawnSync('git', ['add', '-A'], { cwd: root })
  return root
}

const cli = (root, ...args) =>
  spawnSync(process.execPath, [script, ...args], { cwd: root, encoding: 'utf8' })

after(() => {
  for (const dir of bases) rmSync(dir, { recursive: true, force: true })
})

test('a comment block directly above a variable is its description, a header is not', () => {
  const text = '# File header.\n\n# Port the\n# API uses.\nPORT=4000\nNAME=x\n'
  assert.deepEqual(parseEnvExample(text), [
    { name: 'PORT', description: 'Port the API uses.', value: '4000', optional: false },
    { name: 'NAME', description: '', value: 'x', optional: false },
  ])
})

test('an empty value and a change-me placeholder have no default', () => {
  const vars = parseEnvExample('A=\nB=change-me-please\nC=ok\n')
  assert.deepEqual(
    vars.map((v) => v.value),
    [undefined, undefined, 'ok'],
  )
})

test('a commented assignment is an optional variable, other comments are prose', () => {
  const text =
    '# Header header.\n# Sets the header.\n# CLIENT_IP_HEADER=x-real-ip\n# NOTE=not a var\n# Set a=b here\nX=1\n'
  const vars = parseEnvExample(text)
  assert.equal(vars[0].name, 'CLIENT_IP_HEADER')
  assert.equal(vars[0].optional, true)
  assert.equal(vars[0].value, 'x-real-ip')
  assert.equal(vars[0].description, 'Header header. Sets the header.')
  assert.equal(vars[1].name, 'NOTE')
  assert.equal(vars[2].description, 'Set a=b here')
  assert.equal(parseEnvExample('# LONE\n# BARE=\n')[0].value, undefined)
})

test('CRLF input parses like LF', () => {
  assert.deepEqual(parseEnvExample('# d\r\nA=1\r\n'), parseEnvExample('# d\nA=1\n'))
})

test('the block renders rows with dashes, backticks and optional defaults', () => {
  const root = repo({
    [EXAMPLE]: '# One | two.\nA=1\nB=\nC=change-me-x\n# Maybe.\n# D=ex\n# E=\n',
  })
  const lines = renderConfiguration(root).split('\n')
  assert.deepEqual(lines, [
    START,
    '| Variable | Description | Default |',
    '| --- | --- | --- |',
    '| `A` | One \\| two. | `1` |',
    '| `B` |  | — |',
    '| `C` |  | — |',
    '| `D` | Maybe. | optional (example `ex`) |',
    '| `E` |  | optional |',
    END,
  ])
})

test('several files are sorted by path and prefixed with their directory', () => {
  const root = repo({
    [`frontend/${EXAMPLE}`]: '# Server URL.\nPORT=3000\n',
    [`backend/${EXAMPLE}`]: '# Port the API listens on.\nPORT=4000\n',
  })
  const rows = renderConfiguration(root).split('\n').slice(3, -1)
  assert.deepEqual(rows, [
    '| `PORT` | backend: Port the API listens on. | `4000` |',
    '| `PORT` | frontend: Server URL. | `3000` |',
  ])
})

test('an empty comment line adds no double space', () => {
  assert.equal(parseEnvExample('# a\n#\n# b\nX=1\n')[0].description, 'a b')
})

test('an example deleted but not staged leaves the table', () => {
  const root = repo({
    [`backend/${EXAMPLE}`]: 'A=1\n',
    [`frontend/${EXAMPLE}`]: 'B=2\n',
    'README.md': `${START}\nx\n${END}\n`,
  })
  spawnSync('git', ['-c', 'user.email=t@e.x', '-c', 'user.name=t', 'commit', '-qm', 'i'], {
    cwd: root,
  })
  rmSync(path.join(root, 'backend', EXAMPLE))
  const rows = renderConfiguration(root).split('\n').slice(3, -1)
  assert.deepEqual(rows, ['| `B` |  | `2` |'])
  assert.equal(cli(root, '--configuration').status, 0)
})

test('no example file renders the sentence', () => {
  const root = repo({ 'a.txt': 'x' })
  assert.equal(
    renderConfiguration(root),
    `${START}\nThis project reads no environment variables.\n${END}`,
  )
})

test('replaceConfiguration swaps the block and keeps CRLF', () => {
  const block = `${START}\nnew\n${END}`
  const text = `# T\r\n${START}\r\nold\r\nolder\r\n${END}\r\nafter\r\n`
  assert.equal(replaceConfiguration(text, block), `# T\r\n${START}\r\nnew\r\n${END}\r\nafter\r\n`)
  assert.equal(replaceConfiguration(`a\n${START}\nx\n${END}`, block), `a\n${block}`)
  assert.equal(extractConfiguration(`a\r\n${START}\r\nx\r\n${END}\r\nb`), `${START}\nx\n${END}`)
})

test('replaceConfiguration throws on missing, duplicated or reversed markers', () => {
  const block = `${START}\nn\n${END}`
  assert.throws(() => replaceConfiguration('nothing', block), /marker/)
  assert.throws(() => replaceConfiguration(`${START}\nx\n`, block), /marker/)
  assert.throws(() => replaceConfiguration(`${START}\n${END}\n${START}\n${END}`, block), /marker/)
  assert.throws(() => replaceConfiguration(`${END}\n${START}`, block), /order/)
})

test('the CLI rewrites only the block', () => {
  const root = repo({
    [EXAMPLE]: 'A=1\n',
    'README.md': `# T\n\n${START}\nstale\n${END}\n\nTail\n`,
  })
  const run = cli(root, '--configuration')
  assert.equal(run.status, 0, run.stderr)
  const text = readFileSync(path.join(root, 'README.md'), 'utf8')
  assert.ok(text.startsWith('# T\n\n'))
  assert.ok(text.endsWith('\n\nTail\n'))
  assert.ok(text.includes('| `A` |  | `1` |'))
  assert.equal(cli(root, '--configuration', '--root', root).status, 0)
})

test('the CLI fails with one line on a missing README or markers, usage on bad args', () => {
  const root = repo({ 'x.txt': '' })
  const noReadme = cli(root, '--configuration')
  assert.equal(noReadme.status, 1)
  assert.match(noReadme.stderr, /README\.md/)
  writeFileSync(path.join(root, 'README.md'), '# T\n')
  const noMarkers = cli(root, '--configuration')
  assert.equal(noMarkers.status, 1)
  assert.equal(noMarkers.stderr.trim().split('\n').length, 1)
  const bad = cli(root, '--nope')
  assert.equal(bad.status, 2)
  assert.match(bad.stderr, /usage/)
  assert.equal(cli(root).status, 2)
})

describe('readme', { concurrency: 6 }, () => {
  for (const [name, run] of tests) it(name, run)
})
