import { CircleAlertIcon } from 'lucide-react'
import { Link } from 'react-router'

import { formatDateTime } from '@/shared/lib/date'
import { Badge } from '@/shared/ui/badge'

import {
  caseCountLabel,
  errorReason,
  formatScore,
  statusLabel,
  statusTone,
  type EvalRun,
} from '../model'

// The run's status as a badge: a failure is an outline in the destructive text colour with an
// icon (the filled badge fails the dark-mode contrast scan on a card), never colour alone.
export function EvalRunStatusBadge({ status }: { status: EvalRun['status'] }) {
  return status === 'failed' ? (
    <Badge variant="outline" className="border-destructive text-destructive">
      <CircleAlertIcon aria-hidden />
      {statusLabel(status)}
    </Badge>
  ) : (
    <Badge variant={statusTone(status)}>{statusLabel(status)}</Badge>
  )
}

// One run of the list, as a link to its record: when it started, its status in words, the case
// counts and the headline scores (or why it failed). Scores wrap under the title on a phone.
export function EvalRunRow({ run }: { run: EvalRun }) {
  const reason = errorReason(run.errorCode)
  const { headline } = run
  return (
    <Link
      to={`/eval-run/${run.id}`}
      className="flex flex-col gap-2 rounded-lg border border-border bg-card px-4 py-3 text-card-foreground outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      <span className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{formatDateTime(run.createdAt, 'UTC')} UTC</span>
        <EvalRunStatusBadge status={run.status} />
      </span>
      {run.status === 'completed' ? (
        <span className="text-sm text-muted-foreground">
          {caseCountLabel(run.caseCount)}
          {run.skippedCaseCount > 0 ? ` · ${String(run.skippedCaseCount)} skipped` : ''}
          {run.incompleteCaseCount > 0 ? ` · ${String(run.incompleteCaseCount)} incomplete` : ''}
        </span>
      ) : null}
      {headline ? (
        <span className="flex flex-wrap gap-x-4 gap-y-1 text-sm tabular-nums">
          <span>Recall@5 {formatScore(headline.recallAt5)}</span>
          <span>Recall@10 {formatScore(headline.recallAt10)}</span>
          <span>Recall@20 {formatScore(headline.recallAt20)}</span>
          <span>MRR {formatScore(headline.mrr)}</span>
          <span>nDCG@10 {formatScore(headline.ndcgAt10)}</span>
        </span>
      ) : null}
      {run.status === 'failed' && reason ? (
        <span className="text-sm text-destructive">{reason}</span>
      ) : null}
    </Link>
  )
}
