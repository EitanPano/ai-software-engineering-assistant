import {
  formatCosine,
  formatScore,
  kindLabel,
  skipReasonLabel,
  type EvalCaseResult,
} from '../model'

const HEAD = 'px-3 py-2 text-left font-medium text-muted-foreground'
const NUM = 'px-3 py-2 text-right tabular-nums'

// Each case's result. A question is repository-derived text and renders as text, never through
// `Markdown`. A skipped case says why in its row instead of showing zeros.
export function EvalCaseTable({ cases }: { cases: EvalCaseResult[] }) {
  return (
    // Focusable so a keyboard user can scroll it (axe: scrollable-region-focusable).
    <div
      role="region"
      aria-label="Cases, scrollable"
      // A scrollable region must be keyboard reachable (axe scrollable-region-focusable).
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      className="overflow-x-auto rounded-lg border border-border outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      <table aria-label="Cases" className="w-full min-w-[48rem] text-sm">
        <thead className="border-b border-border bg-muted/50">
          <tr>
            <th scope="col" className={HEAD}>
              Question
            </th>
            <th scope="col" className={HEAD}>
              Kind
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Rank
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Recall@5
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              RR
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              nDCG@10
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Top cosine
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Relevant cosine
            </th>
          </tr>
        </thead>
        <tbody>
          {cases.map((result, index) => {
            const skipped = skipReasonLabel(result.skipReason)
            return (
              <tr
                key={`${String(index)}:${result.question}`}
                className="border-b border-border align-top last:border-0"
              >
                <th scope="row" className="px-3 py-2 text-left font-normal">
                  <span className="break-words">{result.question}</span>
                  {skipped ? (
                    <span className="mt-1 block text-xs text-muted-foreground">{skipped}</span>
                  ) : null}
                  {result.incomplete ? (
                    <span className="mt-1 block text-xs text-muted-foreground">
                      Incomplete: a search was cut short.
                    </span>
                  ) : null}
                </th>
                <td className="px-3 py-2">{kindLabel(result.kind)}</td>
                <td className={NUM}>{result.rank ?? '–'}</td>
                <td className={NUM}>{formatScore(result.recallAt5)}</td>
                <td className={NUM}>{formatScore(result.reciprocalRank)}</td>
                <td className={NUM}>{formatScore(result.ndcgAt10)}</td>
                <td className={NUM}>{formatCosine(result.topCosine)}</td>
                <td className={NUM}>{formatCosine(result.relevantCosine)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
