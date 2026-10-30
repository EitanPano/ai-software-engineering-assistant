const CODE = /\.(?:[cm]?[jt]sx?|py)$/
const E2E_SPEC = /(?:^|[\\/.-])e2e(?:[\\/.-]|$)|\.spec\.[^\\/]+$/i
// A focus or skip spelling matters on a test path; `cursor.skip(n)` in `src/` is paging.
const TEST_PATH = [
  /(?:^|\/)(?:tests|__tests__|e2e)\//,
  /\.(?:test|spec)\.[^/]+$/,
  /(?:^|\/)test_[^/]*\.py$/,
  /_test\.py$/,
  /(?:^|\/)conftest\.py$/,
]
const TEST_SKIP = [
  /\.only\(/,
  /\.(?:only|skip)\.each\(/,
  /(?<![.\w$])f(?:it|describe)\(/,
  /\.skip\(/,
  // `describe.skip` or `it.skip` used as a value, not called.
  /\.skip\b(?!\()/,
  /\.todo\(/,
  // The conditional spellings the bun and Vitest runners add.
  /\.(?:skipIf|runIf|todoIf|failing|failingIf|if)\(/,
  /\btest\.fixme\(/,
  /\bxit\(/,
  /\bxtest\(/,
  /\bxdescribe\(/,
  /\bpytest\.mark\.skip/,
  /\bskipif\b/,
  /\bxfail\b/,
  /\bpytest\.skip\(/,
]
// The catalog's one store seam (python-fastapi `tests/store.py`) skips on this reason; the
// `database` gate, not this check, proves those suites ran.
const STORE_SEAM = /(?:\bpytest\.mark\.)?\bskipif\((?=[^\n]*\breason=STORE_SKIP_REASON\b)/
const EXCLUDE = /\.exclude\(/
// One line only: an `expect(…)` chain split over several lines is not caught. A false positive
// is accepted: `expect(await load().catch(() => null)).toBe(null)` matches too.
const SWALLOWED = /\bexpect\s*\([^;]*\)\s*\.catch\(/
const PY_SWALLOWED = /^\s*except\b[^#]*\bAssertionError\b/

const isTestPath = (file) => TEST_PATH.some((pattern) => pattern.test(file.replaceAll('\\', '/')))

export function check(name, hits) {
  const shown = hits.slice(0, 10).map((hit) => `${hit.file}:${hit.line} ${hit.text.trim()}`)
  if (hits.length > 10) shown.push(`and ${hits.length - 10} more`)
  return { name, ok: hits.length === 0, detail: shown.join('; ') }
}

// `added` is [{ file, line, text }] from the diff and the untracked files. Only code files are
// read, so a plan or a skill that names `.only(` in prose does not trip the gate.
export function diffChecks(added) {
  const code = added.filter((entry) => CODE.test(entry.file))
  const skips = code.filter((entry) => {
    if (!isTestPath(entry.file)) return false
    const text = entry.text.replace(STORE_SEAM, '(')
    return TEST_SKIP.some((pattern) => pattern.test(text))
  })
  const excludes = code.filter((e) => E2E_SPEC.test(e.file) && EXCLUDE.test(e.text))
  const swallowed = code.filter((entry) => {
    if (!isTestPath(entry.file)) return false
    if (entry.file.endsWith('.py')) return PY_SWALLOWED.test(entry.text)
    return SWALLOWED.test(entry.text)
  })
  return [
    check('no-focused-or-skipped-test', skips),
    check('no-axe-exclude', excludes),
    check('no-swallowed-assertion', swallowed),
  ]
}
