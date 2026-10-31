import type { EvalCaseResult, EvalRun, EvalRunDetail, EvalRunPage, EvalScore } from '@/shared/api'

export type { EvalCaseResult, EvalRun, EvalRunDetail, EvalRunPage, EvalScore }

type Status = EvalRun['status']
type ErrorCode = NonNullable<EvalRun['errorCode']>
type SkipReason = NonNullable<EvalCaseResult['skipReason']>
export type StatusTone = 'success' | 'destructive' | 'muted' | 'info'

const STATUS_LABEL: Record<Status, string> = {
  queued: 'Queued',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
}

const STATUS_TONE: Record<Status, StatusTone> = {
  queued: 'muted',
  running: 'info',
  completed: 'success',
  failed: 'destructive',
}

// Why a run failed, in our words, keyed by the API's `errorCode`. The server's text is never
// shown, and a failed run is not re-run from here: the user starts a new one.
const ERROR_REASON: Record<ErrorCode, string> = {
  no_runnable_case:
    'No case could run. Connect the repository the cases are labelled for, then start a new run.',
  search_unavailable:
    'The search was unavailable, so the run stopped with no scores. Start a new run in a moment.',
  interrupted: 'The run was interrupted before it finished. Start a new run.',
  internal: 'Something went wrong during the run. Start a new run.',
}

const SKIP_REASON: Record<SkipReason, string> = {
  source_missing: 'Skipped: the source is not connected at the case’s commit.',
  expected_chunk_missing: 'Skipped: no indexed chunk matches the expected lines.',
}

const SEARCH_LABEL: Record<EvalScore['search'], string> = {
  hybrid: 'Hybrid',
  semantic: 'Semantic',
  keyword: 'Keyword',
}

const KIND_LABEL: Record<EvalScore['kind'] | EvalCaseResult['kind'], string> = {
  all: 'All',
  identifier: 'Identifier',
  paraphrase: 'Paraphrase',
  no_answer: 'No answer',
}

export const statusLabel = (status: Status): string => STATUS_LABEL[status]
export const statusTone = (status: Status): StatusTone => STATUS_TONE[status]
export const errorReason = (code: EvalRun['errorCode']): string | null =>
  code === null ? null : ERROR_REASON[code]
export const skipReasonLabel = (reason: EvalCaseResult['skipReason']): string | null =>
  reason === null ? null : SKIP_REASON[reason]
export const searchLabel = (search: EvalScore['search']): string => SEARCH_LABEL[search]
export const kindLabel = (kind: keyof typeof KIND_LABEL): string => KIND_LABEL[kind]

// A score is 0 to 1, shown to two places; a cosine to three, where the cutoff question lives. A
// missing number (a skipped case, no relevant hit) is a dash, never a zero.
export const formatScore = (value: number | null): string =>
  value === null ? '–' : value.toFixed(2)
export const formatCosine = (value: number | null): string =>
  value === null ? '–' : value.toFixed(3)

export const isActive = (run: Pick<EvalRun, 'status'>): boolean =>
  run.status === 'queued' || run.status === 'running'

export const REFRESH_MS = 3000

// The list's `refetchInterval`: poll while any loaded run is still going.
export function listRefreshInterval(data: { pages: EvalRunPage[] } | undefined): number | false {
  return data?.pages.some((page) => page.items.some(isActive)) ? REFRESH_MS : false
}

// One run's `refetchInterval`: poll until it settles.
export function runRefreshInterval(run: EvalRun | undefined): number | false {
  return run !== undefined && isActive(run) ? REFRESH_MS : false
}

const plural = (count: number, noun: string) => `${String(count)} ${noun}${count === 1 ? '' : 's'}`
export const caseCountLabel = (count: number): string => plural(count, 'case')
