// Plan 012 D8: the lanes per task folder, the two read-only roles that may run inline
// interpreters, `git check-ignore`, and the false positives of the secret hook found in the
// studio-booking eval. Each block case pins what must keep failing next to the pass it relaxes.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { fileVerdict, shellVerdict } from './harness.mjs'

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

const lane = (tool, filePath, role, expectBlocked) =>
  test(`${tool} ${filePath} [${role}] ${expectBlocked ? 'blocked' : 'allowed'}`, () => {
    const verdict = fileVerdict(tool, filePath, role)
    assert.equal(verdict.blocked, expectBlocked, verdict.stderr)
  })

// D4: one folder per task, `*` is exactly one segment that is not empty, `.` or `..`.
const OWN_FILE = {
  backend: 'backend.md',
  frontend: 'frontend.md',
  qa: 'qa.md',
  orchestrator: 'ticket.md',
  reviewer: 'review.md'
}
for (const tool of ['Write', 'Edit']) {
  for (const [role, file] of Object.entries(OWN_FILE)) {
    lane(tool, `.orchestrate/012-lean-loop/${file}`, role, false)
    for (const [other, otherFile] of Object.entries(OWN_FILE)) {
      if (other !== role) lane(tool, `.orchestrate/012-lean-loop/${otherFile}`, role, true)
    }
    lane(tool, `.orchestrate/x/../${file}`, role, true)
    lane(tool, `.orchestrate/a/b/${file}`, role, true)
    lane(tool, `.orchestrate/${file}`, role, true)
    // Case-insensitive lane match is a Windows-only fold.
    lane(tool, `.ORCHESTRATE/Task/${file.toUpperCase()}`, role, process.platform !== 'win32')
  }
  lane(tool, '.orchestrate/012-lean-loop/review-security.md', 'reviewer', false)
  lane(tool, '.orchestrate/012-lean-loop/review-security.md', 'qa', true)
  lane(tool, '.orchestrate/012-lean-loop/verify.json', 'qa', true)
  lane(tool, '.orchestrate/012-lean-loop/review.md', 'qa', true)
  lane(tool, '.orchestrate/review/security.md', 'reviewer', true)
  lane(tool, '.orchestrate/ticket/x.md', 'orchestrator', true)
}

// D8 (a): orchestrator and reviewer run read-only inline interpreters; everything else the
// shell can write with stays refused for them, and the implementers keep no inline code.
for (const role of ['orchestrator', 'reviewer']) {
  passes("node -e \"console.log(require('fs').readFileSync('package.json','utf8'))\"", { role })
  passes('node -p "1+1"', { role })
  passes("node - <<'EOF'\nconsole.log(1)\nEOF", { role })
  blocks('echo x > f', { role })
  blocks('tee f', { role })
  blocks('sed -i s/a/b/ f', { role })
  blocks('git commit -m x', { role })
  blocks('git add f', { role })
  blocks('cp a b', { role })
  blocks('rm f', { role })
}
for (const role of ['backend', 'frontend', 'qa']) {
  blocks('node -e "1"', { role })
  blocks('node -p "1"', { role })
}
passes('git check-ignore -v .orchestrate/x/qa.md', { role: 'reviewer' })
passes('git check-ignore .orchestrate', { role: 'backend' })

// D8 (b): the pattern operand of a search program is not a path.
const GREP = String.raw`grep -rnE '\.\.\.process\.env|_options\.env' backend/src`
for (const role of [undefined, 'backend', 'reviewer']) {
  passes(GREP, { role })
  passes(String.raw`rg -n '\.env' backend/src`, { role })
  passes(String.raw`rg -e '\.env' backend/src`, { role })
  passes(String.raw`grep -ie '\.env' backend/src/x.ts`, { role })
  passes(String.raw`grep --regexp='\.env' backend/src/x.ts`, { role })
  passes(String.raw`egrep -n "_options\.env" backend/src`, { role })
  passes(String.raw`fgrep -n '.env' backend/src/x.ts`, { role })
  passes(String.raw`findstr /s /c:".env" backend\src\x.ts`, { role })
  passes(String.raw`Select-String -Pattern '\.env' backend/src/x.ts`, { role })
}
for (const command of [
  'grep x .env',
  'grep -rn x backend/.env',
  'grep .env .env',
  'grep -f .env backend/src/x.ts',
  'grep --file=.env backend/src/x.ts',
  'grep -e x .env',
  'rg x .env',
  'rg -e x -- .env',
  'findstr x .env',
  'Select-String -Pattern x -Path .env',
  'Select-String -Path .env x',
  'cat .env'
]) {
  blocks(command)
}

// D8 (c): an interpreter that reads a heredoc is judged on that heredoc only. R11: a `cat`
// heredoc body is command text, so the notes append next to it blocks; the node edit alone passes.
const NOTES = [
  "cat >> notes <<'EOF'",
  'The server reads `.env` once; never print `.env` or process.env.',
  'EOF',
  "node - <<'EOF'",
  "const fs = require('fs')",
  "fs.writeFileSync('x', 'y')",
  'EOF'
].join('\n')
blocks(NOTES)
passes(NOTES.slice(NOTES.indexOf("node - <<'EOF'")))
blocks(NOTES.replace("fs.writeFileSync('x', 'y')", "fs.readFileSync('.env')"))
blocks(NOTES.replace("fs.writeFileSync('x', 'y')", 'console.log(process.env)'))
blocks('echo `.env` | node -')
blocks('echo "require(\'fs\').readFileSync(\'.env\')" | node')
blocks('cat <<EOF\n$(cat .env)\nEOF')
blocks("bash <<'EOF'\nprintenv\nEOF")
blocks("cat <<'EOF' | node -\nrequire('fs').readFileSync('.env')\nEOF")
blocks("node - <<'EOF' .env\n1\nEOF")

// D8 (d): `set,` in the JS body of an interpreter heredoc is text, not the shell builtin.
const SET_BODY = "node - <<'EOF'\nconst words = `\nset\nenv\nexport\n`\nconsole.log(words)\nEOF"
passes(SET_BODY)
passes("node - <<'EOF'\nconst a = [set, env]\nconsole.log(a)\nEOF")
passes("psql <<'SQL'\nset search_path = a;\nSQL")
blocks("cat <<'EOF'\nset\nenv\nprintenv\nEOF")
blocks('printenv')
blocks('env')
blocks('set')
blocks("bash <<'EOF'\nprintenv\nEOF")
blocks('cat <<EOF\n$(printenv)\nEOF')
blocks("node - <<'EOF'\nconsole.log(process.env)\nEOF")

// R11: bash can run what a `cat` heredoc prints, so its body is judged as command text. Every
// shape that reaches a shell blocks for the default session and for a role, with a secret path
// and with an env dump in the body.
for (const inner of ['cat ' + '.env', 'printenv']) {
  const SHAPES = [
    `cat <<'EOF'\n${inner}\nEOF`,
    `cat <<'EOF' |\nsh\n${inner}\nEOF`,
    `cat <<'EOF' | sh\n${inner}\nEOF`,
    `(cat <<'EOF'\n${inner}\nEOF\n) | sh`,
    `{ cat <<'EOF'\n${inner}\nEOF\n} | bash`,
    `sh < <(cat <<'EOF'\n${inner}\nEOF\n)`,
    `source <(cat <<'EOF'\n${inner}\nEOF\n)`,
    `bash <(cat <<'EOF'\n${inner}\nEOF\n)`,
    `cat <<'EOF' > >(sh)\n${inner}\nEOF`,
    `cat <<'EOF' > x.sh\n${inner}\nEOF\nsh x.sh`
  ]
  for (const command of SHAPES) {
    blocks(command)
    blocks(command, { role: 'backend' })
  }
}
blocks("cat <<'EOF'\nsee the file named .env.local\nEOF")
blocks("psql <<'SQL'\n\\i .env\nSQL")
blocks("cat <<'EOF' | bash\ncat .env\nEOF")
blocks("cat <<'EOF'\nx\nEOF\ncat .env")

// A search program's value-taking options: the value is not the pattern when it is a file.
blocks('grep --exclude-from .env x y')
blocks('grep --exclude-from=.env x y')
blocks('rg --ignore-file .env x')
blocks('rg --newflag x .env')
blocks('grep --newflag x .env')
blocks('grep -f.env x')
blocks('grep -rf.env x')
blocks('findstr /g:.env x')
blocks('findstr /f:.env x y')
blocks('findstr /G:.env x')
passes('grep --include=*.ts -rn x backend/src')
passes('grep --include *.ts -rn x backend/src')
passes('grep -A 3 -B2 x backend/src/x.ts')
passes("grep --exclude-dir node_modules -rn '\\.env' backend/src")
passes("rg -g '*.ts' -t ts '\\.env' backend/src")
passes("rg --glob '*.ts' '\\.env' backend/src")
