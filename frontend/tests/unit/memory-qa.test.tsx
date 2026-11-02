import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderRoutes } from './render-routes'
import { USER, stubApi } from './support'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the memory route under hostile data', () => {
  it('renders markup, a script tag and a very long unbroken word as inert text', async () => {
    const long = 'x'.repeat(600)
    stubApi({
      'GET /api/user/me': Response.json(USER),
      'GET /api/memory': Response.json({
        items: [
          {
            id: 'm1',
            content: '<img src=x onerror="alert(1)"><script>alert(2)</script>',
            conversationId: 'c1',
            createdAt: '2026-10-30T10:00:00Z',
          },
          { id: 'm2', content: long, conversationId: 'c2', createdAt: '2026-10-30T10:00:00Z' },
        ],
        nextCursor: null,
      }),
    })

    renderRoutes('/memory')

    expect(await screen.findByText(long)).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
    expect(document.querySelector('main script')).toBeNull()
    expect(screen.getAllByRole('button', { name: 'Delete memory' })).toHaveLength(2)
  })
})
