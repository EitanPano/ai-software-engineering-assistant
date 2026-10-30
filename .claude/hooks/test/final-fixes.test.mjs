// Plan 012 final review: one interpreter heredoc must not widen the stdin excuse to the rest of
// the command (M1), a reviewer's heredoc body is code and not shell redirects (M2), and an
// fd-numbered redirect names a path like a bare one (R14).
import assert from 'node:assert/strict'
import { test } from 'node:test'

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

// M1: the second stdin reader is judged on the whole command text, whatever the first one read.
const FIRST = "node - <<'EOF'\nconsole.log(1)\nEOF\n"
const SECRET = `require('fs').readFileSync('.env')`
blocks(`${FIRST}node <(echo "${SECRET}")`)
blocks(`${FIRST}node < <(echo "${SECRET}")`)
blocks(`${FIRST}echo "${SECRET}" | node`)
blocks(`${FIRST}node <<< "${SECRET}"`)
blocks(`${FIRST}python - <<'EOF'\nopen('.env')\nEOF`)
blocks(`${FIRST}node - <<'EOF'\n${SECRET}\nEOF`)
blocks(`${FIRST}node <(echo "console.log(process.env)")`)
passes("node - <<'EOF'\nconsole.log(1)\nEOF")
passes(`${FIRST}git status`)
passes("node - <<'EOF'\nconst words = `\nset\nenv\n`\nEOF")

// M2: an interpreter heredoc body is code. `>` and `>=` in it are not redirects for the two
// roles that may run interpreters; the implementers still may not, and shell writes stay refused.
for (const role of ['reviewer', 'orchestrator']) {
  passes("node - <<'EOF'\nif (a > b) console.log(1)\nEOF", { role })
  passes("node - <<'EOF'\nconst ok = x >= 1\nconsole.log(ok)\nEOF", { role })
  passes("python3 - <<'EOF'\nprint(1 if a > b else 2)\nEOF", { role })
  blocks("node - <<'EOF'\nconsole.log(1)\nEOF\necho x > f", { role })
  blocks("node - <<'EOF'\nconsole.log(1)\nEOF\ntee f", { role })
  blocks("bash <<'EOF'\necho x > f\nEOF", { role })
  blocks("node - <<'EOF' > out.txt\nconsole.log(1)\nEOF", { role })
  blocks("node - <<'EOF' | tee f\nconsole.log(1)\nEOF", { role })
}
for (const role of ['backend', 'frontend', 'qa']) {
  blocks("node - <<'EOF'\nconst ok = x >= 1\nEOF", { role })
}

// R14: the target of an fd-numbered or glued redirect is a path; fd duplications are not.
for (const command of [
  'cat 0<.env',
  'cat 3<.env',
  'cat 0<>.env',
  'cat 0< .env',
  'cat <.env',
  'cat <>.env',
  "cat <<'EOF' 1>.env\nx\nEOF",
  'echo x 1>.env',
  'echo x 2>.env',
  'echo x 2>>.env',
  'echo x 2> .env',
  'echo x &>.env',
  'echo x &>>.env',
  'echo x >|.env',
  'echo x 1>|.env',
  'echo x >.env',
  'echo x >>.env',
  'cat 0<id_rsa',
  'cat 0<~/.ssh/config',
  'echo x 2>backend/.env.local',
  'cat 0<.env;echo ok',
  'echo x>.env',
  'echo x 2>&.env'
]) {
  blocks(command)
}
for (const command of [
  'echo hi 2>&1',
  'echo hi >&2',
  'echo hi 3>&1',
  'echo hi 2>&1 >/dev/null',
  'echo hi >/dev/null 2>&1',
  'echo hi 1>/dev/null',
  'echo hi &>/dev/null',
  'cat 0<package.json',
  'cat 0<.env.example',
  'echo x 2>err.log',
  'bun test 2>&1 | tail -5',
  'echo hi 5>&-'
]) {
  passes(command)
}
