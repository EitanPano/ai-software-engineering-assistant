import type { FullResult, TestCase } from '@playwright/test/reporter'
import { afterEach, describe, expect, it, vi } from 'vitest'

import WebServerTail, { LINES_PER_SERVER } from '../../scripts/web-server-tail'

const FAILED = { status: 'failed' } as FullResult
const PASSED = { status: 'passed' } as FullResult

function printed(reporter: WebServerTail, result: FullResult) {
  const log = vi.spyOn(console, 'log').mockImplementation(() => undefined)
  reporter.onEnd(result)
  return log.mock.calls.flat().join('\n')
}

describe('WebServerTail', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('prints the last lines of each server after a failed run', () => {
    const reporter = new WebServerTail()
    for (let line = 0; line <= LINES_PER_SERVER; line++) {
      reporter.onStdOut(`[api] request ${String(line)}\n`)
    }
    reporter.onStdErr('[preview] listening\n[preview] Error: read ECONNRESET\n')

    const output = printed(reporter, FAILED)

    expect(output).toContain('[preview] Error: read ECONNRESET')
    expect(output).toContain(`[api] request ${String(LINES_PER_SERVER)}`)
    // The one line past the limit, so the API cannot crowd the preview server out.
    expect(output).not.toContain('[api] request 0\n')
  })

  it('reads a coloured prefix', () => {
    const reporter = new WebServerTail()
    reporter.onStdErr('\u001b[2m[preview] \u001b[22mboom\n')

    expect(printed(reporter, FAILED)).toContain('boom')
  })

  it('prints nothing after a passed run', () => {
    const reporter = new WebServerTail()
    reporter.onStdErr('[preview] listening\n')

    expect(printed(reporter, PASSED)).toBe('')
  })

  it('prints nothing when no web server ran', () => {
    expect(printed(new WebServerTail(), FAILED)).toBe('')
  })

  it('leaves out what a test printed', () => {
    const reporter = new WebServerTail()
    reporter.onStdOut('[preview] from a test\n', {} as TestCase)

    expect(printed(reporter, FAILED)).toBe('')
  })
})
