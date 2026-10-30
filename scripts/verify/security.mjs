import { matching } from './glob.mjs'

// The paths whose change asks for the security review (dev-loop §4). Plan 014 D2 narrowed the
// list: migrations and `.sql` files no longer trigger. Each package's env module is listed by
// the catalog's template layout.
const GLOBS = [
  '**/auth/**',
  '**/session/**',
  '**/*session*',
  '**/security/**',
  '**/middleware/**',
  '**/proxy.ts',
  '**/shared/auth/**',
  '**/cors.*',
  '**/Dockerfile',
  'docker-compose.yml',
  // bun-express `src/config/env.ts`, python-fastapi `src/app/config/env.py`, and the v1.4.0
  // frontends' `src/shared/config/env.ts` (matched by `**/config/env.ts`). `**/src/env.ts`
  // stays for 1.x frontends.
  '**/config/env.ts',
  '**/config/env.py',
  '**/src/env.ts',
  // Deploy configuration: rarely changed, and it sets headers, build context and routing.
  '**/nginx/**',
  '**/.dockerignore',
  '**/next.config.*',
  // Privilege tools, and the auth entity's roles (plan 016).
  '**/*seed*',
  '**/models/user/**',
]
// A login form is UI; it fires only by a gate line (plan 014, plan 016).
const UI_ONLY = ['**/auth/ui/**']
const CODE = /\.(?:[cm]?[jt]sx?|py)$/
const GATE =
  /(?<![\w$])(?:requireAuth|requireRole|requireAccount|assertRole|require_auth|require_role|require_caller|_assert_role|roleAction|accountAction)(?![\w$])/

// The code files whose changed lines (added or removed) name a gate, from `git diff -U0` text.
export function gateFiles(patch) {
  const found = new Set()
  let file = ''
  let old = ''
  let inHunk = false
  for (const text of patch.split(/\r?\n/)) {
    if (text.startsWith('diff --git ')) inHunk = false
    else if (!inHunk && text.startsWith('--- ')) old = text.slice(4).replace(/^a\//, '')
    else if (!inHunk && text.startsWith('+++ ')) {
      file = text === '+++ /dev/null' ? old : text.slice(4).replace(/^b\//, '')
    } else if (text.startsWith('@@')) inHunk = true
    else if (inHunk && (text[0] === '+' || text[0] === '-') && GATE.test(text.slice(1))) {
      if (CODE.test(file) && matching([file], ['**/migrations/**']).length === 0) found.add(file)
    }
  }
  return [...found]
}

// `lineFiles` are the gate-line files of the same change; only those in `files` count.
export function securityPaths(files, lineFiles = []) {
  const ui = new Set(matching(files, UI_ONLY))
  const byPath = new Set(matching(files, GLOBS).filter((file) => !ui.has(file)))
  const byLine = new Set(lineFiles)
  return files.filter((file) => byPath.has(file) || byLine.has(file))
}

// The security result for a change, from the `git diff -U0` result. A failed diff cannot prove
// the gate lines unchanged, so it triggers the review.
export function securityFor(files, patch) {
  if (!patch.ok) return { triggered: true, paths: files }
  const paths = securityPaths(files, gateFiles(patch.out))
  return { triggered: paths.length > 0, paths }
}
