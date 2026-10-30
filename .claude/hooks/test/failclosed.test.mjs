// The fail-closed contract: a hook that cannot read its input, or crashes after reading it,
// blocks (exit 2) instead of allowing.
import assert from 'node:assert/strict'
import path from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { BOUNDARIES_HOOK, DESTRUCTIVE_HOOK, SECRET_HOOK, runHookRaw } from './harness.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))

for (const hook of [SECRET_HOOK, DESTRUCTIVE_HOOK, BOUNDARIES_HOOK]) {
  for (const [name, input] of [
    ['an empty payload', ''],
    ['invalid JSON', 'not json'],
    ['a non-object payload', '[]'],
    ['a payload without tool_input', '{"tool_name":"Bash"}'],
    ['a null tool_input', '{"tool_input":null}']
  ]) {
    test(`${hook} blocks ${name}`, () => {
      assert.equal(runHookRaw(hook, input).status, 2)
    })
  }
}

test('a hook that throws after parsing exits 2', () => {
  const result = runHookRaw(
    path.join(here, 'fixtures', 'throwing-hook.mjs'),
    '{"tool_name":"Bash","tool_input":{"command":"ls"}}'
  )
  assert.equal(result.status, 2)
  assert.match(result.stderr, /hook crashed/)
})

test('control: the same hook allows a harmless valid payload', () => {
  const result = runHookRaw(DESTRUCTIVE_HOOK, '{"tool_name":"Bash","tool_input":{"command":"ls"}}')
  assert.equal(result.status, 0)
})

// A shell call whose command is not a string cannot be inspected: every hook that reads the
// command blocks it. The boundaries hook only reads it for a role session.
for (const tool_name of ['Bash', 'PowerShell']) {
  for (const command of [['rm', '-rf', 'x'], null, 5, { a: 1 }]) {
    for (const [hook, agent_type] of [
      [SECRET_HOOK, undefined],
      [DESTRUCTIVE_HOOK, undefined],
      [BOUNDARIES_HOOK, 'backend']
    ]) {
      test(`${hook} blocks a ${tool_name} command of ${JSON.stringify(command)}`, () => {
        const input = JSON.stringify({ tool_name, tool_input: { command }, agent_type })
        const result = runHookRaw(hook, input)
        assert.equal(result.status, 2)
        assert.match(result.stderr, /command is not a string/)
      })
    }
  }
}

test('a non-shell tool without a command still passes the command hooks', () => {
  const input = JSON.stringify({ tool_name: 'Read', tool_input: { file_path: 'README.md' } })
  assert.equal(runHookRaw(SECRET_HOOK, input).status, 0)
  assert.equal(runHookRaw(DESTRUCTIVE_HOOK, input).status, 0)
})
