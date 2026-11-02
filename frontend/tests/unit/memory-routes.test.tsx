import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderRoutes } from './render-routes'
import { USER, envelope, stubApi } from './support'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const { toast } = await import('sonner')

const at = '2026-10-30T10:00:00Z'
const memory = (id: string, content: string, conversationId = 'c1') => ({
  id,
  content,
  conversationId,
  createdAt: at,
})
const page = (items: unknown[], nextCursor: string | null = null) =>
  Response.json({ items, nextCursor })

const ME = { 'GET /api/user/me': Response.json(USER) }

beforeEach(() => vi.clearAllMocks())
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the memory route', () => {
  it('sends a visitor to sign in', async () => {
    stubApi({ 'GET /api/user/me': envelope('unauthenticated', 401) })

    const router = renderRoutes('/memory')

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/sign-in')
    })
  })

  it('shows the empty state with a link to the conversations', async () => {
    stubApi({ ...ME, 'GET /api/memory': page([]) })

    renderRoutes('/memory')

    expect(await screen.findByRole('heading', { level: 1, name: 'Memory' })).toBeVisible()
    expect(await screen.findByText('Nothing remembered yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to conversations' })).toHaveAttribute(
      'href',
      '/conversation',
    )
  })

  it('lists each memory as plain text with a link to its conversation', async () => {
    stubApi({
      ...ME,
      'GET /api/memory': page([
        memory('m1', 'I keep deploy notes in <b>ops/RUNBOOK.md</b>', 'c9'),
        memory('m2', 'I use Bun.'),
      ]),
    })

    renderRoutes('/memory')

    expect(
      await screen.findByText('I keep deploy notes in <b>ops/RUNBOOK.md</b>'),
    ).toBeInTheDocument()
    expect(screen.getByText('I use Bun.')).toBeInTheDocument()
    expect(document.querySelector('b')).toBeNull()
    expect(screen.getAllByRole('link', { name: 'Conversation' })[0]).toHaveAttribute(
      'href',
      '/conversation/c9',
    )
  })

  it('shows bidi and tag characters as [U+XXXX] instead of obeying them', async () => {
    stubApi({ ...ME, 'GET /api/memory': page([memory('m1', 'a‮b\u{E0041}c')]) })

    renderRoutes('/memory')

    expect(await screen.findByText('a[U+202E]b[U+E0041]c')).toBeInTheDocument()
  })

  it('loads older memories behind Show more', async () => {
    const fetchMock = stubApi({ ...ME, 'GET /api/memory': page([memory('m1', 'First')], 'next') })

    renderRoutes('/memory')
    await screen.findByText('First')
    expect(fetchMock).toHaveBeenCalled()

    stubApi({ ...ME, 'GET /api/memory': page([memory('m2', 'Second')]) })
    await userEvent.click(screen.getByRole('button', { name: 'Show more' }))

    expect(await screen.findByText('Second')).toBeInTheDocument()
    expect(screen.getByText('First')).toBeInTheDocument()
  })

  it('shows the group error state when the list cannot be read', async () => {
    stubApi({ ...ME, 'GET /api/memory': envelope('internal', 500) })

    renderRoutes('/memory')

    expect(await screen.findByRole('button', { name: /try again/i })).toBeInTheDocument()
  })
})

describe('deleting a memory', () => {
  async function openDialog() {
    const row = (await screen.findByText('I use Bun.')).closest('li') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: 'Delete memory' }))
    return screen.findByRole('dialog', { name: 'Delete this memory?' })
  }

  it('says recall stops at once and a conversation that read it keeps it, with Cancel focused', async () => {
    stubApi({ ...ME, 'GET /api/memory': page([memory('m1', 'I use Bun.')]) })
    renderRoutes('/memory')

    const dialog = await openDialog()

    expect(dialog).toHaveTextContent(/no conversation will recall it/i)
    expect(dialog).toHaveTextContent(/already read it keeps it/i)
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
  })

  it('cancels without calling the API', async () => {
    const fetchMock = stubApi({ ...ME, 'GET /api/memory': page([memory('m1', 'I use Bun.')]) })
    renderRoutes('/memory')
    const dialog = await openDialog()

    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    expect(fetchMock.mock.calls.some(([request]) => request.method === 'DELETE')).toBe(false)
    expect(screen.getByText('I use Bun.')).toBeInTheDocument()
  })

  it('deletes, then the row is gone', async () => {
    let deleted = false
    const fetchMock = stubApi({
      ...ME,
      'GET /api/memory': () =>
        deleted ? page([memory('m2', 'Other fact.')]) : page([memory('m1', 'I use Bun.')]),
      'DELETE /api/memory/m1': () => {
        deleted = true
        return new Response(null, { status: 204 })
      },
    })
    renderRoutes('/memory')
    const dialog = await openDialog()

    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete memory' }))

    await waitFor(() => {
      expect(screen.queryByText('I use Bun.')).not.toBeInTheDocument()
    })
    expect(screen.getByText('Other fact.')).toBeInTheDocument()
    expect(toast.success).toHaveBeenCalledWith('Memory deleted')
    expect(fetchMock.mock.calls.some(([r]) => r.method === 'DELETE')).toBe(true)
  })

  it('keeps the row and toasts our words when the delete fails', async () => {
    stubApi({
      ...ME,
      'GET /api/memory': page([memory('m1', 'I use Bun.')]),
      'DELETE /api/memory/m1': envelope('internal', 500),
    })
    renderRoutes('/memory')
    const dialog = await openDialog()

    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete memory' }))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalled()
    })
    expect(vi.mocked(toast.error).mock.calls[0]?.[0]).not.toMatch(/hunter2/)
    expect(screen.getByText('I use Bun.')).toBeInTheDocument()
  })

  it('says the memory is gone when it was already deleted', async () => {
    let deleted = false
    stubApi({
      ...ME,
      'GET /api/memory': () => (deleted ? page([]) : page([memory('m1', 'I use Bun.')])),
      'DELETE /api/memory/m1': () => {
        deleted = true
        return envelope('not_found', 404)
      },
    })
    renderRoutes('/memory')
    const dialog = await openDialog()

    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete memory' }))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("This memory isn't there any more.")
    })
    await waitFor(() => {
      expect(screen.queryByText('I use Bun.')).not.toBeInTheDocument()
    })
  })
})
