// Plan 011 D5: heredoc bodies are data for the redirect scan unless a shell or interpreter reads
// them, `git hash-object` without -w is a read, and psql meta-commands that write are refused.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { splitHeredocBodies } from '../lib/guardrail.mjs'
import { shellVerdict } from './harness.mjs'

const label = options => (options?.role ? ` [${options.role}]` : '')

const blocks = (command, options) =>
  test(`blocks: ${JSON.stringify(command)}${label(options)}`, () => {
    assert.equal(shellVerdict(command, options).blocked, true, 'expected a block')
  })

const passes = (command, options) =>
  test(`passes: ${JSON.stringify(command)}${label(options)}`, () => {
    const verdict = shellVerdict(command, options)
    assert.equal(verdict.blocked, false, `unexpected block by ${verdict.hook}: ${verdict.stderr}`)
  })

const ROLES = ['backend', 'frontend', 'qa', 'reviewer']

const READ_ONLY = [
  "docker compose exec -T database psql -U app -d app <<'SQL' 2>/dev/null\nselect count(*) from plant where watering_interval_days > 7 and id <> 'x';\nSQL",
  'psql <<EOF\nselect 1 > 0;\nEOF',
  "cat <<'EOF'\na > b\nEOF",
  'docker compose exec -T database psql -U app -d app <<-SQL\n\tselect 1 where 2 > 1;\n\tSQL',
  'git hash-object backend/src/x.py',
  'git hash-object --stdin',
  'git -C backend hash-object src/x.py'
]

for (const role of ROLES) {
  for (const command of READ_ONLY) passes(command, { role })
}
// The interactive session is not the boundaries hook's concern, and none of these commands is
// destructive or names a secret file.
for (const command of READ_ONLY) passes(command)

const ROLE_BLOCKED = [
  "bash <<'EOF'\necho x > backend/f\nEOF",
  'sh <<EOF\necho x > f\nEOF',
  "docker compose exec backend sh <<'EOF'\necho x > /app/f\nEOF",
  'eval "$(cat <<\'EOF\'\necho x > f\nEOF\n)"',
  "cat <<'EOF' > backend/f\nbody\nEOF",
  "python - <<'EOF'\nprint(1)\nEOF",
  "node - <<'EOF'\nconsole.log(1)\nEOF",
  'git hash-object -w f',
  "psql <<'SQL'\n\\! cp a backend/b\nSQL",
  "psql <<'SQL'\n\\o backend/out.txt\nselect 1;\nSQL",
  "psql <<'SQL'\nselect 1 \\g backend/out.txt\nSQL",
  "psql <<'SQL'\n\\copy t to 'backend/x.csv'\nSQL"
]

for (const command of ROLE_BLOCKED) blocks(command, { role: 'backend' })
// The interactive session may write through the shell.
for (const command of ROLE_BLOCKED) passes(command)

// A body line that is a write program still blocks, and so does an operator hidden in a quote.
blocks("cat <<'EOF'\nplain\nEOF\ncp a backend/b", { role: 'backend' })
blocks("cat <<'EOF'\ntee backend/f\nEOF", { role: 'backend' })
blocks('echo "<<X"\necho a > backend/f\nX', { role: 'backend' })
blocks("cat <<'EOF'\nx\nEOF\necho a > backend/f", { role: 'backend' })
blocks('git hash-object -tw f', { role: 'backend' })

// An unquoted delimiter makes bash expand the body, so it is code; `\!` runs a whole command line.
const EXPANDED_BLOCKED = [
  'cat <<EOF\n$(echo x > backend/f)\nEOF',
  'cat <<EOF\n`echo x > backend/f`\nEOF',
  'cat <<EOF\n${x:=$(echo x > backend/f)}\nEOF',
  'cat <<EOF\n$(echo x > frontend/f)\nEOF',
  'cat <<EOF\n$(echo x > AGENTS.md)\nEOF',
  "psql <<'SQL'\n\\! echo x > backend/f\nSQL",
  "docker compose exec -T database psql -U app <<'SQL'\n\\! echo x > backend/f\nSQL",
  "psql <<'SQL'\n\\! bash -c \"echo x > backend/f\"\nSQL",
  "psql <<'SQL'\n\\! sh -c 'echo x > backend/f'\nSQL"
]
for (const command of EXPANDED_BLOCKED) blocks(command, { role: 'backend' })
for (const command of EXPANDED_BLOCKED) passes(command)
// Quotes inside an expanded body do not hide a command substitution.
const QUOTED_SUBSTITUTION = [
  "psql <<EOF\nselect '$(echo x > backend/f)';\nEOF",
  'cat <<EOF\n"$(echo x > backend/f)"\nEOF',
  'cat <<EOF\necho "$(echo x > backend/f)"\nEOF'
]
for (const command of QUOTED_SUBSTITUTION) blocks(command, { role: 'backend' })
for (const command of QUOTED_SUBSTITUTION) passes(command)
passes("psql <<EOF\nselect 'a > b';\nEOF", { role: 'backend' })
passes('cat <<EOF\necho "$(date)" > /dev/null\nEOF', { role: 'backend' })
passes("cat <<'EOF'\nselect '$(echo x > backend/f)';\nEOF", { role: 'backend' })
// `cat` prints this body and bash writes nothing: a plain $VAR is not code.
passes('cat <<EOF\necho $HOME > backend/f\nEOF', { role: 'backend' })
// A quoted delimiter stops the expansion: the same body is only text.
passes("cat <<'EOF'\n$(echo x > backend/f)\nEOF", { role: 'backend' })
passes('cat <<\\EOF\n`echo x > backend/f`\nEOF', { role: 'backend' })

// The destructive hook still reads heredoc bodies.
blocks("bash <<'EOF'\nrm -rf x\nEOF")

test('splitHeredocBodies strips bodies and keeps operator lines', () => {
  const strip = command => splitHeredocBodies(command).rest
  assert.equal(strip("cat <<'EOF' > f\nbody > x\nEOF\necho done"), "cat <<'EOF' > f\necho done")
  assert.equal(strip('cat <<-X\n\tbody\n\tX\nnext'), 'cat <<-X\nnext')
  assert.equal(strip('cat <<A <<"B"\none\nA\ntwo\nB\nafter'), 'cat <<A <<"B"\nafter')
  assert.equal(strip('cat <<EOF\nno end\nstill body'), 'cat <<EOF')
  // A body with no terminator is never data: it stays in the scanned `code`.
  assert.deepEqual(splitHeredocBodies('cat <<EOF\nno end').code, ['no end'])
  assert.equal(strip('cat <<\\EOF\r\nbody\r\nEOF\r\nafter'), 'cat <<\\EOF\r\nafter')
  assert.equal(strip('cat <<< word\nline2'), 'cat <<< word\nline2')
  assert.equal(strip('echo "<<EOF"\nline2\nEOF'), 'echo "<<EOF"\nline2\nEOF')
  assert.equal(strip('echo hi'), 'echo hi')
})

// A1: the detector reads a delimiter the way bash does and fails closed. Each command below
// runs the final write in bash (or is not a heredoc at all), so it must block.
const DETECTOR_BLOCKED = [
  'echo hi # <<EOF\necho x > AGENTS.md',
  'echo hi # <<EOF\necho x > AGENTS.md\nEOF',
  'echo $((1<<2))\necho x > AGENTS.md',
  "echo $'a\\' <<EOF b'\necho x > AGENTS.md",
  'cat <<E"O"F\nbody\nEOF\necho x > AGENTS.md',
  "cat <<'E'OF\nbody\nEOF\necho x > AGENTS.md",
  'cat <<E\\OF\nbody\nEOF\necho x > AGENTS.md',
  'cat <<X+\nbody\nX+\necho x > AGENTS.md',
  "cat <<'EOF'\nselect 1;\nEOF\n# note: cat <<X\necho x > AGENTS.md\nX"
]
for (const command of DETECTOR_BLOCKED) blocks(command, { role: 'backend' })
blocks('Write-Output 1 # <<EOF\nWrite-Output x > AGENTS.md', {
  role: 'backend',
  tool: 'PowerShell'
})
// A body with no terminator is not stripped either.
blocks("cat <<'EOF'\necho x > AGENTS.md", { role: 'backend' })
passes("cat <<'EOF' # note\nselect 1 > 0;\nEOF", { role: 'backend' })

// A2: only cat and psql bodies are data. Any other program may run the body.
const ALLOWLIST_BLOCKED = [
  "$SHELL <<'EOF'\necho x > AGENTS.md\nEOF",
  "${x:-bash} <<'EOF'\necho x > AGENTS.md\nEOF",
  "ash <<'EOF'\necho x > AGENTS.md\nEOF",
  "tcsh <<'EOF'\necho x > AGENTS.md\nEOF",
  "docker compose exec -T backend ash <<'EOF'\necho x > /app/f\nEOF",
  "make -f - <<'EOF'\nall:\n\techo x > AGENTS.md\nEOF",
  "parallel <<'EOF'\necho x > AGENTS.md\nEOF",
  "at now <<'EOF'\necho x > AGENTS.md\nEOF",
  "crontab - <<'EOF'\necho x > AGENTS.md\nEOF",
  "psql <<'SQL'\n\\o |cat > AGENTS.md\nselect 1;\nSQL",
  "psql <<'SQL'\nselect 1 \\g |cat > AGENTS.md\nSQL",
  "psql <<'SQL'\n\\out backend/o.txt\nselect 1;\nSQL",
  "psql <<'SQL'\n\\write backend/o.txt\nSQL",
  "psql <<'SQL'\n\\s backend/o.txt\nSQL",
  "psql <<'SQL'\n\\lo_export 1 backend/o.txt\nSQL",
  "mysql <<'SQL'\nsystem echo x > AGENTS.md\nSQL",
  "sqlite3 db <<'EOF'\n.shell echo x > AGENTS.md\nEOF",
  "ssh localhost <<'EOF'\necho x > f\nEOF",
  "cat <<'EOF' | bash\necho x > AGENTS.md\nEOF",
  "kubectl exec -i pod -- sh <<'EOF'\necho x > f\nEOF"
]
for (const command of ALLOWLIST_BLOCKED) blocks(command, { role: 'backend' })

const ALLOWLIST_PASSES = [
  "docker exec -i db psql <<'SQL'\nselect 1 where 2 > 1;\nSQL",
  "kubectl exec -i pod -- psql <<'SQL'\nselect 1 > 0;\nSQL",
  "PGPASSWORD=x psql -U app <<'SQL'\nselect 1 > 0;\nSQL"
]
for (const role of ROLES) {
  for (const command of ALLOWLIST_PASSES) passes(command, { role })
}

// Round 2: bash joins a backslash-newline before it reads an operator, and a quote opened on an
// earlier line holds until it closes. Both change which text is a heredoc operator or a body.
const JOINED_BLOCKED = [
  "cat <<'EOF' \\\n> backend/f\nbody\nEOF",
  "cat <<'EOF' \\\n| bash\necho x > backend/f\nEOF",
  "psql <<'SQL' \\\n> backend/f\nselect 1;\nSQL",
  'echo "start\ncat <<EOF "\necho x > backend/f\nEOF'
]
// Round 2c: psql meta-commands are judged on heredoc body lines only, and a value flag of
// `exec` cannot shift the reader.
for (const role of ROLES) {
  passes("grep '\\s' backend/src/app.py", { role })
  passes("grep '\\w' backend/AGENTS.md", { role })
  passes("grep -n '\\o' backend/x.txt", { role })
  passes("docker compose exec --index 1 db psql <<'SQL'\nselect 1 where 2 > 1;\nSQL", { role })
}
blocks("docker compose exec --index 2 psql sh <<'EOF'\necho x > backend/f\nEOF", {
  role: 'backend'
})
blocks("docker exec --detach-keys x psql sh <<'EOF'\necho x > backend/f\nEOF", {
  role: 'backend'
})
// A body is opaque: its quotes are never read, but the lines after the terminator are code.
blocks("psql <<'SQL'\n-- don't\nSQL\necho x > backend/f", { role: 'backend' })
for (const command of JOINED_BLOCKED) blocks(command, { role: 'backend' })
for (const role of ROLES) {
  passes("psql <<'SQL'\n-- don't\nselect 1 where 2 > 1;\nSQL", { role })
  passes(
    "docker compose exec -T database psql -U app -d app <<'SQL' 2>/dev/null\n" +
      "select count(*) from plant where name = 'O''Brien' and id <> 'x' -- isn't\nSQL",
    { role }
  )
}
for (const role of ROLES) {
  passes("psql <<'SQL'\nselect 'a\nb > c';\nSQL", { role })
  passes('echo "a\nb"', { role })
}
