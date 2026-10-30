import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, posix, resolve } from 'node:path'
import { after, describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'
import {
  buildRecord,
  danglingReferences,
  filesIn,
  groupsOf,
  hashFile,
  loadManifest,
  readRecord,
  trackedFiles,
  writeRecord,
} from './manifest.mjs'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const dirs = []
function tmp() {
  const dir = mkdtempSync(join(tmpdir(), 'manifest-'))
  dirs.push(dir)
  return dir
}
after(() => dirs.forEach((dir) => rmSync(dir, { recursive: true, force: true })))

function write(root, file, text) {
  mkdirSync(dirname(join(root, file)), { recursive: true })
  writeFileSync(join(root, file), text)
}

const manifest = {
  version: 'unreleased',
  groups: {
    harness: ['a/**', '!a/skip/**', 'AGENTS.md', '.claude/settings.json'],
    project: ['p/**', 'a/both.txt'],
    dev: ['README.md', '**/*.test.mjs'],
  },
  references: [],
}

function full(extra = {}) {
  return {
    format: 1,
    repository: 'https://example.test/r',
    rootCommit: 'abc',
    minCatalog: 'v1.0.0',
    ...manifest,
    ...extra,
  }
}

describe('groupsOf', () => {
  it('honours the ! exclusion', () => {
    assert.deepEqual(groupsOf(manifest, 'a/x.txt'), ['harness'])
    assert.deepEqual(groupsOf(manifest, 'a/skip/x.txt'), [])
  })
  it('reports every group a path falls in', () => {
    assert.deepEqual(groupsOf(manifest, 'a/both.txt'), ['harness', 'project'])
  })
  it('reports none for an unplaced path', () => {
    assert.deepEqual(groupsOf(manifest, 'zzz.txt'), [])
  })
  it('reads backslashes as slashes', () => {
    assert.deepEqual(groupsOf(manifest, 'a\\x.txt'), ['harness'])
  })
})

describe('filesIn', () => {
  it('keeps the files of one group', () => {
    const files = ['a/x.txt', 'p/y.txt', 'README.md', 'a/skip/z.txt']
    assert.deepEqual(filesIn(manifest, 'harness', files), ['a/x.txt'])
    assert.deepEqual(filesIn(manifest, 'dev', files), ['README.md'])
  })
})

describe('loadManifest', () => {
  it('rejects a missing field and an unknown group', () => {
    const root = tmp()
    const { version: _version, ...noVersion } = full()
    write(root, '.claude/harness.json', JSON.stringify(noVersion))
    assert.throws(() => loadManifest(root), /version/)
    const odd = full({ groups: { ...manifest.groups, odd: [] } })
    write(root, '.claude/harness.json', JSON.stringify(odd))
    assert.throws(() => loadManifest(root), /odd/)
  })
  it('rejects a missing or unknown format, naming the file', () => {
    const root = tmp()
    const { format: _format, ...none } = full()
    write(root, '.claude/harness.json', JSON.stringify(none))
    assert.throws(() => loadManifest(root), /harness\.json.*format/)
    write(root, '.claude/harness.json', JSON.stringify(full({ format: 2 })))
    assert.throws(() => loadManifest(root), /harness\.json.*format 2/)
  })
  it('rejects groups that are not an object and malformed references', () => {
    const root = tmp()
    write(root, '.claude/harness.json', JSON.stringify(full({ groups: [] })))
    assert.throws(() => loadManifest(root), /groups/)
    write(root, '.claude/harness.json', JSON.stringify(full({ references: {} })))
    assert.throws(() => loadManifest(root), /references/)
    write(root, '.claude/harness.json', JSON.stringify(full({ references: [{ file: 'a' }] })))
    assert.throws(() => loadManifest(root), /references/)
    write(root, '.claude/harness.json', JSON.stringify(full({ references: ['a'] })))
    assert.throws(() => loadManifest(root), /references/)
  })
  it('loads a valid file', () => {
    const root = tmp()
    write(root, '.claude/harness.json', JSON.stringify(full()))
    assert.equal(loadManifest(root).version, 'unreleased')
  })
})

describe('hashFile and records', () => {
  it('hashes the raw bytes', () => {
    const root = tmp()
    write(root, 'f.txt', 'abc')
    assert.equal(
      hashFile(join(root, 'f.txt')),
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    )
  })
  it('round-trips a record, with two-space indent and a trailing newline', () => {
    const root = tmp()
    write(root, 'AGENTS.md', 'rules')
    write(root, 'a/x.txt', 'x')
    write(root, 'p/y.txt', 'y')
    write(root, '.claude/settings.json', '{"permissions":{"allow":["Read"]}}')
    const record = buildRecord(root, manifest, {
      commit: null,
      files: ['.claude/settings.json', 'AGENTS.md', 'a/x.txt'],
    })
    assert.deepEqual(Object.keys(record.files).sort(), [
      '.claude/settings.json',
      'AGENTS.md',
      'a/x.txt',
    ])
    assert.deepEqual(record.settings, { permissions: { allow: ['Read'] } })
    assert.equal(record.commit, null)
    assert.equal(record.format, 1)
    writeRecord(root, record)
    assert.deepEqual(readRecord(root), record)
    const raw = readFileSync(join(root, '.fullstack', 'harness.json'), 'utf8')
    assert.ok(raw.endsWith('}\n') && raw.includes('\n  "version"'))
  })
  it('records only the listed files, not a project file under a harness glob', () => {
    const root = tmp()
    write(root, 'AGENTS.md', 'rules')
    write(root, 'a/mine/SKILL.md', 'project skill')
    write(root, '.claude/settings.json', '{}')
    const record = buildRecord(root, manifest, { files: ['AGENTS.md', '.claude/settings.json'] })
    assert.deepEqual(Object.keys(record.files).sort(), ['.claude/settings.json', 'AGENTS.md'])
  })
  it('fails on a listed file that is missing, not harness, or on no list', () => {
    const root = tmp()
    write(root, '.claude/settings.json', '{}')
    assert.throws(() => buildRecord(root, manifest, { files: ['a/gone.txt'] }), /missing/)
    assert.throws(() => buildRecord(root, manifest, { files: ['p/y.txt'] }), /not a harness/)
    assert.throws(() => buildRecord(root, manifest, {}), /list/)
  })
  it('returns null when there is no record', () => {
    assert.equal(readRecord(tmp()), null)
  })
})

describe('danglingReferences', () => {
  const files = ['AGENTS.md', 'a/x.txt', 'README.md', 'a/tool.test.mjs']
  it('flags a harness file that names a dev path at a path boundary', () => {
    const root = tmp()
    write(root, 'AGENTS.md', 'see `README.md` for recovery')
    write(root, 'a/x.txt', 'run a/tool.test.mjs.')
    assert.deepEqual(danglingReferences(root, manifest, files), [
      { file: 'AGENTS.md', name: 'README.md' },
      { file: 'a/x.txt', name: 'a/tool.test.mjs' },
    ])
  })
  it('does not count a name inside a longer path', () => {
    const root = tmp()
    write(root, 'AGENTS.md', 'see .orchestrate/README.md and MYREADME.md and README.md.bak')
    write(root, 'a/x.txt', '')
    assert.deepEqual(danglingReferences(root, manifest, files), [])
  })
  it('lets an allowlisted pair through', () => {
    const root = tmp()
    write(root, 'AGENTS.md', 'see README.md')
    write(root, 'a/x.txt', '')
    const allowed = { ...manifest, references: [{ file: 'AGENTS.md', names: ['README.md'] }] }
    assert.deepEqual(danglingReferences(root, allowed, files), [])
  })
})

describe('this repository', () => {
  const real = loadManifest(repoRoot)
  const files = trackedFiles(repoRoot)
  it('places every tracked file in exactly one group', () => {
    const bad = files
      .map((file) => [file, groupsOf(real, file)])
      .filter(([, groups]) => groups.length !== 1)
    assert.deepEqual(bad, [])
  })
  it('has no harness file naming a dev path outside the allowlist', () => {
    assert.deepEqual(danglingReferences(repoRoot, real, files), [])
  })
  it('has no harness .mjs file importing a dev file', () => {
    const bad = []
    for (const file of filesIn(real, 'harness', files).filter((f) => f.endsWith('.mjs'))) {
      const text = readFileSync(join(repoRoot, file), 'utf8')
      for (const [, spec] of text.matchAll(/(?:from|import)\s*\(?\s*['"](\.{1,2}\/[^'"]+)['"]/g)) {
        const target = posix.normalize(posix.join(posix.dirname(file), spec))
        if (files.includes(target) && !groupsOf(real, target).includes('harness')) {
          bad.push(`${file} imports ${target}`)
        }
      }
    }
    assert.deepEqual(bad, [])
  })
  it('lists tracked files with / separators', () => {
    const out = execFileSync('git', ['ls-files'], { cwd: repoRoot, encoding: 'utf8' })
    assert.equal(files.length, out.split('\n').filter(Boolean).length)
    assert.ok(files.every((file) => !file.includes('\\')))
  })
})
