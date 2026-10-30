// Bypasses the first review found: quoted flag values, attached inline code, short flag
// clusters, unknown runner flags, and Python code that reaches the interpreter without -c.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { shellVerdict } from './harness.mjs'

const label = options => (options?.role ? ` [${options.role}]` : '')
const show = command => JSON.stringify(command)

const blocks = (command, options) =>
  test(`blocks: ${show(command)}${label(options)}`, () => {
    assert.equal(shellVerdict(command, options).blocked, true, 'expected a block')
  })

const passes = (command, options) =>
  test(`passes: ${show(command)}${label(options)}`, () => {
    const verdict = shellVerdict(command, options)
    assert.equal(verdict.blocked, false, `unexpected block by ${verdict.hook}: ${verdict.stderr}`)
  })

const HEREDOC_DUMP = "python - <<'EOF'\nimport os\nprint(os.environ)\nEOF"
const HEREDOC_SECRET = "python - <<'EOF'\nprint(open('.env').read())\nEOF"
const HEREDOC_OK = "python - <<'EOF'\nprint(1)\nEOF"

// Critical 1: a quoted --flag="value" is the same value.
for (const command of [
  'bun run --env-file=".env" dev',
  "bun run --env-file='.env' dev",
  'uv run --env-file=".env" poe dev',
  "uv run --env-file='.env' poe dev",
  'uv run --env-file ".env" poe dev',
  'bun run --env-file=".env.local" dev',
  'FOO=".env" echo x',
  "FOO='.env' echo x"
]) {
  blocks(command)
}
passes('uv run --env-file=".env.example" poe dev')
passes("bun run --env-file='.env.example' dev")

// Critical 2: the code attached to the flag is inline code.
for (const command of [
  "python -c'import os;print(os.environ)'",
  'python -c"import os;print(os.environ)"',
  "python3.14 -Ic'import os;print(os.environ)'",
  "uv run python -c'import os;print(os.environ)'",
  "python -c'print(open(\".env\").read())'",
  "node -e'console.log(process.env)'",
  'node -e"console.log(process.env)"',
  'node --eval="console.log(process.env)"',
  "node -p'process.env'",
  "node -e'require(\"fs\").readFileSync(\".env\")'"
]) {
  blocks(command)
}
for (const role of ['backend', 'qa']) {
  for (const command of [
    "python -c'open(\"f\",\"w\")'",
    'python -c"print(1)"',
    "py -c'print(1)'",
    "uv run python -c'print(1)'",
    "node -e'1'",
    'node -e"1"',
    'node --eval="1"',
    "perl -e'1'",
    "ruby -e'1'",
    "php -r'1;'"
  ]) {
    blocks(command, { role })
  }
}
passes("python -c'import os;print(os.environ[\"HOME\"])'")
passes("node -e'console.log(process.env.HOME)'")

// Important 1: short flag clusters and unknown runner flags.
for (const command of [
  'uv run -qp 3.14 rm -rf x',
  'uv run -q rm -rf x',
  'uv run -qq rm -rf x',
  'uv run -qqp 3.14 rm -rf x',
  'uv run -wq httpx rm -rf x',
  'uv tool run -qp 3.14 rimraf x',
  'uvx -qp 3.14 rimraf x',
  'uv run -p3.14 rm -rf x',
  // An unlisted value flag must not hide the program.
  'uv run --newflag value rm -rf x',
  'poetry run --unknown v rimraf x',
  'pdm run --unknown v git reset --hard',
  'hatch run --unknown v rm -rf x',
  'pipx run --spec foo rimraf x',
  'bun run --newflag v git push --force',
  'npm exec --prefix backend rimraf x'
]) {
  blocks(command)
}
for (const role of [undefined, 'backend']) {
  for (const command of [
    'uv run -q poe check',
    'uv run -qq pytest',
    'uv run -qp 3.14 pytest',
    'uv run --newflag value pytest',
    'uv run -qp 3.14 python -m pytest',
    'poetry run --unknown v pytest',
    'pipx run --spec black black .'
  ]) {
    passes(command, { role })
  }
}

// Important 2 and 3: code that reaches the interpreter without -c.
for (const command of [
  'python -m timeit "import os; print(os.environ)"',
  'uv run python -m timeit "import os; print(os.environ)"',
  'python -m cProfile -c "import os; print(os.environ)"',
  'echo "import os; print(os.environ)" | python',
  'echo "import os; print(os.environ)" | uv run python',
  'python script.py "import os; print(os.environ)"',
  HEREDOC_DUMP,
  `uv run ${HEREDOC_DUMP}`,
  HEREDOC_SECRET,
  'python - <<EOF\nimport os\nprint(dict(os.environ))\nEOF',
  'python <<EOF\nimport os\nprint(os.environ)\nEOF',
  'python <<< "import os; print(os.environ)"'
]) {
  blocks(command)
}
blocks('python -m timeit "print(1)"', { role: 'backend' })
for (const role of ['backend', 'qa']) {
  for (const command of [
    'python -',
    'python - <<EOF\nprint(1)\nEOF',
    HEREDOC_OK,
    'echo "print(1)" | python',
    'uv run python < x.py',
    'python -m timeit "print(1)"',
    'python -m cProfile -c "print(1)"',
    'python -m code',
    'python -m runpy os',
    'python -m pdb x.py',
    'python'
  ]) {
    blocks(command, { role })
  }
}
passes(HEREDOC_OK)
passes('echo "print(1)" | python')
passes('python --version')
passes('python3.14 -V')
passes('python --version', { role: 'backend' })
passes('python script.py', { role: 'backend' })
passes('python script.py < input.txt', { role: 'backend' })
passes('echo hi | python script.py', { role: 'backend' })
passes('python -m pytest -k environ')
passes('python -m pytest -k environ', { role: 'backend' })
passes('python manage.py runserver')

// Final review, C1 and I-pre: a backslash-escaped quote outside quotes is a literal character,
// so it must neither merge the arguments after it nor hide a later command.
for (const command of [
  'rm \\" -rf x \\"',
  "rm \\' -rf x \\'",
  'cat \\" .env \\"',
  "cat \\' .env \\'",
  'git push \\" --force \\"',
  'echo \\" ; rm -rf x ; echo \\"',
  "echo \\' ; rm -rf x ; echo \\'"
]) {
  blocks(command)
}
blocks('echo \\" ; tee frontend/x ; echo \\"', { role: 'backend' })
blocks('echo \\" > frontend/x ; echo \\"', { role: 'backend' })
blocks('echo `"; Remove-Item -Recurse x; echo `"')
passes('echo \\"hello\\"')
passes('echo it\\\'s fine')
passes('git commit -m "say \\"hi\\" ; ok"')
passes('cat backend\\notes.txt')

// Final review, M2: node, bun and deno reading their program from stdin run inline code.
const NODE_DUMP = 'console.log(process.env)'
for (const command of [
  `node - <<'EOF'\n${NODE_DUMP}\nEOF`,
  `echo "${NODE_DUMP}" | node`,
  `echo "${NODE_DUMP}" | node -`,
  `bun - <<'EOF'\n${NODE_DUMP}\nEOF`,
  `echo "${NODE_DUMP}" | bun`,
  `echo "${NODE_DUMP}" | deno run -`,
  "node - <<'EOF'\nconsole.log(require('fs').readFileSync('.env', 'utf8'))\nEOF"
]) {
  blocks(command)
}
for (const command of [
  "node - <<'EOF'\nrequire('fs').writeFileSync('frontend/x', '1')\nEOF",
  'echo "1" | node',
  'echo "1" | bun',
  'echo "1" | deno run -'
]) {
  blocks(command, { role: 'backend' })
}
passes("node - <<'EOF'\nconsole.log(1)\nEOF")
passes('echo "console.log(1)" | node')
passes('node script.js')
passes('node --version', { role: 'backend' })
passes('node --test', { role: 'backend' })
passes('node script.js < input.txt', { role: 'backend' })
passes('bun run check', { role: 'backend' })
passes('bun test', { role: 'backend' })
passes('bun --version', { role: 'backend' })
passes('deno test', { role: 'backend' })

// Final review, M4: nesting more wrappers than the analysis follows is refused, not ignored.
blocks('sudo sudo sudo sudo sudo sudo sudo sudo sudo rm -rf x')
blocks('nice nice nice nice nice nice nice nice nice tee frontend/x', { role: 'backend' })
passes('sudo sudo sudo ls')

// Addendum 2: bash drops a backslash before any ordinary character, so the unescaped form of
// each token is judged as well as the raw one (which keeps Windows paths working).
for (const command of [
  'rm \\-rf x',
  'cat .\\env',
  'cat \\.env',
  'cat ".env"\\',
  'cat .env\\',
  'rm -\\r x',
  'git reset --\\hard',
  'git push --for\\ce',
  'sudo r\\m -rf x',
  'uv run r\\m -rf x'
]) {
  blocks(command)
}
blocks('t\\ee frontend/x', { role: 'backend' })
blocks('\\cp a frontend/b', { role: 'backend' })
blocks('p\\ython -c "print(1)"', { role: 'backend' })
// In bash `\\` is one backslash, so the quote after it opens a string: this removes files
// named `\` and ` -rf x `, not a recursive delete.
passes('rm \\\\" -rf x "')
passes('type backend\\README.md')
passes('Get-ChildItem C:\\x\\')
passes('Get-ChildItem C:\\x\\ -Name')
passes('type backend\\README.md', { role: 'backend' })
passes('Get-ChildItem C:\\x\\ -Name', { role: 'backend' })
passes('bun run check 2>&1 | tail -5')
passes('bun run check 2>&1 | tail -5', { role: 'backend' })
passes('uv run poe check')
passes('uv run poe check', { role: 'backend' })
passes('git status', { role: 'backend' })
passes('ls backend\\src', { role: 'backend' })
