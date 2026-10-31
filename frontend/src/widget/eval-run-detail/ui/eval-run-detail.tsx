import { useSuspenseQuery } from '@tanstack/react-query'
import { TriangleAlertIcon } from 'lucide-react'

import { evalRunQuery } from '@/entity/eval-run/api/eval-run'
import {
  caseCountLabel,
  errorReason,
  formatCosine,
  formatScore,
  isActive,
  type EvalRunDetail,
} from '@/entity/eval-run/model'
import { EvalCaseTable } from '@/entity/eval-run/ui/eval-case-table'
import { EvalRunStatusBadge } from '@/entity/eval-run/ui/eval-run-row'
import { EvalScoreTable } from '@/entity/eval-run/ui/eval-score-table'
import { formatDateTime } from '@/shared/lib/date'
import { Alert, AlertDescription, AlertTitle } from '@/shared/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card'
import { Section } from '@/shared/ui/pattern/page-layout'

import { EvalRunDetailSkeleton } from './eval-run-detail-skeleton'

const plural = (count: number, one: string, many: string) => (count === 1 ? one : many)

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card className="gap-2 py-4">
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent className="text-2xl font-semibold tabular-nums">{value}</CardContent>
    </Card>
  )
}

function Caveats({ run }: { run: EvalRunDetail }) {
  if (run.skippedCaseCount === 0 && run.incompleteCaseCount === 0) return null
  return (
    <Alert>
      <TriangleAlertIcon aria-hidden />
      <AlertTitle>Some cases do not count towards the scores</AlertTitle>
      <AlertDescription>
        {run.skippedCaseCount > 0 ? (
          <p>
            {run.skippedCaseCount} {plural(run.skippedCaseCount, 'case was', 'cases were')} skipped
            and spent nothing.
          </p>
        ) : null}
        {run.incompleteCaseCount > 0 ? (
          <p>
            {run.incompleteCaseCount} {plural(run.incompleteCaseCount, 'case was', 'cases were')}{' '}
            incomplete: a search was cut short.
          </p>
        ) : null}
      </AlertDescription>
    </Alert>
  )
}

// One eval run's record, behind `requireRole(…, 'admin')`. While the run is active it shows its
// status over skeleton cards, and the query refetches until it settles; a failed run gives its
// reason in words; a completed one shows the headline, the scores, the cosine evidence, the corpus
// and each case. A question renders as text.
export function EvalRunDetailView({ id }: { id: string }) {
  const { data: run } = useSuspenseQuery(evalRunQuery(id))
  const reason = errorReason(run.errorCode)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <EvalRunStatusBadge status={run.status} />
        <span>Started {formatDateTime(run.createdAt, 'UTC')} UTC</span>
        {run.status === 'completed' ? <span>· {caseCountLabel(run.caseCount)}</span> : null}
      </div>

      {isActive(run) ? (
        <EvalRunDetailSkeleton label="Loading scores" />
      ) : run.status === 'failed' ? (
        <p className="text-sm text-destructive">{reason}</p>
      ) : (
        <>
          <Caveats run={run} />
          {run.headline ? (
            <Section title="Hybrid search">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
                <Metric label="Recall@5" value={formatScore(run.headline.recallAt5)} />
                <Metric label="Recall@10" value={formatScore(run.headline.recallAt10)} />
                <Metric label="Recall@20" value={formatScore(run.headline.recallAt20)} />
                <Metric label="MRR" value={formatScore(run.headline.mrr)} />
                <Metric label="nDCG@10" value={formatScore(run.headline.ndcgAt10)} />
              </div>
            </Section>
          ) : null}
          <Section title="Scores">
            <EvalScoreTable scores={run.scores} />
          </Section>
          {run.cosine ? (
            <Section title="Cosine">
              <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <dt className="text-muted-foreground">Relevant, lowest</dt>
                  <dd className="tabular-nums">{formatCosine(run.cosine.relevantMin)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Relevant, median</dt>
                  <dd className="tabular-nums">{formatCosine(run.cosine.relevantMedian)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">No answer, median</dt>
                  <dd className="tabular-nums">{formatCosine(run.cosine.noAnswerMedian)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">No answer, highest</dt>
                  <dd className="tabular-nums">{formatCosine(run.cosine.noAnswerMax)}</dd>
                </div>
              </dl>
            </Section>
          ) : null}
          {run.corpus.length > 0 || run.settings ? (
            <Section title="Corpus and settings">
              <ul className="flex flex-col gap-1 text-sm">
                {run.corpus.map((source) => (
                  <li key={`${source.url}@${source.indexedCommit}`}>
                    <span className="font-medium">
                      {source.url.replace('https://github.com/', '')}
                    </span>{' '}
                    <span className="text-muted-foreground">
                      at {source.ref} ({source.indexedCommit.slice(0, 7)}) · {source.chunkCount}{' '}
                      chunks
                    </span>
                  </li>
                ))}
              </ul>
              {run.settings ? (
                <p className="text-sm text-muted-foreground">
                  {run.settings.embeddingModel} · RRF k {run.settings.rrfK} ·{' '}
                  {run.settings.candidates} semantic and {run.settings.keywordCandidates} keyword
                  candidates · trigram threshold {run.settings.trigramThreshold}
                </p>
              ) : null}
            </Section>
          ) : null}
          <Section title="Cases">
            <EvalCaseTable cases={run.cases} />
          </Section>
        </>
      )}
    </div>
  )
}
