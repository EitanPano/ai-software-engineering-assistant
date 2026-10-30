const ANSI = /\u001b\[[0-9;]*m/g
const WORDS = 'passed|failed|skipped|flaky|pass|fail|skip|todo|xfailed|xpassed|errors?|did not run'
// A summary line starts with a count and a word (bun, Playwright), `Tests` (Vitest) or `=`
// (pytest).
const SUMMARY = new RegExp(String.raw`^\s*=*\s*(?:Tests?\s+)?\d+ (?:${WORDS})\b`)
const PAIR = new RegExp(String.raw`(\d+) (${WORDS})\b`, 'g')
const KIND = {
  passed: 'passed',
  pass: 'passed',
  xpassed: 'passed',
  failed: 'failed',
  fail: 'failed',
  error: 'failed',
  errors: 'failed',
  skipped: 'skipped',
  skip: 'skipped',
  todo: 'skipped',
  xfailed: 'skipped',
  'did not run': 'skipped',
  flaky: 'flaky',
}

// Best effort over bun test, Vitest, Playwright and pytest: the exit code decides, the counts
// only report. Per summary line the last one wins, so a final total overrides a progress line.
export function parseSummary(output) {
  const counts = { passed: 0, failed: 0, skipped: 0, flaky: 0 }
  for (const line of output.replace(ANSI, '').split(/\r?\n/)) {
    if (!SUMMARY.test(line)) continue
    const seen = {}
    for (const [, count, word] of line.matchAll(PAIR)) {
      seen[KIND[word]] = (seen[KIND[word]] ?? 0) + Number(count)
    }
    // bun and Playwright print one kind per line, so a kind absent from this line keeps its
    // value; one printed as 0 resets it, which is how a final "0 fail" clears an earlier log line.
    const whole = /^\s*=|Tests?\s/.test(line)
    for (const kind of Object.keys(counts)) {
      if (kind in seen || whole) counts[kind] = seen[kind] ?? 0
    }
  }
  return counts
}

export function tail(output, lines = 80) {
  return output.replace(ANSI, '').split(/\r?\n/).slice(-lines).join('\n').trim()
}
