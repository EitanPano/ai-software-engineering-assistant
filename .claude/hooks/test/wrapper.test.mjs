// Bypasses the guardrail review of 2026-10-24 found: a wrapper's value flag hid the program from
// every hook (`timeout -s KILL 5 rm -rf x`), and perl, ruby, php and deno inline code read
// secrets or dumped the environment.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { shellVerdict } from './harness.mjs'

const label = options =>
  `${options?.role ? ` [${options.role}]` : ''}${options?.tool ? ` (${options.tool})` : ''}`
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

// P0: each wrapper's own value flags, and the boolean flags the old shared table consumed.
for (const command of [
  'timeout --preserve-status 5 rm -rf x',
  'timeout -s KILL 5 rm -rf x',
  'timeout -sKILL 5 rm -rf x',
  'timeout -k 1 5 rm -rf x',
  'timeout --signal=KILL 5 git reset --hard',
  'timeout --kill-after 1 5 git push --force',
  'sudo --user root rm -rf x',
  'sudo -n rm -rf x',
  'sudo -E rm -rf x',
  'sudo -s rm -rf x',
  'sudo -iu root rm -rf x',
  'exec -a foo rm -rf x',
  'stdbuf -o L git reset --hard',
  'nice --adjustment 5 rm -rf x',
  'env --chdir /tmp rm -rf x',
  'env -iu FOO rm -rf x',
  'xargs -r rm -rf',
  'xargs -t rm -rf',
  'xargs -0 -r rm -rf',
  'xargs --max-args 1 rm -rf',
  'caffeinate -t 5 rm -rf x',
  'time -o out.txt rm -rf x',
  'npx --package foo rimraf x',
  'npx -p foo rm -rf x',
  'bash -o pipefail -c "rm -rf x"',
  'bash -eo pipefail -c "rm -rf x"',
  'bash +o posix -c "rm -rf x"',
  'bash --rcfile x -c "rm -rf x"',
  'cmd /e:on /c "rmdir /s /q x"',
  'env -S "rm -rf x"',
  'env -S"rm -rf x"',
  'env --split-string="rm -rf x"',
  'env -S "-i rm -rf x"',
  // A flag no table knows still cannot hide the program: every token of the tail is judged.
  'sudo --made-up v rm -rf x',
  'timeout --made-up v 5 git reset --hard',
  'nice --made-up v rimraf x'
]) {
  blocks(command)
}
// Judging every token of a wrapper's tail over-blocks a destructive spelling in an argument.
// Accepted: wrappers in front of `echo` are rare, and the alternative lets a flag hide a program.
blocks('sudo echo rm -r x')

// P0 on PowerShell: value parameters by any prefix, and an encoded command, which hides it.
for (const command of [
  'powershell -ExecutionPolicy Bypass -Command "Remove-Item -Recurse x"',
  'pwsh -ep Bypass -c "Remove-Item -Recurse x"',
  'powershell -ex bypass -Command "Remove-Item -Recurse x"',
  'powershell -WindowStyle Hidden -Command "Remove-Item -Recurse x"',
  'powershell /c "Remove-Item -Recurse x"',
  'powershell -EncodedCommand ZQBjAGgAbwAgADEA',
  'powershell -enc ZQBjAGgAbwAgADEA',
  'pwsh -e ZQBjAGgAbwAgADEA',
  'powershell -NoProfile -ec ZQBjAGgAbwAgADEA',
  'powershell -EncodedCommand:ZQBjAGgAbwAgADEA'
]) {
  blocks(command, { tool: 'PowerShell' })
}
for (const role of [undefined, 'backend']) {
  passes('powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1', {
    role,
    tool: 'PowerShell'
  })
}
passes('pwsh -NoProfile -Command "Get-ChildItem"', { tool: 'PowerShell' })
passes('powershell -ExecutionPolicy Bypass -Command "bun run check"', { tool: 'PowerShell' })

// P0 in the secret hook: inline code and environment dumps behind a wrapper's value flag.
for (const command of [
  'timeout -k 1 5 python -c "print(open(\'.env\').read())"',
  'sudo --user root python -c "import os; print(os.environ)"',
  'timeout --made-up v 5 node -e "console.log(process.env)"',
  'env -S "printenv"'
]) {
  blocks(command)
}

// P0 in the lane hook: write channels behind a wrapper's value flag.
for (const command of [
  'timeout -s KILL 5 node -e "1"',
  'sudo --user root tee frontend/x',
  'nice --adjustment 5 cp a frontend/b',
  'xargs -r rm',
  'timeout --made-up v 5 node -e "1"'
]) {
  blocks(command, { role: 'backend' })
}

// P1: perl, ruby, php and deno inline code that reads a secret file.
for (const command of [
  'perl -e "print `cat .env`"',
  "perl -e 'open(F, \".env\"); print <F>'",
  "perl -nle 'BEGIN { open F, q(.env) } print'",
  'ruby -e "puts File.read(\'.env\')"',
  "ruby -ne 'puts File.read(\".env\")'",
  'php -r "echo file_get_contents(\'.env\');"',
  "php -r'echo file_get_contents(\".env\");'",
  'deno eval "console.log(Deno.readTextFileSync(\'.env\'))"',
  // Attached inline code over several lines (P2).
  "node -e'const fs = require(\"fs\")\nconsole.log(fs.readFileSync(\".env\", \"utf8\"))'"
]) {
  blocks(command)
}

// P1: whole-environment reads in each language, inline and on stdin.
for (const command of [
  'perl -e "print %ENV"',
  "perl -E 'say for %ENV'",
  "perl -le 'print for keys %ENV'",
  'ruby -e "p ENV.to_h"',
  "ruby -e 'puts ENV.inspect'",
  "ruby -e 'p ENV'",
  'php -r "print_r(getenv());"',
  "php -r 'print_r($_ENV);'",
  "php -r 'var_dump($_SERVER);'",
  'deno eval "console.log(Deno.env.toObject())"',
  "perl <<'EOF'\nprint %ENV\nEOF",
  "echo 'p ENV.to_h' | ruby",
  "php <<'EOF'\n<?php print_r(getenv());\nEOF"
]) {
  blocks(command)
}
for (const command of [
  'perl -e "print 1"',
  "perl -e 'print $ENV{HOME}'",
  'ruby -e "puts ENV[\'HOME\']"',
  'ruby -e "puts ENV.fetch(\'HOME\')"',
  'php -r "echo getenv(\'HOME\');"',
  "php -r 'echo $_ENV[\"HOME\"];'",
  'deno eval "console.log(Deno.env.get(\'HOME\'))"',
  'perl script.pl',
  'ruby script.rb',
  'php artisan migrate:status'
]) {
  passes(command)
}

// The lane hook reads inline code the same way: clusters and deno eval are inline, while
// syntax checks and modules preloaded by path are not.
for (const command of [
  "perl -lne 'print' x",
  "perl -pi -e 's/a/b/' x",
  "ruby -ne 'puts' x",
  'deno eval "1"',
  "php -B 'echo 1;' -R 'echo 2;'"
]) {
  blocks(command, { role: 'backend' })
}
for (const command of [
  'node --check script.js',
  'node -r ./setup.js script.js',
  'ruby -c script.rb',
  'php -c php.ini script.php',
  'perl script.pl'
]) {
  passes(command, { role: 'backend' })
}

// Everyday wrapped commands keep passing.
for (const role of [undefined, 'backend']) {
  for (const command of [
    'timeout 300 bun run test',
    'timeout --preserve-status 300 bun run test',
    'timeout -s INT 300 bun run dev',
    'env -S "bun run check"',
    'nice -n 10 bun run build',
    'stdbuf -oL bun run dev',
    'bash -o pipefail -c "bun run check | tail -5"',
    'bash -lc "bun run check"',
    'env CI=1 bun test'
  ]) {
    passes(command, { role })
  }
}
passes('sudo -u postgres psql -c "SELECT 1"')
passes('xargs -I {} echo {}')
passes('xargs -r echo')
passes('npx --package prettier prettier --check .')

// Review of this fix, R1: env reads escapes and variables in its -S string, so those are refused.
blocks("env -S 'rm\\_-rf\\_x'")
blocks('env -S "${CMD} -rf x"')

// R2: a command string handed to a shell is split into commands, each judged on its own.
for (const command of [
  'bash -c "cd x; rm -rf y"',
  'bash -c "cd x && rm -rf y"',
  'sh -c "true | rm -rf y"',
  'bash -lc "cd backend\nrm -rf node_modules"',
  'sh -c "bash -c \'cd x; git reset --hard\'"',
  'sudo --made-up v bash -c "cd x; rm -rf y"',
  'cmd /c "cd x & rmdir /s /q y"',
  'cmd /c"rmdir /s /q x"',
  'cmd /crmdir /s /q x',
  'fish -C "rm -rf x"',
  'fish -C "echo hi" -c "rm -rf x"',
  'bash -c "cd x; printenv"',
  'bash -c "cd x; python -c \'import os; print(os.environ)\'"'
]) {
  blocks(command)
}
for (const command of [
  'powershell -Command "cd x; Remove-Item -Recurse y"',
  // PowerShell reads an en dash as a dash.
  'Remove-Item –Recurse x',
  'pwsh –Command "Remove-Item -Recurse x"',
  'pwsh –EncodedCommand ZQBjAGgAbwAgADEA'
]) {
  blocks(command, { tool: 'PowerShell' })
}
for (const command of [
  'bash -c "cd x; tee frontend/y"',
  'bash -c "echo 1 > frontend/x"',
  'sh -c "cd backend && node -e 1"'
]) {
  blocks(command, { role: 'backend' })
}
for (const role of [undefined, 'backend']) {
  passes('bash -c "cd backend && bun run check"', { role })
  passes('bash -c "bun run check 2>&1 | tail -5"', { role })
  passes('powershell -Command "cd backend; bun run check"', { role, tool: 'PowerShell' })
}
// A quoted argument that is not handed to a shell stays one argument.
passes('git commit -m "docs: rm -rf is refused; so is git reset --hard"')

// R3: abbreviated GNU long options and strtod durations no longer hide the program, and an
// environment dump anywhere in a wrapper's tail is judged.
for (const command of [
  'timeout 1e1 printenv',
  'timeout --sig KILL 5 printenv',
  'env --ch /tmp printenv',
  'nice --adj 5 printenv',
  'sudo --made-up v printenv',
  'timeout 1e1 rm -rf x'
]) {
  blocks(command)
}
blocks('timeout --sig KILL 5 Get-ChildItem Env:', { tool: 'PowerShell' })
for (const command of [
  'timeout --sig KILL 5 cp a frontend/b',
  'sudo --us root tee frontend/x',
  'timeout 1e1 git commit -m x',
  'timeout 1e1 sed -i s/a/b/ frontend/x'
]) {
  blocks(command, { role: 'backend' })
}
passes('timeout 1e1 bun run test')
passes('timeout 1e1 bun run test', { role: 'backend' })

// R4: a perl switch with an attached value (-M, -I) is not inline code.
passes('perl -MTest::More t/basic.t', { role: 'backend' })
passes('perl -I lib -Mstrict script.pl', { role: 'backend' })
