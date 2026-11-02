import type { FullResult, Reporter, TestCase } from '@playwright/test/reporter'

// `verify` keeps only the end of a failed step's output and a failing suite prints far more than
// that, so what a dying web server said was lost (plan 006). Printing each server's last lines
// after the summary puts them in that end. The limit is per server, so the API's logs cannot
// crowd out the preview server's, and six servers at this limit print at most 74 of `verify`'s 80 lines.
export const LINES_PER_SERVER = 12

// Playwright starts each line of a web server's output with `[name] `, coloured when it may be.
const SERVER_LINE = /\[([\w-]+)\] /

export default class WebServerTail implements Reporter {
  private readonly tails = new Map<string, string[]>()

  onStdOut(chunk: string | Buffer, test?: TestCase) {
    this.keep(chunk, test)
  }

  onStdErr(chunk: string | Buffer, test?: TestCase) {
    this.keep(chunk, test)
  }

  onEnd(result: FullResult) {
    if (result.status === 'passed' || this.tails.size === 0) return
    console.log(`\nWeb servers, last ${String(LINES_PER_SERVER)} lines each:`)
    for (const lines of this.tails.values()) console.log(lines.join('\n'))
  }

  private keep(chunk: string | Buffer, test?: TestCase) {
    if (test) return
    for (const line of chunk.toString().split('\n')) {
      const server = SERVER_LINE.exec(line)?.[1]
      if (server === undefined) continue
      this.tails.set(server, [...(this.tails.get(server) ?? []), line].slice(-LINES_PER_SERVER))
    }
  }
}
