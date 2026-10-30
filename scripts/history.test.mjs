import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { after, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import {
  authFlagFrom,
  clearHarnessHistory,
  finishProject,
  resolveAuthMarkers,
  writeProjectReadme,
} from './history.mjs'

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

const mixed = [
  '# Doc',
  '| session | A record | table `session` <!-- auth --> |',
  '| module | Reference | `api/module/` |',
  '<!-- auth-start -->',
  '- Default: JWT',
  '<!-- auth-end -->',
  '<!-- noauth: - Auth: none. No accounts. -->',
  '<!-- noauth:   a planned change. -->',
  '- Client model',
  '',
].join('\n')

const made = []
after(() => made.forEach((dir) => rmSync(dir, { recursive: true, force: true })))

function tempRoot() {
  const dir = mkdtempSync(path.join(tmpdir(), 'history-'))
  made.push(dir)
  return dir
}

test('resolveAuthMarkers keeps an inline row without its marker when auth is on', () => {
  const out = resolveAuthMarkers('a\n| x | y <!-- auth --> |\nb', true)
  assert.equal(out, 'a\n| x | y |\nb')
})

test('resolveAuthMarkers drops an inline row when auth is off', () => {
  assert.equal(resolveAuthMarkers('a\n| x | y <!-- auth -->\nb', false), 'a\nb')
})

test('resolveAuthMarkers keeps or drops a block', () => {
  const text = 'a\n  <!-- auth-start -->\nx\ny\n<!-- auth-end -->\nb'
  assert.equal(resolveAuthMarkers(text, true), 'a\nx\ny\nb')
  assert.equal(resolveAuthMarkers(text, false), 'a\nb')
})

test('resolveAuthMarkers turns noauth lines into text or drops them', () => {
  const text = 'a\n  <!-- noauth: - none -->\n<!-- noauth:   more -->\nb'
  assert.equal(resolveAuthMarkers(text, false), 'a\n  - none\n  more\nb')
  assert.equal(resolveAuthMarkers(text, true), 'a\nb')
})

test('resolveAuthMarkers throws on an unclosed block', () => {
  assert.throws(() => resolveAuthMarkers('<!-- auth-start -->\nx', true), /auth-start/)
})

test('resolveAuthMarkers keeps the line ending and the trailing newline', () => {
  const crlf = resolveAuthMarkers(mixed.replace(/\n/g, '\r\n'), false)
  assert.ok(crlf.endsWith('\r\n'))
  assert.equal(crlf.replace(/\r\n/g, ''), crlf.replace(/[\r\n]/g, ''))
  assert.ok(!/(?<!\r)\n/.test(crlf))
  const lf = resolveAuthMarkers(mixed, true)
  assert.ok(!lf.includes('\r'))
  assert.ok(lf.endsWith('\n'))
})

test('resolveAuthMarkers returns a text with no marker unchanged', () => {
  const text = 'one\r\ntwo\r\n<!-- FILL: x -->\r\n'
  assert.equal(resolveAuthMarkers(text, true), text)
  assert.equal(resolveAuthMarkers(text, false), text)
})

test('resolveAuthMarkers leaves no marker in either variant', () => {
  for (const auth of [true, false]) {
    const out = resolveAuthMarkers(mixed, auth)
    assert.ok(!/<!-- (no)?auth/.test(out), out)
  }
  assert.ok(resolveAuthMarkers(mixed, false).includes('- Auth: none. No accounts.\n  a planned'))
  assert.ok(resolveAuthMarkers(mixed, true).includes('- Default: JWT'))
})

function git(root, ...args) {
  const flags = ['-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false']
  const run = spawnSync('git', ['-C', root, ...flags, ...args], { encoding: 'utf8' })
  assert.equal(run.status, 0, run.stderr)
}

// Plans are only the harness's to delete when git tracks them, so a seeded root is a repository.
function seed(root, { tracked = true } = {}) {
  mkdirSync(path.join(root, '.plan'))
  mkdirSync(path.join(root, '.doc'))
  for (const name of ['000-backlog.md', '001-a.md', '010-b.md', 'notes.md']) {
    writeFileSync(path.join(root, '.plan', name), 'x\n')
  }
  writeFileSync(
    path.join(root, '.doc', 'glossary.md'),
    '| Term |\n| session | s <!-- auth --> |\n| module | m |\n',
  )
  writeFileSync(path.join(root, '.doc', 'architecture.md'), mixed.replace(/\n/g, '\r\n'))
  if (tracked) {
    git(root, 'init', '-q')
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', 'seed')
  }
}

test('clearHarnessHistory removes plans and the auth text under auth off', () => {
  const root = tempRoot()
  seed(root)
  const result = clearHarnessHistory(root, { auth: false })
  assert.deepEqual(result.removedPlans, ['.plan/001-a.md', '.plan/010-b.md'])
  assert.deepEqual([...result.docs].sort(), ['.doc/architecture.md', '.doc/glossary.md'])
  assert.deepEqual(readdirSync(path.join(root, '.plan')).sort(), ['000-backlog.md', 'notes.md'])
  const glossary = readFileSync(path.join(root, '.doc', 'glossary.md'), 'utf8')
  assert.ok(!glossary.includes('session'))
  assert.ok(glossary.includes('| module | m |'))
  const arch = readFileSync(path.join(root, '.doc', 'architecture.md'), 'utf8')
  assert.ok(!/(?<!\r)\n/.test(arch))
  assert.ok(arch.includes('- Auth: none. No accounts.'))
  assert.ok(!arch.includes('JWT'))
})

test('clearHarnessHistory keeps the auth text under auth on', () => {
  const root = tempRoot()
  seed(root)
  clearHarnessHistory(root, { auth: true })
  const glossary = readFileSync(path.join(root, '.doc', 'glossary.md'), 'utf8')
  assert.ok(glossary.includes('| session | s |'))
  assert.ok(!glossary.includes('<!--'))
  const arch = readFileSync(path.join(root, '.doc', 'architecture.md'), 'utf8')
  assert.ok(arch.includes('- Default: JWT'))
  assert.ok(!arch.includes('none'))
})

test('clearHarnessHistory on an empty root returns empty lists and creates nothing', () => {
  const root = tempRoot()
  assert.deepEqual(clearHarnessHistory(root, { auth: true }), {
    removedPlans: [],
    keptPlans: [],
    docs: [],
  })
  assert.deepEqual(readdirSync(root), [])
})

test('authFlagFrom reads the resolved flag from the provenance', () => {
  const dir = tempRoot()
  const file = path.join(dir, 'catalog.yaml')
  writeFileSync(file, 'packages:\n  backend:\n    flags:\n      auth: false\n')
  assert.equal(authFlagFrom(file), false)
  writeFileSync(file, 'packages:\n  backend:\n    flags:\n      auth: true\n')
  assert.equal(authFlagFrom(file), true)
  assert.equal(authFlagFrom(path.join(dir, 'missing.yaml')), true)
  assert.ok(!existsSync(path.join(dir, 'missing.yaml')))
})

test("the repository's own .doc files resolve cleanly in both variants", () => {
  const glossary = readFileSync(path.join(repo, '.doc', 'glossary.md'), 'utf8')
  const arch = readFileSync(path.join(repo, '.doc', 'architecture.md'), 'utf8')
  // Conditional on content, so the test holds before and after a file is cleared: a file with
  // markers loses them in both variants, a file without any comes back unchanged.
  const marked = (text) => /<!--\s*(no)?auth|auth-(start|end)/.test(text)
  for (const text of [glossary, arch]) {
    for (const auth of [true, false]) {
      const out = resolveAuthMarkers(text, auth)
      if (marked(text)) assert.ok(!marked(out))
      else assert.equal(out, text)
    }
  }
  if (marked(glossary)) {
    const noAuthGlossary = resolveAuthMarkers(glossary, false)
    for (const term of ['session', 'caller', 'OTP', 'target']) {
      assert.ok(!noAuthGlossary.split('\n').some((line) => line.startsWith(`| ${term}`)))
    }
  }
  if (marked(arch)) assert.ok(resolveAuthMarkers(arch, false).includes('Auth: none'))
})

test('clearHarnessHistory keeps a modified tracked plan and an untracked plan', () => {
  const root = tempRoot()
  seed(root)
  writeFileSync(path.join(root, '.plan', '001-a.md'), 'edited by the product\n')
  writeFileSync(path.join(root, '.plan', '020-own.md'), 'new\n')
  const result = clearHarnessHistory(root, { auth: false })
  assert.deepEqual(result.removedPlans, ['.plan/010-b.md'])
  assert.deepEqual(result.keptPlans, ['.plan/001-a.md', '.plan/020-own.md'])
  const kept = readFileSync(path.join(root, '.plan', '001-a.md'), 'utf8')
  assert.equal(kept, 'edited by the product\n')
  assert.ok(existsSync(path.join(root, '.plan', '020-own.md')))
})

test('clearHarnessHistory keeps every plan when the root is not a git repository', () => {
  const root = tempRoot()
  seed(root, { tracked: false })
  const result = clearHarnessHistory(root, { auth: true })
  assert.deepEqual(result.removedPlans, [])
  assert.deepEqual(result.keptPlans, ['.plan/001-a.md', '.plan/010-b.md'])
  assert.deepEqual(readdirSync(path.join(root, '.plan')).sort(), [
    '000-backlog.md',
    '001-a.md',
    '010-b.md',
    'notes.md',
  ])
})

test('resolveAuthMarkers throws on a misspelled or misplaced marker', () => {
  for (const text of [
    'a <!--auth-->',
    'a <!-- auth --> trailing words',
    '<!-- authh -->',
    '<!--noauth: x -->',
    '<!--auth-start-->',
  ]) {
    assert.throws(() => resolveAuthMarkers(text, true), /auth marker|auth-start/, text)
    assert.throws(() => resolveAuthMarkers(text, false), /auth marker|auth-start/, text)
  }
})

test('resolveAuthMarkers takes an inline marker only at the end of the content', () => {
  assert.equal(resolveAuthMarkers('| r | c <!-- auth -->  ', true), '| r | c  ')
  assert.equal(resolveAuthMarkers('| r | c <!-- auth --> |  ', true), '| r | c |  ')
  assert.equal(resolveAuthMarkers('x <!-- auth -->  \ny', false), 'y')
})

test('clearHarnessHistory touches nothing when a marker is malformed', () => {
  const root = tempRoot()
  seed(root)
  writeFileSync(path.join(root, '.doc', 'architecture.md'), '<!-- auth-start -->\nx\n')
  const glossary = readFileSync(path.join(root, '.doc', 'glossary.md'), 'utf8')
  assert.throws(() => clearHarnessHistory(root, { auth: false }), /auth-start/)
  assert.ok(existsSync(path.join(root, '.plan', '001-a.md')))
  assert.equal(readFileSync(path.join(root, '.doc', 'glossary.md'), 'utf8'), glossary)
})

test('resolveAuthMarkers throws on a stray end and on a nested start', () => {
  assert.throws(() => resolveAuthMarkers('x\n<!-- auth-end -->\n', true), /auth-end/)
  const nested = '<!-- auth-start -->\n<!-- auth-start -->\n<!-- auth-end -->\n'
  assert.throws(() => resolveAuthMarkers(nested, true), /auth-start/)
})

test('resolveAuthMarkers handles an arrow in noauth text and no final newline', () => {
  assert.equal(resolveAuthMarkers('<!-- noauth: a --> b -->', false), 'a --> b')
  assert.equal(resolveAuthMarkers('a\n<!-- noauth: b -->', false), 'a\nb')
  assert.equal(resolveAuthMarkers('a\n| r | c <!-- auth --> |', true), 'a\n| r | c |')
})

// A project fixture: a repository whose second commit pins the first as the manifest's rootCommit.
const GITIGNORE = [
  '# >>> harness: replaced on harness updates, do not edit inside this block',
  '.orchestrate/*',
  '# <<< harness',
  '',
  '# >>> harness-dev: removed at setup',
  'node_modules/',
  '# <<< harness-dev',
  '',
].join('\n')

function gitOut(root, ...args) {
  const run = spawnSync(
    'git',
    ['-c', 'user.name=t', '-c', 'user.email=t@example.com', '-C', root, ...args],
    { encoding: 'utf8' },
  )
  assert.equal(run.status, 0, run.stderr)
  return run.stdout.trim()
}

function put(root, file, text) {
  mkdirSync(path.dirname(path.join(root, file)), { recursive: true })
  writeFileSync(path.join(root, file), text)
}

function manifestText(rootCommit) {
  return JSON.stringify({
    format: 1,
    version: '1.2.3',
    repository: 'https://example.com/h',
    rootCommit,
    minCatalog: 'v1.0.0',
    groups: {
      harness: ['.claude/settings.json', '.claude/harness.json', 'AGENTS.md'],
      project: ['README.md', '.gitignore'],
      dev: [
        'scripts/bootstrap.mjs',
        'scripts/history.mjs',
        '.plan/*.md',
        '!.plan/000-backlog.md',
        'tmpdev/**',
      ],
    },
    references: [],
  })
}

function project({ keepHistory = true } = {}) {
  const root = tempRoot()
  gitOut(root, 'init', '-q')
  put(root, '.claude/harness.json', manifestText('0'.repeat(40)))
  put(root, '.claude/settings.json', '{"hooks":{}}\n')
  put(root, 'AGENTS.md', 'rules\n')
  put(root, 'README.md', '# harness\n')
  put(root, '.gitignore', GITIGNORE)
  put(root, '.fullstack/catalog.yaml', 'packages:\n')
  put(root, 'scripts/bootstrap.mjs', 'x\n')
  put(root, 'scripts/history.mjs', 'x\n')
  put(root, '.plan/000-backlog.md', 'queue\n')
  put(root, '.plan/001-clean.md', 'plan\n')
  put(root, '.plan/002-edited.md', 'plan\n')
  put(root, 'tmpdev/sub/a.mjs', 'x\n')
  gitOut(root, 'add', '-A')
  gitOut(root, 'commit', '-q', '-m', 'root')
  const first = gitOut(root, 'rev-parse', 'HEAD')
  put(root, '.claude/harness.json', manifestText(keepHistory ? first : 'f'.repeat(40)))
  gitOut(root, 'commit', '-q', '-am', 'pin')
  put(root, '.plan/002-edited.md', 'mine\n')
  put(root, '.plan/003-new.md', 'mine\n')
  return root
}

test('finishProject removes only unmodified tracked dev files and the empty folders', () => {
  const root = project()
  finishProject(root)
  for (const gone of ['scripts/bootstrap.mjs', 'scripts/history.mjs', '.plan/001-clean.md']) {
    assert.equal(existsSync(path.join(root, gone)), false, gone)
  }
  assert.equal(existsSync(path.join(root, 'tmpdev')), false)
  for (const kept of [
    '.plan/002-edited.md',
    '.plan/003-new.md',
    '.plan/000-backlog.md',
    'README.md',
  ]) {
    assert.ok(existsSync(path.join(root, kept)), kept)
  }
})

test('finishProject removes the gitignore dev block and keeps the harness block', () => {
  const root = project()
  finishProject(root)
  const text = readFileSync(path.join(root, '.gitignore'), 'utf8')
  assert.doesNotMatch(text, /harness-dev|node_modules/)
  assert.match(text, /# >>> harness:/)
  assert.match(text, /# <<< harness\n$/)
})

test('finishProject records the version and a hash per harness file', () => {
  const root = project()
  const head = gitOut(root, 'rev-parse', 'HEAD')
  finishProject(root)
  const record = JSON.parse(readFileSync(path.join(root, '.fullstack', 'harness.json'), 'utf8'))
  assert.equal(record.version, '1.2.3')
  assert.equal(record.commit, head)
  assert.deepEqual(Object.keys(record.files), [
    '.claude/harness.json',
    '.claude/settings.json',
    'AGENTS.md',
  ])
  assert.match(record.files['AGENTS.md'], /^[0-9a-f]{64}$/)
})

test('finishProject warns on harness history and records no commit without it', () => {
  const kept = finishProject(project())
  assert.match(kept.warnings.join('\n'), /Use this template/)
  const root = project({ keepHistory: false })
  const fresh = finishProject(root)
  assert.deepEqual(fresh.warnings, [])
  const record = JSON.parse(readFileSync(path.join(root, '.fullstack', 'harness.json'), 'utf8'))
  assert.equal(record.commit, null)
})

test('finishProject refuses a README that still holds a placeholder, changing nothing', () => {
  const root = project()
  put(root, 'README.md', '# p\n<!-- readme:about -->\n')
  assert.throws(() => finishProject(root), /README\.md.*<!-- readme:/)
  assert.ok(existsSync(path.join(root, 'scripts', 'bootstrap.mjs')))
  assert.equal(existsSync(path.join(root, '.fullstack', 'harness.json')), false)
})

test('finishProject refuses a tree that was never bootstrapped', () => {
  const root = project()
  rmSync(path.join(root, '.fullstack', 'catalog.yaml'))
  assert.throws(() => finishProject(root), /catalog\.yaml/)
})

const CATALOG = [
  'deploy: split',
  'packages:',
  '  backend:',
  '    template: server/bun-express',
  '    commands:',
  '      install: bun install',
  '      dev: bun run dev',
  '      check: bun run check',
  '      test: bun test',
  '    http:',
  '      port: 4000',
  '  frontend:',
  '    template: frontend/next',
  '    commands:',
  '      install: bun install',
  '      dev: bun run dev',
  '      check: bun run check',
  '      testE2e: bun run test:e2e',
  '    http:',
  '      port: 3000',
  '',
].join('\n')

const TEMPLATE_YAML = {
  'server/bun-express': "tools:\n  - { name: bun, min: '1.4' }\n  - { name: node, min: '24' }\n",
  'frontend/next': 'tools:\n  - { name: bun, min: "1.4" }\n  - { name: node, min: "24" }\n',
  'server/python-fastapi': "tools:\n  - { name: uv, min: '0.12.23', max: '0.14' }\nflags: {}\n",
}

function catalogRoot() {
  const dir = tempRoot()
  for (const [template, yaml] of Object.entries(TEMPLATE_YAML)) {
    put(dir, `${template}/template.yaml`, yaml)
  }
  return dir
}

function readmeFixture({ remote = true } = {}) {
  const root = tempRoot()
  gitOut(root, 'init', '-q')
  if (remote) gitOut(root, 'remote', 'add', 'origin', 'https://example.com/me/plant-care.git')
  put(root, '.fullstack/catalog.yaml', CATALOG)
  put(root, 'backend/.env.example', '# Port to listen on\nPORT=4000\n')
  put(root, 'docker-compose.yml', 'services: {}\n')
  put(root, 'README.md', '# harness\n')
  const template = path.join(repo, '.claude', 'skills', 'bootstrap-project', 'readme-template.md')
  return { root, template }
}

test('writeProjectReadme fills every mechanical part from the catalog', () => {
  const { root, template } = readmeFixture()
  writeProjectReadme(root, 'plant-care', template, catalogRoot())
  const text = readFileSync(path.join(root, 'README.md'), 'utf8')
  assert.match(text, /^# plant-care$/m)
  assert.match(text, /git clone https:\/\/example\.com\/me\/plant-care\.git/)
  assert.match(text, /cd plant-care/)
  assert.match(text, /cd backend\nbun install\ncd \.\./)
  assert.match(text, /cd frontend\nbun run dev\ncd \.\./)
  assert.match(text, /http:\/\/localhost:3000/)
  assert.match(text, /cd backend\nbun run check\nbun test\ncd \.\./)
  assert.match(text, /cd frontend\nbun run check\nbun run test:e2e\ncd \.\./)
  assert.doesNotMatch(text, /&&|\(cd /)
  assert.match(text, /own terminal/)
  assert.match(text, /- node 24\+/)
  assert.match(text, /- bun 1\.4\+/)
  assert.match(text, /- git/)
  assert.match(text, /Docker with Compose v2/)
  assert.match(text, /docker compose --profile app up --build/)
  assert.match(text, /<!-- configuration:start -->[\s\S]*`PORT`[\s\S]*<!-- configuration:end -->/)
  assert.match(text, /<!-- readme:about -->/)
  assert.match(text, /<!-- readme:features -->/)
  assert.match(text, /No license has been chosen yet/)
  assert.doesNotMatch(text, /\{\{/)
})

test('writeProjectReadme falls back to a placeholder URL and names a LICENSE file', () => {
  const { root, template } = readmeFixture({ remote: false })
  put(root, 'LICENSE', 'MIT\n')
  rmSync(path.join(root, 'docker-compose.yml'))
  writeProjectReadme(root, 'plant-care', template)
  const text = readFileSync(path.join(root, 'README.md'), 'utf8')
  assert.match(text, /git clone <repository-url>/)
  assert.match(text, /\[LICENSE\]\(LICENSE\)/)
  assert.doesNotMatch(text, /Docker with Compose|docker compose/)
})

test('writeProjectReadme refuses a template token it cannot fill', () => {
  const { root } = readmeFixture()
  const bad = path.join(root, 'bad.md')
  writeFileSync(bad, '# {{name}}\n{{mystery}}\n')
  assert.throws(() => writeProjectReadme(root, 'x', bad), /mystery/)
})

function writeReadme(root, template, catalog = catalogRoot()) {
  writeProjectReadme(root, 'plant-care', template, catalog)
  return readFileSync(path.join(root, 'README.md'), 'utf8')
}

test('the README lists the declared tools of each template, once, with their minimum', () => {
  const { root, template } = readmeFixture()
  put(
    root,
    '.fullstack/catalog.yaml',
    CATALOG.replace('server/bun-express', 'server/python-fastapi'),
  )
  const text = writeReadme(root, template)
  assert.match(text, /- uv 0\.12\.23\+/)
  assert.match(text, /- node 24\+/)
  assert.match(text, /- bun 1\.4\+/)
  assert.equal(text.match(/- node 24\+/g).length, 1)
  assert.match(text, /- Docker with Compose v2/)
  assert.match(text, /- git/)
})

test('the README names no tool that no template declares', () => {
  const { root, template } = readmeFixture()
  put(
    root,
    '.fullstack/catalog.yaml',
    'deploy: split\npackages:\n  a:\n    template: server/none\n',
  )
  const text = writeReadme(root, template)
  assert.doesNotMatch(text, /- (node|bun|uv)/)
  assert.match(text, /- git/)
})

test('single deploy: the dev URL is the frontend port, Compose names the server port', () => {
  const { root, template } = readmeFixture()
  put(root, '.fullstack/catalog.yaml', CATALOG.replace('deploy: split', 'deploy: single'))
  const text = writeReadme(root, template)
  assert.match(text, /Open http:\/\/localhost:3000 once the dev servers/)
  assert.match(text, /Compose[^\n]*http:\/\/localhost:4000/)
})

test('split deploy: Compose names the frontend port', () => {
  const { root, template } = readmeFixture()
  const text = writeReadme(root, template)
  assert.match(text, /Compose[^\n]*http:\/\/localhost:3000/)
})

test('the README title is the brand display name when the catalog records one', () => {
  const { root, template } = readmeFixture()
  put(
    root,
    '.fullstack/catalog.yaml',
    `${CATALOG}answers:\n  projectName: plant-care\n  brand:\n    displayName: Plant Care Studio\n`,
  )
  assert.match(writeReadme(root, template), /^# Plant Care Studio$/m)
})

test('a section no package declares commands for has no empty fence', () => {
  const { root, template } = readmeFixture()
  put(root, '.fullstack/catalog.yaml', 'deploy: split\npackages:\n  a:\n    template: x/y\n')
  const text = writeReadme(root, template)
  assert.doesNotMatch(text, /```bash\n\s*```/)
})

function unbootstrapped() {
  const root = tempRoot()
  gitOut(root, 'init', '-q')
  put(root, '.claude/harness.json', manifestText('0'.repeat(40)))
  put(root, '.claude/settings.json', '{"hooks":{}}\n')
  put(root, 'AGENTS.md', 'rules\n')
  put(root, 'README.md', '# p\n')
  put(root, '.gitignore', GITIGNORE)
  put(root, '.fullstack/catalog.yaml', 'packages:\n')
  put(root, 'scripts/bootstrap.mjs', 'x\n')
  return root
}

test('finishProject refuses a repository with no commit, writing nothing', () => {
  const root = unbootstrapped()
  gitOut(root, 'add', '-A')
  assert.throws(() => finishProject(root), /no commit/)
  assert.equal(existsSync(path.join(root, '.fullstack', 'harness.json')), false)
  assert.ok(existsSync(path.join(root, 'scripts', 'bootstrap.mjs')))
  assert.equal(readFileSync(path.join(root, '.gitignore'), 'utf8'), GITIGNORE)
})

test('finishProject refuses when no harness file is tracked', () => {
  const root = tempRoot()
  gitOut(root, 'init', '-q')
  put(root, '.claude/harness.json', manifestText('0'.repeat(40)))
  put(root, '.fullstack/catalog.yaml', 'packages:\n')
  put(root, 'README.md', '# p\n')
  put(root, 'other.txt', 'x\n')
  gitOut(root, 'add', 'other.txt', 'README.md')
  gitOut(root, 'commit', '-q', '-m', 'root')
  assert.throws(() => finishProject(root), /harness files/)
})

test('finishProject keeps a staged-new dev file and lists it', () => {
  const root = project()
  put(root, 'tmpdev/new.mjs', 'x\n')
  gitOut(root, 'add', 'tmpdev/new.mjs')
  const { actions } = finishProject(root)
  assert.ok(existsSync(path.join(root, 'tmpdev', 'new.mjs')))
  assert.match(actions.join('\n'), /kept[^\n]*tmpdev\/new\.mjs/)
})

test('finishProject neither removes nor lists a tracked dev file already deleted on disk', () => {
  const root = project()
  rmSync(path.join(root, 'tmpdev', 'sub', 'a.mjs'))
  const { actions } = finishProject(root)
  assert.doesNotMatch(actions.join('\n'), /tmpdev\/sub\/a\.mjs/)
  assert.doesNotMatch(actions.join('\n'), /kept[^\n]*\.plan\/001-clean\.md/)
})

function readmeFor(origin, { harnessUrl = 'https://example.com/h', name = 'plant-care' } = {}) {
  const { root, template } = readmeFixture({ remote: false })
  if (origin !== undefined) gitOut(root, 'remote', 'add', 'origin', origin)
  put(root, '.claude/harness.json', JSON.stringify({ repository: harnessUrl }))
  writeProjectReadme(root, name, template, catalogRoot())
  return readFileSync(path.join(root, 'README.md'), 'utf8')
}

test('the README hides an origin that is the harness repository, with or without .git', () => {
  for (const origin of ['https://example.com/h', 'HTTPS://example.com/H.git/']) {
    const text = readmeFor(origin)
    assert.match(text, /git clone <repository-url>\ncd plant-care\n/, origin)
  }
})

test('the README hides a local filesystem origin', () => {
  for (const origin of ['C:/Dev/harness', '/srv/harness', './harness', '../harness']) {
    assert.match(readmeFor(origin), /git clone <repository-url>\ncd plant-care\n/, origin)
  }
  assert.match(readmeFor('file:///srv/harness'), /git clone <repository-url>\ncd plant-care\n/)
})

test('the README keeps the origin of a real product repository', () => {
  const text = readmeFor('https://example.com/me/plant-care.git')
  assert.match(text, /git clone https:\/\/example\.com\/me\/plant-care\.git\ncd plant-care\n/)
})

test('the README uses the placeholder and the project name when there is no origin', () => {
  assert.match(readmeFor(undefined, { name: 'zed' }), /git clone <repository-url>\ncd zed\n/)
})

test('finishProject lists a modified dev file as kept', () => {
  const { actions } = finishProject(project())
  assert.match(actions.join('\n'), /kept[^\n]*\.plan\/002-edited\.md/)
})

test('finishProject never removes a dev file that is also in another group', () => {
  const root = project()
  const both = JSON.parse(manifestText(gitOut(root, 'rev-parse', 'HEAD~1')))
  both.groups.dev.push('AGENTS.md')
  put(root, '.claude/harness.json', JSON.stringify(both))
  gitOut(root, 'commit', '-q', '-am', 'overlap')
  finishProject(root)
  assert.ok(existsSync(path.join(root, 'AGENTS.md')))
})

test('finishProject with an unterminated dev block throws before any write', () => {
  const root = project()
  const broken = GITIGNORE.replace('# <<< harness-dev\n', '')
  put(root, '.gitignore', broken)
  gitOut(root, 'commit', '-q', '-am', 'broken')
  assert.throws(() => finishProject(root), /harness-dev/)
  assert.equal(readFileSync(path.join(root, '.gitignore'), 'utf8'), broken)
  assert.equal(existsSync(path.join(root, '.fullstack', 'harness.json')), false)
  assert.ok(existsSync(path.join(root, 'scripts', 'bootstrap.mjs')))
})

test('finishProject refuses a missing README and any spelling of the placeholder', () => {
  const root = project()
  rmSync(path.join(root, 'README.md'))
  assert.throws(() => finishProject(root), /README\.md is missing/)
  put(root, 'README.md', '# p\n<!--readme:about-->\n')
  assert.throws(() => finishProject(root), /placeholder/)
  put(root, 'README.md', '# p\n<!--   readme: features -->\n')
  assert.throws(() => finishProject(root), /placeholder/)
})

test('finishProject warns about harness files modified against HEAD', () => {
  const root = project()
  put(root, 'AGENTS.md', 'my rules\n')
  const { warnings } = finishProject(root)
  assert.match(warnings.join('\n'), /AGENTS\.md[^\n]*(modified|harness content)/)
})
