import type { SearchHit } from '@/shared/api'

// One search hit as the API sends it; a test overrides what it asserts on.
export const hit = (over: Partial<SearchHit> = {}): SearchHit => ({
  chunkId: 'c1',
  sourceId: 's1',
  url: 'https://github.com/octocat/Hello-World',
  ref: 'main',
  path: 'src/limiter.py',
  symbol: 'check_limit',
  startLine: 10,
  endLine: 24,
  content: 'def check_limit(key):\n    return True',
  score: 0.03,
  semanticRank: 1,
  fullTextRank: 2,
  trigramRank: null,
  ...over,
})
