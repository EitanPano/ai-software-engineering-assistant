import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { after, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { failingHook } from './harness-update.mjs'
import { buildRecord, readRecord, writeRecord } from './manifest.mjs'

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), 'harness-update.mjs')
const made = []
// The updater leaves its backups in os.tmpdir(); the children get a temp root the tests own.
const TMP_ROOT = mkdtempSync(join(tmpdir(), 'hu-tmproot-'))
made.push(TMP_ROOT)
const childEnv = (extra = {}) => ({
  ...process.env,
  TMP: TMP_ROOT,
  TEMP: TMP_ROOT,
  TMPDIR: TMP_ROOT,
  ...extra,
})
after(() => made.forEach((dir) => rmSync(dir, { recursive: true, force: true })))

const git = (cwd, ...args) => execFileSync('git', args, { cwd, encoding: 'utf8' })
const block = (lines) =>
  '# >>> harness: replaced on harness updates, do not edit inside this block\n' +
  `${lines.join('\n')}\n# <<< harness\n`
const HOOK_OK = 'process.exit(0)\n'
const HOOK_BAD = 'process.exit(3)\n'

function settings(allow) {
  return {
    permissions: { allow, deny: ['Bash(rm -rf*)'] },
    hooks: {
      PreToolUse: [
        {
          matcher: '*',
          hooks: [
            {
              type: 'command',
              command: 'node',
              args: ['${CLAUDE_PROJECT_DIR}/.claude/hooks/check.mjs'],
              timeout: 10,
            },
          ],
        },
      ],
    },
  }
}

function put(root, files) {
  for (const [file, content] of Object.entries(files)) {
    mkdirSync(dirname(join(root, file)), { recursive: true })
    const text = typeof content === 'string' ? content : `${JSON.stringify(content, null, 2)}\n`
    writeFileSync(join(root, file), text)
  }
}

function manifest(version, minCatalog = 'v1.0.0', repository = 'unused') {
  return {
    format: 1,
    version,
    repository,
    rootCommit: 'x',
    minCatalog,
    groups: {
      harness: [
        '.claude/skills/**',
        '.claude/settings.json',
        '.claude/hooks/*.mjs',
        '.claude/harness.json',
        'AGENTS.md',
      ],
      project: ['README.md', '.doc/**', 'catalog.lock', '.gitignore'],
      dev: [],
    },
    references: [],
  }
}

function repo(files, { tag } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'hu-test-'))
  made.push(dir)
  git(dir, 'init', '-q')
  git(dir, 'config', 'user.email', 't@t')
  git(dir, 'config', 'user.name', 't')
  git(dir, 'config', 'commit.gpgsign', 'false')
  put(dir, files)
  git(dir, 'add', '-A')
  git(dir, 'commit', '-qm', 'release')
  if (tag) git(dir, 'tag', tag)
  return dir
}

const LOCK = (version) => ({ repository: 'r', version, commit: 'c' })

function release(version, extra = {}, options = {}) {
  const { allow = ['Bash(ls*)'], hook = HOOK_OK, minCatalog, ignore = ['.a'], repository } = options
  return {
    '.claude/harness.json': manifest(version, minCatalog, repository),
    '.claude/settings.json': settings(allow),
    '.claude/hooks/check.mjs': hook,
    '.claude/skills/core/SKILL.md': `core ${version}\n`,
    'AGENTS.md': `agents ${version}\n`,
    'README.md': `readme ${version}\n`,
    '.doc/glossary.md': `glossary ${version}\n`,
    'catalog.lock': LOCK('v1.5.0'),
    '.gitignore': block(ignore),
    ...extra,
  }
}

const SEEDS = ['README.md', '.gitignore', 'catalog.lock']

// A project that took a release at setup: its files copied, the record written, committed.
function project(files, { lock = 'v1.5.0', commit = null } = {}) {
  const dir = repo({ ...files, 'catalog.lock': LOCK(lock) })
  const shipped = Object.keys(files).filter((f) => !SEEDS.includes(f) && !f.startsWith('.doc'))
  writeRecord(dir, buildRecord(dir, files['.claude/harness.json'], { commit, files: shipped }))
  git(dir, 'add', '-A')
  git(dir, 'commit', '-qm', 'setup')
  return dir
}

function run(root, ...args) {
  const result = spawnSync('node', [SCRIPT, '--root', root, ...args], {
    encoding: 'utf8',
    env: childEnv(),
  })
  return { status: result.status, out: result.stdout + result.stderr }
}

const read = (root, file) => readFileSync(join(root, file), 'utf8')

test('replaces harness files, deletes dropped ones, keeps project files and entries', () => {
  const proj = project(release('1.0.0', { '.claude/skills/old/SKILL.md': 'old\n' }))
  put(proj, { '.claude/skills/mine/SKILL.md': 'mine\n', 'README.md': 'my readme\n' })
  const edited = JSON.parse(read(proj, '.claude/settings.json'))
  edited.permissions.allow.push('Bash(make*)')
  edited.permissions.deny.push('Bash(curl*)')
  put(proj, {
    '.claude/settings.json': edited,
    '.gitignore': `${block(['.a'])}\n# mine\nmine/\n`,
  })
  git(proj, 'add', '-A')
  git(proj, 'commit', '-qm', 'project edits')

  const src = repo(
    release('1.1.0', {}, { allow: ['Bash(ls*)', 'Bash(pwd*)'], ignore: ['.a', '.b'] }),
  )
  const result = run(proj, '--from', src)
  assert.equal(result.status, 0, result.out)
  assert.equal(read(proj, '.claude/skills/core/SKILL.md'), 'core 1.1.0\n')
  assert.equal(existsSync(join(proj, '.claude/skills/old')), false)
  assert.equal(read(proj, '.claude/skills/mine/SKILL.md'), 'mine\n')
  assert.equal(read(proj, 'README.md'), 'my readme\n')
  const merged = JSON.parse(read(proj, '.claude/settings.json'))
  assert.deepEqual(merged.permissions.allow, ['Bash(ls*)', 'Bash(pwd*)', 'Bash(make*)'])
  assert.deepEqual(merged.permissions.deny, ['Bash(rm -rf*)', 'Bash(curl*)'])
  assert.equal(read(proj, '.gitignore'), `${block(['.a', '.b'])}\n# mine\nmine/\n`)
  const record = readRecord(proj)
  assert.equal(record.version, '1.1.0')
  assert.equal(record.commit, git(src, 'rev-parse', 'HEAD').trim())
  assert.deepEqual(record.settings.permissions.allow, ['Bash(ls*)', 'Bash(pwd*)'])
  assert.equal('.claude/skills/old/SKILL.md' in record.files, false)
  assert.equal('.claude/skills/mine/SKILL.md' in record.files, false)
})

test('a second update still recognises the project entries', () => {
  const proj = project(release('1.0.0'))
  const edited = JSON.parse(read(proj, '.claude/settings.json'))
  edited.permissions.allow.push('Bash(make*)')
  put(proj, { '.claude/settings.json': edited })
  git(proj, 'commit', '-qam', 'entry')
  assert.equal(run(proj, '--from', repo(release('1.1.0'))).status, 0)
  git(proj, 'add', '-A')
  git(proj, 'commit', '-qm', 'update')
  const result = run(proj, '--from', repo(release('1.2.0')))
  assert.equal(result.status, 0, result.out)
  const allow = JSON.parse(read(proj, '.claude/settings.json')).permissions.allow
  assert.ok(allow.includes('Bash(make*)'))
})

test('inserts the block at the top when the project has none', () => {
  const proj = project(release('1.0.0'))
  put(proj, { '.gitignore': 'node_modules/\n' })
  git(proj, 'commit', '-qam', 'ignore')
  assert.equal(run(proj, '--from', repo(release('1.1.0'))).status, 0)
  assert.equal(read(proj, '.gitignore'), `${block(['.a'])}\nnode_modules/\n`)
})

test('refuses a dirty tree', () => {
  const proj = project(release('1.0.0'))
  put(proj, { 'notes.txt': 'x' })
  const result = run(proj, '--from', repo(release('1.1.0')))
  assert.equal(result.status, 1)
  assert.match(result.out, /dirty/)
  assert.equal(read(proj, 'AGENTS.md'), 'agents 1.0.0\n')
})

test('stops on a local edit and a missing harness file unless --overwrite', () => {
  const proj = project(release('1.0.0'))
  put(proj, { 'AGENTS.md': 'edited\n' })
  rmSync(join(proj, '.claude/skills/core/SKILL.md'))
  git(proj, 'add', '-A')
  git(proj, 'commit', '-qm', 'edit')
  const src = repo(release('1.1.0'))
  const refused = run(proj, '--from', src)
  assert.equal(refused.status, 1)
  assert.match(refused.out, /AGENTS\.md \(modified\)/)
  assert.match(refused.out, /SKILL\.md \(missing\)/)
  assert.equal(read(proj, 'AGENTS.md'), 'edited\n')
  const forced = run(proj, '--from', src, '--overwrite')
  assert.equal(forced.status, 0, forced.out)
  assert.equal(read(proj, 'AGENTS.md'), 'agents 1.1.0\n')
})

test('refuses without a version record and points to the manual path', () => {
  const proj = repo(release('1.0.0'))
  const result = run(proj, '--from', repo(release('1.1.0')))
  assert.equal(result.status, 1)
  assert.match(result.out, /\.claude\/README\.md/)
})

test('refuses a release whose path is a project file, writing nothing', () => {
  const proj = project(release('1.0.0'))
  put(proj, { '.claude/skills/extra/SKILL.md': 'mine\n' })
  git(proj, 'add', '-A')
  git(proj, 'commit', '-qm', 'mine')
  const src = repo(release('1.1.0', { '.claude/skills/extra/SKILL.md': 'theirs\n' }))
  const result = run(proj, '--from', src)
  assert.equal(result.status, 1)
  assert.match(result.out, /extra\/SKILL\.md/)
  assert.equal(read(proj, '.claude/skills/extra/SKILL.md'), 'mine\n')
  assert.equal(read(proj, 'AGENTS.md'), 'agents 1.0.0\n')
})

test('refuses a minCatalog above the lock, naming the newest compatible tag', () => {
  const src = repo(release('1.0.0', {}, { minCatalog: 'v1.0.0' }), { tag: 'v1.0.0' })
  put(src, release('2.0.0', {}, { minCatalog: 'v1.4.0' }))
  git(src, 'commit', '-qam', 'two')
  git(src, 'tag', 'v1.1.0')
  put(src, release('3.0.0', {}, { minCatalog: 'v1.9.0' }))
  git(src, 'commit', '-qam', 'three')
  git(src, 'tag', 'v1.2.0')
  const proj = project(release('1.0.0'), { lock: 'v1.4.2' })
  const result = run(proj, '--from', src)
  assert.equal(result.status, 1)
  assert.match(result.out, /v1\.1\.0/)
  assert.equal(read(proj, 'AGENTS.md'), 'agents 1.0.0\n')
  const none = run(project(release('1.0.0'), { lock: 'v0.9.0' }), '--from', src)
  assert.match(none.out, /no release/)
})

test('a failing hook restores the backup completely', () => {
  const proj = project(release('1.0.0', { '.claude/skills/old/SKILL.md': 'old\n' }))
  const before = {
    ignore: read(proj, '.gitignore'),
    record: read(proj, '.fullstack/harness.json'),
    settings: read(proj, '.claude/settings.json'),
  }
  const src = repo(
    release(
      '1.1.0',
      { '.claude/skills/fresh/deep/SKILL.md': 'new\n' },
      { hook: HOOK_BAD, ignore: ['.z'] },
    ),
  )
  const result = run(proj, '--from', src)
  assert.equal(result.status, 1)
  assert.match(result.out, /check\.mjs/)
  assert.equal(read(proj, 'AGENTS.md'), 'agents 1.0.0\n')
  assert.equal(read(proj, '.claude/skills/old/SKILL.md'), 'old\n')
  assert.equal(existsSync(join(proj, '.claude/skills/fresh')), false)
  assert.equal(read(proj, '.gitignore'), before.ignore)
  assert.equal(read(proj, '.fullstack/harness.json'), before.record)
  assert.equal(read(proj, '.claude/settings.json'), before.settings)
  assert.equal(git(proj, 'status', '--porcelain').trim(), '')
})

test('--version fetches into the cache from the project repository', () => {
  const src = repo(release('1.1.0'), { tag: 'v1.1.0' })
  const proj = project(release('1.0.0', {}, { repository: src }))
  const cache = mkdtempSync(join(tmpdir(), 'hu-cache-'))
  made.push(cache)
  const env = childEnv({ FULLSTACK_HARNESS_CACHE: cache })
  const result = spawnSync('node', [SCRIPT, '--root', proj, '--version', 'v1.1.0'], {
    encoding: 'utf8',
    env,
  })
  assert.equal(result.status, 0, result.stdout + result.stderr)
  assert.ok(existsSync(join(cache, 'v1.1.0', '.git')))
  // A clone may check out CRLF on Windows.
  assert.equal(read(proj, 'AGENTS.md').replace(/\r\n/g, '\n'), 'agents 1.1.0\n')
})

test('prints upstream project-file changes as advice and never applies them', () => {
  const src = repo(release('1.0.0'))
  const oldCommit = git(src, 'rev-parse', 'HEAD').trim()
  put(src, { '.doc/glossary.md': 'glossary NEW\n', 'README.md': 'readme NEW\n' })
  git(src, 'commit', '-qam', 'doc change')
  const proj = project(release('1.0.0'), { commit: oldCommit })
  const result = run(proj, '--from', src)
  assert.equal(result.status, 0, result.out)
  assert.match(result.out, /glossary NEW/)
  assert.doesNotMatch(result.out, /readme NEW/)
  assert.equal(read(proj, '.doc/glossary.md'), 'glossary 1.0.0\n')
})

test('lists the seeds when the old commit is unknown', () => {
  const proj = project(release('1.0.0'), { commit: 'a'.repeat(40) })
  const result = run(proj, '--from', repo(release('1.1.0')))
  assert.equal(result.status, 0, result.out)
  assert.match(result.out, /\.doc\/glossary\.md/)
  assert.match(result.out, /cannot be shown/)
})

test('--help prints the usage and a missing source is a usage error', () => {
  const opts = { encoding: 'utf8', env: childEnv() }
  assert.equal(spawnSync('node', [SCRIPT, '--help'], opts).status, 0)
  assert.equal(spawnSync('node', [SCRIPT], opts).status, 2)
})

test('a failure after the hook check restores everything and prints no advice', () => {
  const proj = project(release('1.0.0'))
  const before = read(proj, '.fullstack/harness.json')
  // The hook passes but removes a shipped file, so building the record fails afterwards.
  const hook =
    "import { rmSync } from 'node:fs'\nrmSync(`${process.env.CLAUDE_PROJECT_DIR}/AGENTS.md`)\n"
  const result = run(proj, '--from', repo(release('1.1.0', {}, { hook })))
  assert.equal(result.status, 1)
  assert.doesNotMatch(result.out, /Project files the release seeds/)
  assert.equal(read(proj, 'AGENTS.md'), 'agents 1.0.0\n')
  assert.equal(read(proj, '.claude/skills/core/SKILL.md'), 'core 1.0.0\n')
  assert.equal(read(proj, '.fullstack/harness.json'), before)
  assert.equal(git(proj, 'status', '--porcelain').trim(), '')
})

test('the real shipped hooks pass the check, so a real update is not rolled back', () => {
  const real = join(dirname(SCRIPT), '..', '.claude')
  const dir = mkdtempSync(join(tmpdir(), 'hu-real-'))
  made.push(dir)
  cpSync(join(real, 'hooks'), join(dir, '.claude', 'hooks'), {
    recursive: true,
    filter: (path) => !/[\/]test([\/]|$)/.test(path),
  })
  writeFileSync(join(dir, 'README.md'), 'x\n')
  const real_settings = JSON.parse(readFileSync(join(real, 'settings.json'), 'utf8'))
  assert.equal(failingHook(real_settings, dir), null)
})

test('the hook check sends a Read, a Bash and an Edit payload to every hook', () => {
  const dir = mkdtempSync(join(tmpdir(), 'hu-payload-'))
  made.push(dir)
  mkdirSync(join(dir, '.claude', 'hooks'), { recursive: true })
  const log = join(dir, 'seen.txt')
  const hook = `import { appendFileSync, readFileSync } from 'node:fs'
const input = JSON.parse(readFileSync(0, 'utf8'))
appendFileSync(${JSON.stringify(log)}, input.tool_name + '\\n')
process.exit(input.tool_name === 'Edit' ? 3 : 0)
`
  writeFileSync(join(dir, '.claude', 'hooks', 'check.mjs'), hook)
  const bad = failingHook(settings(['Bash(ls*)']), dir)
  assert.match(bad.why, /exit 3/)
  assert.deepEqual(readFileSync(log, 'utf8').trim().split('\n'), ['Read', 'Bash', 'Edit'])
})

test('an unknown format in the release manifest is a one-line refusal naming the file', () => {
  const proj = project(release('1.0.0'))
  const future = { ...manifest('1.1.0'), format: 2 }
  const result = run(proj, '--from', repo(release('1.1.0', { '.claude/harness.json': future })))
  assert.equal(result.status, 1)
  assert.match(result.out, /\.claude\/harness\.json.*format 2/)
  assert.doesNotMatch(result.out, /\bat .*\.mjs/)
  assert.equal(read(proj, 'AGENTS.md'), 'agents 1.0.0\n')
})

test('an unknown format in the project record is a one-line refusal naming the file', () => {
  const proj = project(release('1.0.0'))
  const record = JSON.parse(read(proj, '.fullstack/harness.json'))
  record.format = 2
  put(proj, { '.fullstack/harness.json': record })
  git(proj, 'commit', '-qam', 'future record')
  const result = run(proj, '--from', repo(release('1.1.0')))
  assert.equal(result.status, 1)
  assert.match(result.out, /\.fullstack\/harness\.json.*format 2/)
  assert.doesNotMatch(result.out, /\bat .*\.mjs/)
  assert.equal(read(proj, 'AGENTS.md'), 'agents 1.0.0\n')
})

test('a malformed references list in the release is a refusal', () => {
  const proj = project(release('1.0.0'))
  const bad = { ...manifest('1.1.0'), references: [{ file: 'AGENTS.md' }] }
  const result = run(proj, '--from', repo(release('1.1.0', { '.claude/harness.json': bad })))
  assert.equal(result.status, 1)
  assert.match(result.out, /references/)
  assert.doesNotMatch(result.out, /\bat .*\.mjs/)
})

test('a file the release reclassifies as project stays in place and leaves the record', () => {
  const proj = project(release('1.0.0', { '.claude/skills/moved/SKILL.md': 'mine now\n' }))
  const next = manifest('1.1.0')
  next.groups.project.push('.claude/skills/moved/**')
  next.groups.harness.push('!.claude/skills/moved/**')
  const files = { '.claude/skills/moved/SKILL.md': 'seed\n', '.claude/harness.json': next }
  const result = run(proj, '--from', repo(release('1.1.0', files)))
  assert.equal(result.status, 0, result.out)
  assert.equal(read(proj, '.claude/skills/moved/SKILL.md'), 'mine now\n')
  assert.equal('.claude/skills/moved/SKILL.md' in readRecord(proj).files, false)
  assert.doesNotMatch(result.out, /removed:/)
})

test('the summary names the release commit', () => {
  const src = repo(release('1.1.0'))
  const result = run(project(release('1.0.0')), '--from', src)
  assert.match(result.out, new RegExp(git(src, 'rev-parse', '--short=7', 'HEAD').trim()))
})

test('a BOM at the start of a JSON file does not break the update', () => {
  const src = repo(release('1.1.0'))
  const file = join(src, '.claude', 'settings.json')
  writeFileSync(file, `\uFEFF${readFileSync(file, 'utf8')}`)
  git(src, 'commit', '-qam', 'bom')
  const result = run(project(release('1.0.0')), '--from', src)
  assert.equal(result.status, 0, result.out)
})

test('a harness-dev end marker is not the end of the harness block', () => {
  const proj = project(release('1.0.0'))
  put(proj, { '.gitignore': '# >>> harness: old\nold\n# <<< harness-dev\nmine/\n' })
  git(proj, 'commit', '-qam', 'odd ignore')
  assert.equal(run(proj, '--from', repo(release('1.1.0'))).status, 0)
  const text = read(proj, '.gitignore')
  assert.match(text, /^# >>> harness:.*\n\.a\n# <<< harness\n/)
  assert.match(text, /mine\//)
})

test('a project without a recorded commit gets advice from the tag of its version', () => {
  const src = repo(release('1.0.0'), { tag: 'v1.0.0' })
  put(src, { '.doc/glossary.md': 'glossary NEW\n' })
  git(src, 'commit', '-qam', 'doc change')
  const result = run(project(release('1.0.0'), { commit: null }), '--from', src)
  assert.equal(result.status, 0, result.out)
  assert.match(result.out, /glossary NEW/)
})

test('a project edit to a non-permission settings key is a local edit', () => {
  const proj = project(release('1.0.0'))
  const edited = JSON.parse(read(proj, '.claude/settings.json'))
  edited.model = 'mine'
  put(proj, { '.claude/settings.json': edited })
  git(proj, 'commit', '-qam', 'model')
  const src = repo(release('1.1.0'))
  const refused = run(proj, '--from', src)
  assert.equal(refused.status, 1)
  assert.match(refused.out, /settings\.json \(modified\)/)
  assert.equal(run(proj, '--from', src, '--overwrite').status, 0)
  assert.equal('model' in JSON.parse(read(proj, '.claude/settings.json')), false)
})

test('a record without settings is invalid', () => {
  const proj = project(release('1.0.0'))
  const record = JSON.parse(read(proj, '.fullstack/harness.json'))
  record.settings = null
  put(proj, { '.fullstack/harness.json': record })
  git(proj, 'add', '-A')
  git(proj, 'commit', '-qm', 'broken record')
  const result = run(proj, '--from', repo(release('1.1.0')))
  assert.equal(result.status, 1)
  assert.match(result.out, /\.fullstack\/harness\.json/)
})

test('a malformed minCatalog and a non-repository root are one-line refusals', () => {
  const proj = project(release('1.0.0'))
  const bad = run(proj, '--from', repo(release('1.1.0', {}, { minCatalog: 'soon' })))
  assert.equal(bad.status, 1)
  assert.match(bad.out, /minCatalog "soon"/)
  assert.doesNotMatch(bad.out, /\bat .*\.mjs/)
  const plain = mkdtempSync(join(tmpdir(), 'hu-plain-'))
  made.push(plain)
  const none = run(plain, '--from', proj)
  assert.equal(none.status, 1)
  assert.match(none.out, /not a git repository/)
})
