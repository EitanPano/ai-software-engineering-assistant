import { describe, expect, it } from 'vitest'

import {
  caseCountLabel,
  errorReason,
  formatCosine,
  formatScore,
  listRefreshInterval,
  runRefreshInterval,
  skipReasonLabel,
} from '@/entity/eval-run/model'

describe('eval run model, boundaries', () => {
  it('shows a zero score as 0.00 and only a missing one as a dash', () => {
    expect(formatScore(0)).toBe('0.00')
    expect(formatCosine(0)).toBe('0.000')
    expect(formatScore(null)).toBe('–')
    expect(formatCosine(null)).toBe('–')
  })

  it('never polls an empty list or a missing run', () => {
    expect(listRefreshInterval(undefined)).toBe(false)
    expect(listRefreshInterval({ pages: [] })).toBe(false)
    expect(listRefreshInterval({ pages: [{ items: [], nextCursor: null }] })).toBe(false)
    expect(runRefreshInterval(undefined)).toBe(false)
  })

  it('has no reason for a run or case that carries none', () => {
    expect(errorReason(null)).toBeNull()
    expect(skipReasonLabel(null)).toBeNull()
  })

  it('counts zero and one case in the right number', () => {
    expect(caseCountLabel(0)).toBe('0 cases')
    expect(caseCountLabel(1)).toBe('1 case')
  })
})
