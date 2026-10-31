import type { Source, SourcePage } from '@/shared/api'

export type { Source, SourcePage }

type Status = Source['status']
type ErrorCode = NonNullable<Source['errorCode']>
export type StatusTone = 'success' | 'destructive' | 'muted' | 'info'

const STATUS_LABEL: Record<Status, string> = {
  queued: 'Queued',
  indexing: 'Indexing',
  ready: 'Ready',
  failed: 'Failed',
}

const STATUS_TONE: Record<Status, StatusTone> = {
  queued: 'muted',
  indexing: 'info',
  ready: 'success',
  failed: 'destructive',
}

// Why a source failed, in our words, keyed by the API's `errorCode`. The server's text is never
// shown.
const ERROR_REASON: Record<ErrorCode, string> = {
  repository_unavailable: "We couldn't download the repository from GitHub. Retry in a moment.",
  repository_too_large: 'The repository is too large to index.',
  embedding_unavailable: 'The embedding service was unavailable. Retry in a moment.',
  interrupted: 'Indexing was interrupted. Retry to index it again.',
  internal: 'Something went wrong while indexing. Retry to index it again.',
}

export const statusLabel = (status: Status): string => STATUS_LABEL[status]
export const statusTone = (status: Status): StatusTone => STATUS_TONE[status]
export const errorReason = (code: Source['errorCode']): string | null =>
  code === null ? null : ERROR_REASON[code]

// `owner/repository` from the canonical url; anything else is shown as given.
export function repositoryName(url: string): string {
  const match = /^https:\/\/github\.com\/([^/]+\/[^/]+)$/.exec(url)
  return match?.[1] ?? url
}

export const isActive = (source: Pick<Source, 'status'>): boolean =>
  source.status === 'queued' || source.status === 'indexing'

export const REFRESH_MS = 3000

// The list's `refetchInterval`: poll while any loaded row is still being indexed.
export function refreshInterval(data: { pages: SourcePage[] } | undefined): number | false {
  return data?.pages.some((page) => page.items.some(isActive)) ? REFRESH_MS : false
}
