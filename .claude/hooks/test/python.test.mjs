// Python package runners, value-taking runner flags, Python inline code, and the secret
// files and environment dumps that go with them (plan 009, M4-20).
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { shellVerdict } from './harness.mjs'

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

// Runners are seen through, for everyone.
for (const command of [
  'uv run rm -rf x',
  'uv run --directory backend rm -r x',
  'uv run --directory=backend rm -r x',
  'uv --directory backend run rm -r x',
  'uv run --with httpx --python 3.14 rm -rf x',
  'uv run -p 3.14 -w httpx rm -rf x',
  'uv run --group dev --extra x rm -rf x',
  'uv tool run rimraf x',
  'uv tool run --from foo rimraf x',
  'uvx rimraf x',
  'uvx --from foo rimraf x',
  'uvx --from=foo rimraf x',
  'poetry run git reset --hard',
  'poetry --directory backend run rm -rf x',
  'poetry -C backend run rm -rf x',
  'pipx run rimraf x',
  'pdm run rm -rf x',
  'pdm run -p backend rm -rf x',
  'pdm run --env-file f rm -rf x',
  'hatch run rm -rf x',
  'hatch run test:rm -rf x',
  'hatch -e test run rm -rf x',
  'bun run --cwd backend rm -r x',
  'bun run --cwd=backend rm -r x',
  'bun --cwd backend run rm -r x',
  'bun x -p pkg rimraf x',
  'bunx -p pkg rimraf x',
  'npm exec --package foo rimraf x',
  'npm exec -w backend rimraf x',
  'npm run --workspace backend rimraf x',
  'python -m rimraf x',
  'uv run python -m rimraf x',
  'uv run git push --force',
  'uv run sh -c "rm -r x"',
  'uv run --env-file=.env.example rm -rf x'
]) {
  blocks(command)
}

// Python inline code and environment dumps, for everyone.
for (const command of [
  'uv run python -c "import os; print(os.environ)"',
  'python -c "import os;print(os.environ)"',
  'py -c "import os; print(dict(os.environ))"',
  'python3.14 -c "import os; print(os.environ.items())"',
  'python3 -c "import os; print(os.environ.copy())"',
  'python -c "import os; print(list(os.environ.keys()))"',
  'python -c "import os; print(os.environ.values())"',
  'python -c "import os; print({**os.environ})"',
  'python -c "import os, json; print(json.dumps(dict(os.environ)))"',
  'python -c "import os; print(os.environb)"',
  'python -c "from os import environ; print(environ)"',
  'python -c "from os import environ; print(dict(environ))"',
  'python -Ic "import os; print(os.environ)"',
  'python -X dev -c "import os; print(os.environ)"',
  'uv run --with httpx python -c "import os; print(os.environ)"',
  'pypy3 -c "import os; print(os.environ)"',
  "python -c 'import os; print(os.environ)'"
]) {
  blocks(command)
}

// Secret files behind wrappers, flags and inline code, for everyone.
for (const command of [
  'bun run --env-file .env dev',
  'bun run --env-file=.env dev',
  'bun run --env-file=backend/.env.local dev',
  'uv run --env-file .env poe dev',
  'uv run --env-file=.env poe dev',
  'uvx --env-file .env tool',
  'pdm run --env-file .env x',
  'python -c "print(open(\'.env\').read())"',
  'python -c "print(open(\'backend/.env.local\').read())"',
  'python -c "from pathlib import Path; print(Path(\'.env\').read_text())"',
  'uv run python -c "print(open(\'.env\').read())"',
  'node -e "console.log(require(\'fs\').readFileSync(\'backend/.env.local\', \'utf8\'))"',
  'node -e "require(\'fs\').readFileSync(\'.env\')"',
  'python -c "print(open(\'server.pem\').read())"',
  'cat ~/.pypirc',
  'cat pip.conf',
  'cat pip.ini',
  'type %APPDATA%\\pip\\pip.ini',
  'Get-Content ~/.pypirc'
]) {
  blocks(command)
}

// Role agents: inline code through every runtime and runner, and shell write channels
// behind a runner.
for (const role of ['backend', 'frontend', 'qa']) {
  for (const command of [
    'uv run python -c "print(1)"',
    'py -c "print(1)"',
    'python3.14 -c "print(1)"',
    'python -c "print(1)"',
    'python -Ic "print(1)"',
    'pypy3 -c "print(1)"',
    'uv run --with httpx python -c "print(1)"',
    'uv run --directory backend python -c "print(1)"',
    'uvx --from foo python -c "print(1)"',
    'poetry run python -c "print(1)"',
    'uv run tee f',
    'uv run sed -i s/a/b/ f',
    'uv run sh -c "cp a b"',
    'uv run --directory backend rm f',
    'uv run node -e "1"',
    'bun run --cwd backend rm f'
  ]) {
    blocks(command, { role })
  }
}

// Ordinary Python work passes for everyone and for role agents.
for (const role of [undefined, 'backend']) {
  for (const command of [
    'uv run poe check',
    'uv run poe test-db',
    'uv sync',
    'uv sync --locked',
    'uv lock',
    'uv lock --check',
    'uv add httpx',
    'uv run pytest',
    'uv run ruff check .',
    'uv run mypy src',
    'uv run --directory backend poe check',
    'uv run --with httpx pytest',
    'uv --version',
    'uv tool run ruff check .',
    'uvx ruff check .',
    'python -m pytest',
    'python3.14 -m pytest -q',
    'python -X dev -m pytest',
    'py -3.14 -m pytest',
    'uv run python -m pytest -p tests.db.plugin',
    'uv run python -m app.openapi --write',
    'uv run --env-file=.env.example poe dev',
    'uv run --env-file .env.example poe dev',
    'poetry run pytest',
    'poetry install',
    'pdm run pytest',
    'hatch run test:pytest',
    'pipx run black .',
    'python script.py',
    'python script.py -c config.ini',
    'cat backend/.env.example',
    'cat .env.sample',
    'cat .env.template',
    'bun run --cwd backend check',
    'bun run --env-file=.env.example dev',
    'npm exec --package foo prettier --check .'
  ]) {
    passes(command, { role })
  }
}

// Reading one key from the environment is fine for the interactive session.
passes('python -c "import os; print(os.environ[\'HOME\'])"')
passes('python -c "import os; print(os.environ.get(\'HOME\'))"')
passes('python -c "import os; print(os.getenv(\'HOME\'))"')
passes('uv run python -c "import os; print(os.environ.get(\'HOME\', \'\'))"')
passes('python -c "print(open(\'.env.example\').read())"')
passes('python -c "print(open(\'README.md\').read())"')
passes('node -e "console.log(require(\'fs\').readFileSync(\'.env.example\', \'utf8\'))"')

// PowerShell payloads go through the same guardrails.
const powershell = (command, expectBlocked, options = {}) =>
  test(`${expectBlocked ? 'blocks' : 'passes'} (PowerShell): ${command}${label(options)}`, () => {
    const verdict = shellVerdict(command, { ...options, tool: 'PowerShell' })
    assert.equal(verdict.blocked, expectBlocked, verdict.stderr)
  })

powershell('uv run rm -rf x', true)
powershell('uv run --directory backend Remove-Item -Recurse x', true)
powershell('uv run python -c "import os; print(dict(os.environ))"', true)
powershell('Get-Content ~/.pypirc', true)
powershell('uv run --env-file .env poe dev', true)
powershell('uv run python -c "print(1)"', true, { role: 'backend' })
powershell('uv run poe check', false)
powershell('uv run poe check', false, { role: 'backend' })
powershell('uv sync --locked', false)

// Final review, C2: uv's own Python channels, `uv run -m <module>` and `uv run -` (a script
// on stdin), reach the interpreter without naming it.
const PY_DUMP = 'import os;print(os.environ)'
const PY_WRITE = "open('frontend/x.txt','w').write('1')"
for (const command of [
  `uv run -m timeit "${PY_DUMP}"`,
  `uv run --module timeit "${PY_DUMP}"`,
  `uv run -qm timeit "${PY_DUMP}"`,
  `uv run -m timeit -n1 "print(open('.env').read())"`,
  `uv run -m timeit -n1 "print(open('/home/u/.pypirc').read())"`,
  `uv run -m code <<'EOF'\n${PY_DUMP}\nEOF`,
  `uv run - <<'EOF'\n${PY_DUMP}\nEOF`,
  `echo "${PY_DUMP}" | uv run -`,
  `echo "${PY_DUMP}" | uv run --no-project -`,
  `uv run - <<'EOF'\nprint(open('.env').read())\nEOF`
]) {
  blocks(command)
}
for (const command of [
  `uv run -m timeit "${PY_WRITE}"`,
  `uv run --module timeit "${PY_WRITE}"`,
  `uv run -m code <<'EOF'\n${PY_WRITE}\nEOF`,
  `uv run - <<'EOF'\n${PY_WRITE}\nEOF`,
  `echo "${PY_WRITE}" | uv run --no-project -`
]) {
  blocks(command, { role: 'backend' })
}
for (const role of [undefined, 'backend']) {
  passes('uv run -m pytest', { role })
  passes('uv run -m pytest -q -k environ', { role })
  passes('uv run --module pytest', { role })
  passes('uv run -m app.openapi --write', { role })
  passes('uv run pytest -m slow', { role })
  passes('uv run -pm pytest', { role })
}

// Final review, I1: hidden uv value flags (not in `--help`) before and after the subcommand.
for (const command of [
  'uv --python-preference system run rm -rf x',
  'uv --preview-features x run git reset --hard',
  'uv --python-fetch automatic run rimraf x',
  'uv run --python-preference system rm -rf x',
  `uv run --python-preference system python -c "${PY_DUMP}"`,
  `uv --python-preference system run python -c "${PY_DUMP}"`,
  `uv run --preview-features x python -c "${PY_DUMP}"`,
  `uv run --python-fetch never python -c "print(open('.env').read())"`,
  // An unlisted flag still hides nothing: every later interpreter is judged.
  `uv run --newflag value python -c "${PY_DUMP}"`,
  `uv --newflag value run python -c "${PY_DUMP}"`,
  `uv run --newflag value node -e "console.log(process.env)"`,
  `uv run --newflag value python - <<'EOF'\n${PY_DUMP}\nEOF`,
  'npm --prefix backend exec rimraf x',
  'pnpm --filter x exec rm -rf y'
]) {
  blocks(command)
}
for (const command of [
  `uv run --python-preference system python -c "${PY_WRITE}"`,
  `uv run --newflag value python -c "${PY_WRITE}"`,
  `uv --newflag value run python -c "${PY_WRITE}"`,
  `uv run --newflag value node -e "1"`,
  `uv run --newflag value python - <<'EOF'\n${PY_WRITE}\nEOF`
]) {
  blocks(command, { role: 'backend' })
}
for (const role of [undefined, 'backend']) {
  passes('uv run --python-preference system pytest', { role })
  passes('uv --python-preference system run poe check', { role })
  passes('uv run --newflag value pytest -k environ', { role })
  passes('uv run --newflag value poe check', { role })
  passes('bun add rimraf', { role })
  passes('npm --prefix backend run build', { role })
  passes('pnpm --filter x exec prettier --check .', { role })
}

// Final review, I2: `env` behind a runner or wrapper still dumps the environment.
for (const command of [
  'uv run env',
  'uvx env',
  'poetry run env',
  'uv run printenv',
  'bun run env',
  'sudo env',
  'nohup env',
  'env -u FOO',
  'env FOO=1',
  'timeout 5 env',
  'echo ok; uv run env'
]) {
  blocks(command)
}
passes('env DEBUG=1 uv run poe dev')
passes('env -u FOO uv run poe dev')
passes('sudo ls')
passes('printenv DATABASE_URL')

// Final review, I3: the asyncio and IPython REPLs read stdin.
for (const module of ['asyncio', 'code', 'pdb', 'ipython', 'IPython']) {
  blocks(`python -m ${module} <<'EOF'\n${PY_DUMP}\nEOF`)
  blocks(`echo "${PY_DUMP}" | python -m ${module}`)
  blocks(`python -m ${module} <<'EOF'\nprint(open('.env').read())\nEOF`)
  blocks(`python -m ${module} <<'EOF'\n${PY_WRITE}\nEOF`, { role: 'backend' })
}
blocks(`python -Im asyncio <<'EOF'\n${PY_DUMP}\nEOF`)
passes('python -m pdb script.py')
passes('python -m pytest -k asyncio')
passes('python -m asyncio --help', { role: undefined })

// Final review, M1: pyw, ipython and dotless versioned launchers.
for (const launcher of ['pyw', 'ipython', 'python314', 'python3', 'pythonw', 'pypy310']) {
  blocks(`${launcher} -c "${PY_DUMP}"`)
  blocks(`${launcher} -c "${PY_WRITE}"`, { role: 'backend' })
}
passes('python314 -m pytest', { role: 'backend' })

// Final review, M3: poetry's repository credentials.
for (const command of [
  'cat ~/.config/pypoetry/auth.toml',
  'cat pypoetry/auth.toml',
  'type %APPDATA%\\pypoetry\\auth.toml',
  'Get-Content C:\\Users\\x\\AppData\\Roaming\\pypoetry\\auth.toml',
  `python -c "print(open('/home/u/.config/pypoetry/auth.toml').read())"`
]) {
  blocks(command)
}
passes('cat docs/auth.toml')
passes('cat pypoetry/config.toml')

// Final review, M10: a value flag of `uv run` placed before `python -c` neither hides the
// program nor the secret.
for (const flag of ['--with-requirements r.txt', '--package app', '--index https://x.test/simple', '--project backend']) {
  blocks(`uv run ${flag} python -c "${PY_DUMP}"`)
  blocks(`uv run ${flag} python -c "print(open('.env').read())"`)
  blocks(`uv run ${flag} python -c "${PY_WRITE}"`, { role: 'backend' })
  blocks(`uv run ${flag} python - <<'EOF'\n${PY_WRITE}\nEOF`, { role: 'backend' })
  passes(`uv run ${flag} pytest`)
  passes(`uv run ${flag} pytest`, { role: 'backend' })
}

// Addendum 2: the `--module=<mod>` spelling is the same channel as `--module <mod>`.
blocks(`uv run --module=timeit "${PY_DUMP}"`)
blocks(`uv run --with httpx --module=timeit "${PY_DUMP}"`)
blocks(`uv run --module=timeit "${PY_WRITE}"`, { role: 'backend' })
blocks(`uv run --module=code <<'EOF'\n${PY_DUMP}\nEOF`)
for (const role of [undefined, 'backend']) {
  passes('uv run --module=pytest -q', { role })
  passes('uv run --module=app.openapi --write', { role })
}
