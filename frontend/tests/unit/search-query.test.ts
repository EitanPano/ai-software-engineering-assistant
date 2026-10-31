import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { dropFailedSearch, searchKey } from '@/entity/chunk/api/chunk'

const newClient = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })
const cached = (client: QueryClient, q: string) =>
  client.getQueryCache().find({ queryKey: searchKey(q) })

// Fails the search for `q` with an error of its own and returns it, as the wait state holds the
// error its page threw. Asked again, the same query fails with a new error object.
const fail = async (client: QueryClient, q: string) => {
  const error = new Error('refused')
  await client
    .query({ queryKey: searchKey(q), queryFn: () => Promise.reject(error) })
    .catch(() => undefined)
  return error
}

describe('dropFailedSearch', () => {
  it('drops the search that failed, so the same text is asked again', async () => {
    const client = newClient()
    const error = await fail(client, 'alpha')
    expect(cached(client, 'alpha')?.state.status).toBe('error')

    dropFailedSearch(client, 'alpha', error)

    expect(cached(client, 'alpha')).toBeUndefined()
  })

  it('keeps a newer failure of the same text, as the retry has just been refused again', async () => {
    const client = newClient()
    const older = await fail(client, 'alpha')
    const newer = await fail(client, 'alpha')
    expect(newer).not.toBe(older)
    expect(cached(client, 'alpha')?.state.error).toBe(newer)

    dropFailedSearch(client, 'alpha', older)

    expect(cached(client, 'alpha')?.state.error).toBe(newer)
  })

  it('keeps a result it holds', async () => {
    const client = newClient()
    await client.query({ queryKey: searchKey('alpha'), queryFn: () => ({ items: [] }) })

    dropFailedSearch(client, 'alpha', new Error('refused'))

    expect(cached(client, 'alpha')?.state.status).toBe('success')
  })

  it('keeps another text, failed or not', async () => {
    const client = newClient()
    // The error is beta's own, so only the key tells the two texts apart.
    const error = await fail(client, 'beta')

    dropFailedSearch(client, 'alpha', error)

    expect(cached(client, 'beta')?.state.status).toBe('error')
  })

  it('keeps a search that is being asked, as the retry starts it', () => {
    const client = newClient()
    void client
      .query({ queryKey: searchKey('alpha'), queryFn: () => new Promise<never>(() => undefined) })
      .catch(() => undefined)
    expect(cached(client, 'alpha')?.state.status).toBe('pending')

    dropFailedSearch(client, 'alpha', new Error('refused'))

    expect(cached(client, 'alpha')?.state.fetchStatus).toBe('fetching')
  })
})
