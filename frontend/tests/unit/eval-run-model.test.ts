import { describe, expect, it } from 'vitest'

import {
  REFRESH_MS,
  errorReason,
  formatCosine,
  formatScore,
  isActive,
  kindLabel,
  listRefreshInterval,
  runRefreshInterval,
  searchLabel,
  skipReasonLabel,
  statusLabel,
  statusTone,
  type EvalRun,
} from '@/entity/eval-run/model'
import { MEASURE_COPY } from '@/feature/measure/model'

const run = (over: Partial<EvalRun> = {}): EvalRun => ({
  id: 'r1',
  status: 'completed',
  errorCode: null,
  caseCount: 30,
  skippedCaseCount: 0,
  incompleteCaseCount: 0,
  headline: null,
  createdAt: '2026-10-31T10:00:00Z',
  updatedAt: '2026-10-31T10:01:00Z',
  ...over,
})

describe('the eval-run entity', () => {
  it('names every status in words, each with a tone', () => {
    expect(statusLabel('queued')).toBe('Queued')
    expect(statusLabel('running')).toBe('Running')
    expect(statusLabel('completed')).toBe('Completed')
    expect(statusLabel('failed')).toBe('Failed')
    expect(statusTone('queued')).toBe('muted')
    expect(statusTone('running')).toBe('info')
    expect(statusTone('completed')).toBe('success')
    expect(statusTone('failed')).toBe('destructive')
  })

  it('gives each failure reason in our words, and none for a run that did not fail', () => {
    for (const code of [
      'no_runnable_case',
      'search_unavailable',
      'interrupted',
      'internal',
    ] as const) {
      expect(errorReason(code)).toMatch(/\.$/)
    }
    expect(errorReason(null)).toBeNull()
    expect(errorReason('search_unavailable')).not.toMatch(/voyage/i)
  })

  it('is active while queued or running only', () => {
    expect(isActive(run({ status: 'queued' }))).toBe(true)
    expect(isActive(run({ status: 'running' }))).toBe(true)
    expect(isActive(run({ status: 'completed' }))).toBe(false)
    expect(isActive(run({ status: 'failed' }))).toBe(false)
  })

  it('polls a list while any loaded run is active, and a run while it is active', () => {
    const page = (items: EvalRun[]) => ({ pages: [{ items, nextCursor: null }] })
    expect(listRefreshInterval(page([run(), run({ status: 'running' })]))).toBe(REFRESH_MS)
    expect(listRefreshInterval(page([run(), run({ status: 'failed' })]))).toBe(false)
    expect(listRefreshInterval(page([]))).toBe(false)
    expect(listRefreshInterval(undefined)).toBe(false)
    expect(runRefreshInterval(run({ status: 'queued' }))).toBe(REFRESH_MS)
    expect(runRefreshInterval(run())).toBe(false)
    expect(runRefreshInterval(undefined)).toBe(false)
  })

  it('formats a score to two places, a cosine to three, and null as a dash', () => {
    expect(formatScore(1)).toBe('1.00')
    expect(formatScore(0.8333)).toBe('0.83')
    expect(formatScore(0)).toBe('0.00')
    expect(formatScore(null)).toBe('–')
    expect(formatCosine(0.2436)).toBe('0.244')
    expect(formatCosine(null)).toBe('–')
  })

  it('labels searches, kinds and skip reasons in words', () => {
    expect(searchLabel('hybrid')).toBe('Hybrid')
    expect(searchLabel('semantic')).toBe('Semantic')
    expect(searchLabel('keyword')).toBe('Keyword')
    expect(kindLabel('all')).toBe('All')
    expect(kindLabel('identifier')).toBe('Identifier')
    expect(kindLabel('paraphrase')).toBe('Paraphrase')
    expect(kindLabel('no_answer')).toBe('No answer')
    expect(skipReasonLabel('source_missing')).toMatch(/source/i)
    expect(skipReasonLabel('expected_chunk_missing')).toMatch(/chunk/i)
    expect(skipReasonLabel(null)).toBeNull()
  })
})

describe('the measure feature copy', () => {
  it('words a run already active as a wait, and keeps the server text out', () => {
    expect(MEASURE_COPY.conflict).toMatch(/already/i)
    expect(MEASURE_COPY.forbidden).toBeDefined()
    for (const text of Object.values(MEASURE_COPY)) expect(text).not.toMatch(/hunter2/)
  })
})
