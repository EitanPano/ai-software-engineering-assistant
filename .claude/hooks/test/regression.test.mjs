// Behaviour the hooks had before the Python-runner work: it must not change.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { fileVerdict, shellVerdict } from './harness.mjs'

const label = options => (options?.role ? ` [${options.role}]` : '')

const blocks = (command, options) =>
  test(`blocks: ${command}${label(options)}`, () => {
    assert.equal(shellVerdict(command, options).blocked, true, 'expected a block')
  })

const passes = (command, options) =>
  test(`passes: ${command}${label(options)}`, () => {
    const verdict = shellVerdict(command, options)
    assert.equal(verdict.blocked, false, `unexpected block by ${verdict.hook}: ${verdict.stderr}`)
  })

// Recursive deletion, every spelling findRule names.
for (const command of [
  'rm -rf x',
  'rm -r x',
  'rm -fr x',
  'rm -R -f x',
  'rm --recursive x',
  'rm -Rf x',
  'sudo rm -rf x',
  'sh -c "rm -r x"',
  'bash -lc "rm -rf x"',
  'find . -delete',
  'find . -exec rm -r {} +',
  'rmdir /s x',
  'del /s x',
  'Remove-Item -Recurse x',
  'Remove-Item x -Recurse -Force',
  'ri -r x',
  'rimraf x',
  'bunx rimraf x',
  'bun x rimraf x',
  'npx rimraf x',
  'npm exec rimraf x',
  'bun run rm -r x',
  'cd x && rm -rf y'
]) {
  blocks(command)
}

// Git history and working-tree destruction.
for (const command of [
  'git push --force',
  'git push -f origin main',
  'git push --force-with-lease',
  'git push origin +main',
  'git reset --hard',
  'git reset --hard HEAD~1',
  'git clean -fd',
  'git branch -D topic',
  'git stash drop',
  'git checkout .',
  'git restore .',
  'git filter-branch --all'
]) {
  blocks(command)
}

// Other destructive tooling.
for (const command of [
  'drizzle-kit drop',
  'prisma migrate reset',
  'supabase db reset',
  'docker system prune',
  'docker volume rm x',
  'docker compose down -v',
  'docker-compose down --volumes',
  'psql -c "DROP TABLE post"',
  'psql -c "DELETE FROM post"',
  'redis-cli FLUSHALL',
  'mongosh --eval "db.dropDatabase()"'
]) {
  blocks(command)
}

// Environment dumps.
for (const command of [
  'printenv',
  'env',
  'node -e "console.log(process.env)"',
  'bun -e "console.log(Bun.env)"',
  'Get-ChildItem Env:',
  'gci env:',
  'ls Env:\\',
  'set',
  'export -p',
  'declare -x',
  '[System.Environment]::GetEnvironmentVariables()'
]) {
  blocks(command)
}

// Secret files.
for (const command of [
  'cat .env',
  'cat backend/.env',
  'cat backend/.env.local',
  'cat .env*',
  'type backend\\.env.local',
  'Get-Content .env.production',
  'cat id_rsa',
  'cat server.pem',
  'cat ~/.ssh/config',
  'cat ~/.npmrc',
  'cat credentials.json',
  'echo x > .env',
  'cat < .env',
  'bash -c "cat .env"'
]) {
  blocks(command)
}

// Commands that look dangerous in text but are not.
for (const command of [
  'echo "rm -r x"',
  'echo "git push --force"',
  'git commit -m "docs: explain rm -rf"',
  'grep truncate src/',
  'grep -rn "process.env" src/',
  'node -e "console.log(process.env.HOME)"',
  'node -e "console.log(process.env[\'HOME\'])"',
  'cat backend/.env.example',
  'cat .env.sample',
  'cat .env.template',
  'ls',
  'git status',
  'git log --oneline -5',
  'git push origin feat/x',
  'rm file.txt',
  'bun run check',
  'bun run dev',
  'bun x prettier --check .',
  'npm run test',
  'docker compose up -d --wait db',
  'docker compose down',
  'psql -c "SELECT 1"',
  'psql -c "DELETE FROM post WHERE id = 1"'
]) {
  passes(command)
}

// Role agents: shell write channels are blocked.
for (const role of ['backend', 'frontend', 'qa']) {
  for (const command of [
    'sed -i s/a/b/ f',
    'sed --in-place s/a/b/ f',
    'echo x > f',
    'echo x >> f',
    'echo x | tee f',
    'Set-Content f x',
    'Add-Content f x',
    'Out-File f',
    'cp a b',
    'mv a b',
    'rm f',
    'touch f',
    'node -e "1"',
    'python -c "print(1)"',
    'python3 -c "print(1)"',
    'git add .',
    'git commit -m x',
    'git checkout main',
    'git -c core.pager=cat log',
    'git diff --output=f',
    'git branch topic'
  ]) {
    blocks(command, { role })
  }
}
blocks('Set-Content f x', { role: 'backend', tool: 'PowerShell' })

// Role agents: false positives the harness eval logged (plan 006) stay fixed.
for (const role of ['backend', 'qa']) {
  for (const command of [
    'bun run check 2>&1; echo done',
    'bun run check 2>&1',
    'bun run check > /dev/null',
    'bun run check >/dev/null;',
    'bun run check 2>&1|tail',
    'bun run check 2> /dev/null',
    'git -C backend status',
    'git --no-pager log',
    'git -P diff',
    'git --git-dir=.git status',
    'git --work-tree . status',
    'git status',
    'git diff HEAD',
    'git log --oneline',
    'git branch --list',
    'git stash list',
    'bun run check',
    'bun run test',
    'ls -la',
    'cat backend/AGENTS.md'
  ]) {
    passes(command, { role })
  }
}
// D8: the orchestrator reads code at plan N's Base, read-only.
for (const command of ['git show c61dafb:AGENTS.md', 'git show HEAD:frontend/package.json']) {
  passes(command, { role: 'orchestrator' })
}
passes('Get-Content backend/AGENTS.md', { role: 'backend', tool: 'PowerShell' })

// Lane writes for Edit and Write payloads.
const lane = (tool, filePath, role, expectBlocked) =>
  test(`${tool} ${filePath} [${role}] ${expectBlocked ? 'blocked' : 'allowed'}`, () => {
    const verdict = fileVerdict(tool, filePath, role)
    assert.equal(verdict.blocked, expectBlocked, verdict.stderr)
  })

for (const tool of ['Write', 'Edit']) {
  lane(tool, 'backend/src/x.ts', 'backend', false)
  lane(tool, 'backend/tests/x.test.ts', 'backend', false)
  lane(tool, 'docker-compose.yml', 'backend', false)
  lane(tool, 'db/init.sql', 'backend', false)
  lane(tool, 'frontend/src/x.ts', 'backend', true)
  lane(tool, '.claude/hooks/lib/guardrail.mjs', 'backend', true)
  lane(tool, 'backend/../frontend/x.ts', 'backend', true)
  lane(tool, 'frontend/src/x.ts', 'frontend', false)
  lane(tool, 'backend/src/x.ts', 'frontend', true)
  lane(tool, 'backend/tests/x.test.ts', 'qa', false)
  lane(tool, 'backend/src/x.ts', 'qa', true)
  lane(tool, '.plan/001-x.md', 'orchestrator', true)
  lane(tool, '.plan/000-backlog.md', 'orchestrator', true)
  lane(tool, '.plan/017-2026-10-30-x.md', 'orchestrator', true)
  lane(tool, '.orchestrate/../plan.md', 'orchestrator', true)
  // The shared matcher folds case on win32 only.
  lane(tool, '.orchestrate/x/PLAN.md', 'orchestrator', process.platform !== 'win32')
  lane(tool, 'backend/src/x.ts', 'orchestrator', true)
  lane(tool, '.orchestrate/016-visual-loop/plan.md', 'orchestrator', false)
  lane(tool, '.orchestrate/016-visual-loop/ticket.md', 'orchestrator', false)
  lane(tool, 'frontend/src/x.ts', 'orchestrator', true)
  lane(tool, '.orchestrate/016-visual-loop/backend.md', 'orchestrator', true)
  lane(tool, '.orchestrate/016-visual-loop/review.md', 'orchestrator', true)
  lane(tool, '.orchestrate/016-visual-loop/plan.md', 'backend', true)
  lane(tool, '.orchestrate/012-lean-loop/review.md', 'reviewer', false)
  lane(tool, 'backend/src/x.ts', 'reviewer', true)
  lane(tool, 'backend/src/x.ts', 'general-purpose', false)
  lane(tool, 'backend/src/x.ts', 'explore', true)
  lane(tool, 'backend/src/x.ts', undefined, false)
  lane(tool, 'backend/.env', undefined, true)
  lane(tool, 'backend/.env', 'general-purpose', true)
  lane(tool, 'backend/.env.example', 'backend', false)
}
