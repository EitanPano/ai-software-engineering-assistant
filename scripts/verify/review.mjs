import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { git } from './git.mjs'
import { matching } from './glob.mjs'

// Mirrors SECRET_NAME in .claude/hooks/block-secret-file-access.mjs, which exports no predicate.
// Such files stay out of the body (the stat and the name list still show them) so the reviewer
// can raise them without the content being copied to disk.
const SECRET_NAME = [
  /^\.env(\..+)?$/i,
  /\.(pem|key|p12|pfx|jks|keystore|kdbx|tfstate)$/i,
  /^id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$/i,
  /^(\.npmrc|\.netrc|\.pgpass|\.git-credentials|\.htpasswd|kubeconfig)$/i,
  /^(\.pypirc|pip\.(conf|ini))$/i,
  /^(credentials|secrets?)\.(json|ya?ml|toml|env|txt|properties|ini)$/i,
  /service[-_]?account.*\.json$/i,
]
const SECRET_ALLOWED = /^\.env\.(example|sample|template)$/i
// Directories that only ever hold credentials, anywhere in the path.
const SECRET_DIR = /(^|[/\\])(\.aws|\.ssh|\.gnupg|\.kube|\.docker)([/\\]|$)/i
const isSecretName = (file) => {
  if (SECRET_DIR.test(file)) return true
  const name = file.slice(file.lastIndexOf('/') + 1)
  if (SECRET_ALLOWED.test(name)) return false
  // The hook treats any base name starting with `.env` as secret (`.envrc`, `.env-foo`).
  return /^\.env/i.test(name) || SECRET_NAME.some((pattern) => pattern.test(name))
}

function run(root, args) {
  const result = git(root, args)
  if (!result.ok) throw new Error(`git ${args[0]} failed while writing the review package`)
  return result.out
}

// Still listed in the stat, left out of the diff body: lockfiles and generated files.
export const EXCLUDED = [
  '**/bun.lock',
  '**/bun.lockb',
  '**/package-lock.json',
  '**/yarn.lock',
  '**/pnpm-lock.yaml',
  '**/uv.lock',
  '**/poetry.lock',
  '**/openapi.json',
  '**/lib/api/schema.d.ts',
  '**/api/generated/**',
]

// The review package text: a header, the stat of every changed file, the excluded paths, and
// the `-U10` diff of the rest. `from` is a commit or tree; `to` is the verified tree.
export function reviewText(root, header, from, to) {
  const names = run(root, ['diff', '--name-only', '--no-renames', from, to])
  const files = names.split(/\r?\n/).filter(Boolean)
  const excluded = matching(files, EXCLUDED)
  const secret = files.filter(isSecretName)
  const stat = run(root, ['diff', '--stat=200', '--no-color', '--no-renames', from, to])
  const skip = [...excluded, ...secret].map((file) => `:(exclude,literal)${file}`)
  const args = ['diff', '-U10', '--no-color', '--no-renames', from, to]
  const body = run(root, [...args, ...(skip.length > 0 ? ['--', '.', ...skip] : [])])
  const list = excluded.length > 0 ? excluded.join(', ') : 'none'
  const parts = [header.join('\n'), stat.trimEnd(), `excluded from the diff below: ${list}`]
  if (secret.length > 0) parts.push(`secret-named, not shown: ${secret.join(', ')}`)
  return `${parts.join('\n\n')}\n\n${body}`
}

// Writes `review.diff`, and `review-fix-<n>.diff` on a fix round; returns the file names.
export function writeReviewPackage(root, outDir, { base, tree, round }) {
  mkdirSync(outDir, { recursive: true })
  const commit = run(root, ['rev-parse', `${base}^{commit}`]).trim()
  // Every text is built before the first file is written, so a git failure leaves no package.
  const files = []
  const put = (name, text) => files.push([name, text])
  const header = ['# review package', `base ${commit}`, `tree ${tree}`]
  put('review.diff', reviewText(root, header, commit, tree))
  if (round !== undefined) {
    const fixHeader = [
      `# review package: fix round ${round.n}`,
      `round-base ${round.base}`,
      `tree ${tree}`,
    ]
    put(`review-fix-${round.n}.diff`, reviewText(root, fixHeader, round.base, tree))
  }
  for (const [name, text] of files) writeFileSync(path.join(outDir, name), text)
  return files.map(([name]) => name)
}
