import { formatScore, kindLabel, searchLabel, type EvalScore } from '../model'

const HEAD = 'px-3 py-2 text-left font-medium text-muted-foreground'
const NUM = 'px-3 py-2 text-right tabular-nums'

// The scores by search and kind, one row each. The table scrolls inside its own container on a
// phone; the page never does. A row with no case is absent from the API, so it is absent here.
export function EvalScoreTable({ scores }: { scores: EvalScore[] }) {
  return (
    // Focusable so a keyboard user can scroll it (axe: scrollable-region-focusable).
    <div
      role="region"
      aria-label="Scores, scrollable"
      // A scrollable region must be keyboard reachable (axe scrollable-region-focusable).
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      className="overflow-x-auto rounded-lg border border-border outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      <table aria-label="Scores by search and kind" className="w-full min-w-[40rem] text-sm">
        <thead className="border-b border-border bg-muted/50">
          <tr>
            <th scope="col" className={HEAD}>
              Search
            </th>
            <th scope="col" className={HEAD}>
              Kind
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Cases
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Recall@5
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Recall@10
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Recall@20
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              MRR
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              nDCG@10
            </th>
          </tr>
        </thead>
        <tbody>
          {scores.map((score) => (
            <tr
              key={`${score.search}:${score.kind}`}
              className="border-b border-border last:border-0"
            >
              <th scope="row" className="px-3 py-2 text-left font-medium">
                {searchLabel(score.search)}
              </th>
              <td className="px-3 py-2">{kindLabel(score.kind)}</td>
              <td className={NUM}>{score.caseCount}</td>
              <td className={NUM}>{formatScore(score.recallAt5)}</td>
              <td className={NUM}>{formatScore(score.recallAt10)}</td>
              <td className={NUM}>{formatScore(score.recallAt20)}</td>
              <td className={NUM}>{formatScore(score.mrr)}</td>
              <td className={NUM}>{formatScore(score.ndcgAt10)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
