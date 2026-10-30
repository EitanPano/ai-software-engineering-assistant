// Spawns a hook the way Claude Code does: `node <hook>`, JSON payload on stdin,
// CLAUDE_PROJECT_DIR in the environment. Exit 0 allows, exit 2 blocks.
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
export const ROOT = path.resolve(here, '..', '..', '..')
const HOOKS = path.join(ROOT, '.claude', 'hooks')

export const SECRET_HOOK = 'block-secret-file-access.mjs'
export const DESTRUCTIVE_HOOK = 'block-destructive-bash.mjs'
export const BOUNDARIES_HOOK = 'enforce-agent-boundaries.mjs'

export function runHook(hook, payload) {
  const env = { ...process.env, CLAUDE_PROJECT_DIR: ROOT }
  delete env.AGENT_ROLE
  const result = spawnSync('node', [path.join(HOOKS, hook)], {
    input: JSON.stringify({ cwd: ROOT, ...payload }),
    env,
    encoding: 'utf8'
  })
  return { status: result.status, stderr: result.stderr }
}

// Spawns a hook with raw stdin, no payload wrapping: for malformed input and for fixture hooks.
// `hookPath` is a file name under .claude/hooks or an absolute path.
export function runHookRaw(hookPath, input) {
  const env = { ...process.env, CLAUDE_PROJECT_DIR: ROOT }
  delete env.AGENT_ROLE
  const file = path.isAbsolute(hookPath) ? hookPath : path.join(HOOKS, hookPath)
  const result = spawnSync('node', [file], { input, env, encoding: 'utf8' })
  return { status: result.status, stderr: result.stderr }
}

export function shellPayload(command, { role, tool = 'Bash' } = {}) {
  const payload = { tool_name: tool, tool_input: { command } }
  if (role !== undefined) payload.agent_type = role
  return payload
}

export function filePayload(tool, filePath, role) {
  const payload = { tool_name: tool, tool_input: { file_path: filePath, content: 'x' } }
  if (role !== undefined) payload.agent_type = role
  return payload
}

// The verdict of the hooks wired on a shell tool, in settings.json order. The first hook
// that blocks names itself, so a failure message shows which guardrail fired.
export function shellVerdict(command, options = {}) {
  return verdictOf(shellPayload(command, options), [SECRET_HOOK, DESTRUCTIVE_HOOK, BOUNDARIES_HOOK])
}

export function fileVerdict(tool, filePath, role) {
  return verdictOf(filePayload(tool, filePath, role), [SECRET_HOOK, BOUNDARIES_HOOK])
}

function verdictOf(payload, hooks) {
  for (const hook of hooks) {
    const { status, stderr } = runHook(hook, payload)
    if (status !== 0) return { blocked: true, hook, stderr: stderr.trim() }
  }
  return { blocked: false, hook: null, stderr: '' }
}
