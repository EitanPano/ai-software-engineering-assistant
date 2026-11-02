import { describe, expect, it } from 'vitest'

import {
  REFRESH_MS,
  errorReason,
  isActive,
  refreshInterval,
  repositoryName,
  statusLabel,
  statusTone,
  type Source,
} from '@/entity/source/model'
import { CONNECT_COPY, connectSchema, toConnectBody } from '@/feature/connect/model'

const source = (over: Partial<Source> = {}): Source => ({
  id: 's1',
  url: 'https://github.com/octocat/Hello-World',
  ref: 'master',
  status: 'ready',
  errorCode: null,
  indexedCommit: 'abc123',
  documentCount: 2,
  chunkCount: 9,
  createdAt: '2026-10-31T10:00:00Z',
  updatedAt: '2026-10-31T10:01:00Z',
  ...over,
})

describe('the source entity', () => {
  it('names every status in words, each with a tone', () => {
    expect(statusLabel('queued')).toBe('Queued')
    expect(statusLabel('indexing')).toBe('Indexing')
    expect(statusLabel('ready')).toBe('Ready')
    expect(statusLabel('failed')).toBe('Failed')
    expect(statusTone('ready')).toBe('success')
    expect(statusTone('failed')).toBe('destructive')
    expect(statusTone('queued')).toBe('muted')
    expect(statusTone('indexing')).toBe('info')
  })

  it('says why a source failed in our words, and nothing for one that did not', () => {
    expect(errorReason('repository_too_large')).toMatch(/too large/i)
    expect(errorReason('embedding_unavailable')).toMatch(/embedding service/i)
    expect(errorReason('interrupted')).toMatch(/interrupted/i)
    expect(errorReason('internal')).toMatch(/went wrong/i)
    expect(errorReason('repository_unavailable')).toMatch(/download/i)
    expect(errorReason(null)).toBeNull()
  })

  it('shows the owner and repository of the url', () => {
    expect(repositoryName('https://github.com/octocat/Hello-World')).toBe('octocat/Hello-World')
    expect(repositoryName('not a url')).toBe('not a url')
  })

  it('treats queued and indexing as active', () => {
    expect(isActive(source({ status: 'queued' }))).toBe(true)
    expect(isActive(source({ status: 'indexing' }))).toBe(true)
    expect(isActive(source({ status: 'ready' }))).toBe(false)
    expect(isActive(source({ status: 'failed' }))).toBe(false)
  })

  it('refreshes every 3 s while a loaded row is active, and stops otherwise', () => {
    const page = (...items: Source[]) => ({ items, nextCursor: null })
    expect(REFRESH_MS).toBe(3000)
    expect(refreshInterval(undefined)).toBe(false)
    expect(refreshInterval({ pages: [page(source())] })).toBe(false)
    expect(refreshInterval({ pages: [page(source()), page(source({ status: 'queued' }))] })).toBe(
      REFRESH_MS,
    )
  })
})

describe('the connect form', () => {
  it('accepts the exact url form with and without a ref', () => {
    expect(
      connectSchema.safeParse({ url: 'https://github.com/octocat/Hello-World', ref: '' }).success,
    ).toBe(true)
    expect(
      connectSchema.safeParse({ url: 'https://github.com/octocat/Hello-World', ref: 'v1.0/x' })
        .success,
    ).toBe(true)
  })

  it.each([
    'http://github.com/octocat/Hello-World',
    'https://example.com/octocat/Hello-World',
    'https://github.com/octocat/Hello-World/',
    'https://github.com/octocat',
    '',
  ])('refuses %j in our words', (url) => {
    const result = connectSchema.safeParse({ url, ref: '' })
    expect(result.success).toBe(false)
    expect(result.error?.issues[0]?.message).toBe(
      'Enter the repository as https://github.com/owner/repository',
    )
  })

  it('refuses a malformed ref in our words', () => {
    const result = connectSchema.safeParse({
      url: 'https://github.com/octocat/Hello-World',
      ref: '-bad',
    })
    expect(result.success).toBe(false)
    expect(result.error?.issues[0]?.message).toBe(
      'Use a branch, tag or commit: letters, digits, dots, slashes, dashes or underscores',
    )
  })

  it('builds the body without an empty ref and with trimmed text', () => {
    expect(toConnectBody({ url: ' https://github.com/a/b ', ref: '  ' })).toEqual({
      url: 'https://github.com/a/b',
    })
    expect(toConnectBody({ url: 'https://github.com/a/b', ref: ' dev ' })).toEqual({
      url: 'https://github.com/a/b',
      ref: 'dev',
    })
  })

  it('words the server outcomes itself', () => {
    expect(CONNECT_COPY.not_found).toMatch(/public repository/i)
    expect(CONNECT_COPY.conflict).toMatch(/already connected/i)
    expect(CONNECT_COPY.upstream_unavailable).toMatch(/GitHub/)
    expect(CONNECT_COPY['validation_failed:url']).toBeDefined()
    expect(CONNECT_COPY['validation_failed:ref']).toBeDefined()
  })
})
