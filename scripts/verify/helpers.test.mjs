import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { test } from 'node:test'
import { parsePlan } from '../verify.mjs'
import { diffChecks } from './checks.mjs'
import { carriedPackages, readSources } from './reuse.mjs'
import { parseRetired, retiredHits } from './retired.mjs'
import { gateFiles, securityFor, securityPaths } from './security.mjs'
import { parseSummary } from './summary.mjs'

test('bun test summary', () => {
  const out = ' 12 pass\n 1 skip\n 2 fail\nRan 15 tests across 3 files.'
  assert.deepEqual(parseSummary(out), { passed: 12, failed: 2, skipped: 1, flaky: 0 })
})

test('Vitest summary, with colour codes', () => {
  const out = ' Test Files  1 failed (1)\n\u001b[2m      Tests \u001b[22m 3 failed | 5 passed | 1 skipped (9)'
  assert.deepEqual(parseSummary(out), { passed: 5, failed: 3, skipped: 1, flaky: 0 })
})

test('Playwright summary with a flaky test', () => {
  const out = '  1 flaky\n    [chromium] › a.spec.ts:3\n  1 skipped\n  8 passed (12.3s)'
  assert.deepEqual(parseSummary(out), { passed: 8, failed: 0, skipped: 1, flaky: 1 })
})

test('pytest summary counts xfailed as skipped and errors as failed', () => {
  const out = '=== 1 failed, 5 passed, 2 skipped, 1 xfailed, 1 error in 0.42s ==='
  assert.deepEqual(parseSummary(out), { passed: 5, failed: 2, skipped: 3, flaky: 0 })
})

test('output with no summary counts nothing', () => {
  assert.deepEqual(parseSummary('compiled 3 files'), { passed: 0, failed: 0, skipped: 0, flaky: 0 })
})

const added = (file, text) => ({ file, line: 1, text })
const names = (list) => list.filter((entry) => !entry.ok).map((entry) => entry.name)

test('every forbidden spelling is found in a code file', () => {
  const spellings = [
    'it.only(',
    'describe.skip(',
    'it.todo(',
    'test.fixme(',
    'xit(',
    'xdescribe(',
    '@pytest.mark.skip',
    '@pytest.mark.skipif(x)',
    '@pytest.mark.xfail',
    'pytest.skip("x")',
  ]
  for (const text of spellings) {
    assert.deepEqual(names(diffChecks([added('a.test.ts', text)])), ['no-focused-or-skipped-test'])
  }
})

test('prose and other file types are not read, an ordinary line passes', () => {
  assert.deepEqual(names(diffChecks([added('.plan/001.md', 'no `.only(` allowed')])), [])
  assert.deepEqual(names(diffChecks([added('a.ts', 'const skipped = items.filter(x)')])), [])
})

test('.exclude( counts only in an e2e spec', () => {
  assert.deepEqual(names(diffChecks([added('frontend/e2e/a.spec.ts', 'axe.exclude(".x")')])), [
    'no-axe-exclude',
  ])
  assert.deepEqual(names(diffChecks([added('frontend/src/list.ts', 'set.exclude(1)')])), [])
})

test('the detail lists file, line and text, capped at ten', () => {
  const many = Array.from({ length: 12 }, (_, line) => ({ file: 'a.test.ts', line, text: 'it.only(' }))
  const [check] = diffChecks(many)
  assert.equal(check.ok, false)
  assert.match(check.detail, /a\.test\.ts:0 it\.only\(/)
  assert.match(check.detail, /and 2 more$/)
})

test('.each variants and fit/fdescribe are found', () => {
  for (const text of ['it.only.each([1])(', 'describe.skip.each([1])(', 'fit("x", f)', 'fdescribe("x", f)']) {
    assert.deepEqual(names(diffChecks([added('a.test.ts', text)])), ['no-focused-or-skipped-test'])
  }
})

test('.exclude( counts in any *.spec.* file as well as in an e2e folder', () => {
  assert.deepEqual(names(diffChecks([added('tests/a11y.spec.ts', 'axe.exclude(".x")')])), [
    'no-axe-exclude',
  ])
  assert.deepEqual(names(diffChecks([added('src/a11y.test.ts', 'axe.exclude(".x")')])), [])
})

test('fit( and fdescribe( are found only as bare calls', () => {
  for (const text of ['model.fit(x)', 'fitAddon.fit()', 'obj.fdescribe(1)', 'refit(1)', '$fit(1)']) {
    assert.deepEqual(names(diffChecks([added('a.test.ts', text)])), [], text)
  }
  for (const text of ['  fit("x", f)', 'fdescribe("x", f)']) {
    assert.deepEqual(names(diffChecks([added('a.test.ts', text)])), ['no-focused-or-skipped-test'])
  }
})

test('the skip spellings apply to test paths only', () => {
  assert.deepEqual(names(diffChecks([added('src/page.ts', 'cursor.skip(n)')])), [])
  assert.deepEqual(names(diffChecks([added('backend/src/q.py', 'q.todo(1)')])), [])
  const paths = [
    'tests/a.ts',
    'src/__tests__/a.ts',
    'frontend/e2e/a.ts',
    'a.test.ts',
    'a.spec.tsx',
    'backend/test_a.py',
    'backend/a_test.py',
    'backend/conftest.py',
  ]
  for (const file of paths) {
    assert.deepEqual(names(diffChecks([added(file, 'cursor.skip(n)')])), ['no-focused-or-skipped-test'], file)
  }
})

test('the conditional and value spellings are found on a test path', () => {
  const spellings = [
    'it.skipIf(win)("x", f)',
    'it.runIf(win)("x", f)',
    'it.todoIf(win)("x", f)',
    'it.failing("x", f)',
    'it.failingIf(win)("x", f)',
    'test.if(win)("x", f)',
    'const t = describe.skip',
    'xtest("x", f)',
  ]
  for (const text of spellings) {
    assert.deepEqual(names(diffChecks([added('a.test.ts', text)])), ['no-focused-or-skipped-test'], text)
  }
  assert.deepEqual(names(diffChecks([added('a.test.ts', 'it("skips nothing", f)')])), [])
})

test('the catalog store seam skipif is exempt, any other skipif is not', () => {
  const seam = 'store_backed = pytest.mark.skipif(not STORE_ENABLED, reason=STORE_SKIP_REASON)'
  assert.deepEqual(names(diffChecks([added('backend/tests/store.py', seam)])), [])
  const other = '@pytest.mark.skipif(True, reason="later")'
  assert.deepEqual(names(diffChecks([added('backend/tests/store.py', other)])), [
    'no-focused-or-skipped-test',
  ])
})

test('the last summary line of a runner wins, even when it reports zero', () => {
  const out = '3 failed attempts\n 12 pass\n 0 fail'
  assert.deepEqual(parseSummary(out), { passed: 12, failed: 0, skipped: 0, flaky: 0 })
})

test('parsePlan reads the first token after Base:', () => {
  const branch = 'Branch: `feat/x`\n'
  assert.equal(parsePlan(`${branch}Base: 6a85649 (dev = main)\n`).base, '6a85649')
  assert.equal(parsePlan(`${branch}Base: \`6a85649\` (dev)\n`).base, '6a85649')
  assert.equal(parsePlan(`${branch}Base: dev (defaced)\n`).base, undefined)
})

test('securityPaths matches the plan 014 globs with glob semantics', () => {
  const hit = [
    'backend/src/api/auth/routes.ts',
    'frontend/src/shared/auth/session.ts',
    'backend/src/middleware/gate.ts',
    'backend/src/services/security/hash.ts',
    'frontend/src/proxy.ts',
    'backend/src/services/session.ts',
    'backend/src/infra/jobs/session-cleanup.ts',
    'backend/src/app/infra/jobs/session_cleanup.py',
    'backend/src/api/session/routes.ts',
    'backend/src/config/cors.ts',
    'backend/src/app/config/cors.py',
    'frontend/src/shared/auth/token.ts',
    'backend/src/middleware/auth.ts',
    'backend/Dockerfile',
    'docker-compose.yml',
    'backend/src/config/env.ts',
    'backend/src/app/config/env.py',
    'frontend/src/env.ts',
    'frontend/src/shared/config/env.ts',
    'frontend/nginx/security-headers.conf',
    'frontend/.dockerignore',
    'frontend/next.config.ts',
  ]
  const miss = [
    'backend/src/api/booking/routes.ts',
    'backend/src/api/author/routes.ts',
    'backend/src/api/post/controller.ts',
    'frontend/src/feature/post/ui/Card.tsx',
    'backend/docs/docker-compose.yml',
    'backend/src/myproxy.ts',
    'backend/src/authority.ts',
    'backend/src/infra/database/migrations/0001_init.sql',
    'db/init/01-schema.sql',
    'backend/drizzle/0002_booking.sql',
  ]
  assert.deepEqual(securityPaths([...hit, ...miss]), hit)
})

test('a malformed result file is no source, for the reuse reader and the carry-forward', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'sources-'))
  try {
    writeFileSync(path.join(dir, 'verify.json'), '{"packages": null}')
    writeFileSync(path.join(dir, 'verify-partial.json'), '{"packages": ')
    assert.deepEqual(readSources(dir), [])
    assert.deepEqual(carriedPackages(dir, {}), {})
    writeFileSync(path.join(dir, 'verify.json'), '{"packages": []}')
    assert.deepEqual(readSources(dir), [])
    const good = { check: { ok: true } }
    const body = { packages: { backend: null, frontend: good, other: 'x' } }
    writeFileSync(path.join(dir, 'verify-partial.json'), JSON.stringify(body))
    assert.equal(readSources(dir).length, 1)
    const carried = carriedPackages(dir, {})
    assert.deepEqual(Object.keys(carried), ['frontend'])
    assert.equal(carried.frontend.check.carried, true)
    writeFileSync(path.join(dir, 'verify-partial.json'), '{"packages": null}')
    assert.deepEqual(carriedPackages(dir, {}), {})
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

const SWALLOW = 'await expect(x).toBeFocused().catch(() => undefined)'
const swallowed = (file, text) =>
  diffChecks([{ file, line: 1, text }]).find((c) => c.name === 'no-swallowed-assertion')

test('no-swallowed-assertion fails on a caught expect chain in a test file only', () => {
  const hit = swallowed('frontend/tests/e2e/nav.spec.ts', SWALLOW)
  assert.equal(hit.ok, false)
  assert.match(hit.detail, /nav\.spec\.ts:1/)
  assert.equal(swallowed('frontend/src/shared/lib/focus.ts', SWALLOW).ok, true)
  assert.equal(swallowed('frontend/tests/unit/a.test.ts', 'expect(a).toBe(1)').ok, true)
  assert.equal(swallowed('frontend/tests/unit/a.test.ts', 'load().catch(() => undefined)').ok, true)
})

test('no-swallowed-assertion fails on a Python except AssertionError in a test file', () => {
  const line = '    except AssertionError:'
  assert.equal(swallowed('backend/tests/test_a.py', line).ok, false)
  assert.equal(swallowed('backend/tests/test_a.py', '    except (ValueError, AssertionError):').ok, false)
  assert.equal(swallowed('backend/src/app/a.py', line).ok, true)
  assert.equal(swallowed('backend/tests/test_a.py', '    except ValueError:').ok, true)
})

const patch = (file, ...lines) =>
  [`diff --git a/${file} b/${file}`, `--- a/${file}`, `+++ b/${file}`, '@@ -1 +1 @@', ...lines, ''].join('\n')

test('the gate line trigger fires on an added or removed gate line, wherever the file is', () => {
  const added = patch('backend/src/api/user/routes.ts', '+  requireRole(UserRole.admin),')
  assert.deepEqual(gateFiles(added), ['backend/src/api/user/routes.ts'])
  const removed = patch('backend/src/app/api/user/routes.py', '-    dependencies=[Depends(require_role)],')
  assert.deepEqual(gateFiles(removed), ['backend/src/app/api/user/routes.py'])
  const ui = patch('frontend/src/feature/auth/ui/login-form.tsx', '+const a = roleAction(role)')
  assert.deepEqual(gateFiles(ui), ['frontend/src/feature/auth/ui/login-form.tsx'])
  const both = patch('a.ts', '+accountAction') + patch('b.mjs', '-require_caller(r)')
  assert.deepEqual(gateFiles(both), ['a.ts', 'b.mjs'])
})

test('the gate line trigger needs a whole identifier on a changed line of a code file', () => {
  assert.deepEqual(gateFiles(patch('a.ts', '+const requireRoleList = []')), [])
  assert.deepEqual(gateFiles(patch('a.ts', '+const myrequireAuth = 1')), [])
  assert.deepEqual(gateFiles(patch('README.md', '+uses requireRole')), [])
  assert.deepEqual(gateFiles(patch('db/migrations/0001.sql', '+-- requireRole')), [])
  assert.deepEqual(gateFiles(patch('backend/migrations/0002.ts', '+requireRole()')), [])
  // A context line is not a change: the diff header carries it, not a +/- line.
  assert.deepEqual(gateFiles('diff --git a/a.ts b/a.ts\n--- a/a.ts\n+++ b/a.ts\n@@ -1 +1 @@ requireRole\n+x\n'), [])
})

test('securityPaths adds the seed and auth-entity globs and drops auth/ui', () => {
  const hit = [
    'backend/src/infra/scripts/seed.ts',
    'backend/src/app/infra/scripts/seed.py',
    'backend/src/models/user/enum.ts',
    'backend/src/app/models/user/enums.py',
  ]
  const miss = [
    'frontend/src/feature/auth/ui/login-form.tsx',
    'backend/src/models/post/enum.ts',
    'backend/src/api/seeder/routes.ts/x/y.ts',
  ]
  assert.deepEqual(securityPaths([...hit, ...miss]), hit)
})

test('securityPaths joins the files the line trigger names', () => {
  const files = ['backend/src/api/user/routes.ts', 'frontend/src/feature/auth/ui/login-form.tsx', 'x.ts']
  assert.deepEqual(securityPaths(files), [])
  assert.deepEqual(securityPaths(files, ['backend/src/api/user/routes.ts']), [
    'backend/src/api/user/routes.ts',
  ])
  assert.deepEqual(securityPaths(files, ['gone.ts']), [])
})

test('parseRetired reads the first Retired: line, one term per backtick span', () => {
  assert.deepEqual(parseRetired('Base: abc\nRetired: `OldName`, `old_name`\n'), ['OldName', 'old_name'])
  assert.deepEqual(parseRetired('Retired: `a`\nRetired: `b`\n'), ['a'])
  assert.deepEqual(parseRetired('Retired: none\n'), [])
  assert.deepEqual(parseRetired('Retired: nothing in backticks\n'), [])
  assert.deepEqual(parseRetired('Branch: x/y\n'), [])
  assert.deepEqual(parseRetired('Retired: `a`, `a`, ``\n'), ['a'])
})

test('the gate line trigger knows the guards and the fail-closed re-checks', () => {
  for (const name of ['requireAccount', 'assertRole', '_assert_role']) {
    assert.deepEqual(gateFiles(patch('a.ts', `+  ${name}(caller)`)), ['a.ts'], name)
  }
  assert.deepEqual(gateFiles(patch('a.py', '-    _assert_role(caller, "admin")')), ['a.py'])
  assert.deepEqual(gateFiles(patch('a.ts', '+const myassertRole = 1')), [])
  assert.deepEqual(gateFiles(patch('a.ts', '+const requireAccountList = 1')), [])
})

test('a failed git diff sets the security trigger instead of dropping it', () => {
  const files = ['a.ts', 'b.ts']
  assert.deepEqual(securityFor(files, { ok: false, out: '' }), { triggered: true, paths: files })
  assert.deepEqual(securityFor(['x.ts'], { ok: true, out: '' }), { triggered: false, paths: [] })
  const hit = patch('a.ts', '+requireRole()')
  assert.deepEqual(securityFor(files, { ok: true, out: hit }), { triggered: true, paths: ['a.ts'] })
})

test('retired-terms matches a listed file path, and a failed git call throws', async () => {
  const { mkdtempSync, mkdirSync, writeFileSync, rmSync } = await import('node:fs')
  const { tmpdir } = await import('node:os')
  const { spawnSync } = await import('node:child_process')
  const root = mkdtempSync(path.join(tmpdir(), 'retired-'))
  try {
    spawnSync('git', ['init', '-q'], { cwd: root })
    mkdirSync(path.join(root, 'backend', 'api', 'note'), { recursive: true })
    writeFileSync(path.join(root, 'backend', 'api', 'note', 'x.ts'), 'export const a = 1\n')
    const hits = retiredHits(root, ['backend'], ['API/note/'])
    assert.equal(hits.length, 1)
    assert.equal(hits[0].file, 'backend/api/note/x.ts')
    assert.deepEqual(retiredHits(root, ['backend'], ['api/other/']), [])
    assert.throws(() => retiredHits(path.join(root, 'missing'), ['backend'], ['x']), /git/)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
