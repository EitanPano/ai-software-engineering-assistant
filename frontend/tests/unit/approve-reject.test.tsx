import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { APPROVE_COPY } from '@/feature/approve/model'
import { ApproveButton } from '@/feature/approve/ui/approve-button'
import { REJECT_COPY } from '@/feature/reject/model'
import { RejectButton } from '@/feature/reject/ui/reject-button'

import { envelope, renderApp, stubApi } from './support'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const { toast } = await import('sonner')

const DIGEST = 'b'.repeat(64)
const DECIDED = (decision: 'approved' | 'rejected') =>
  Response.json({
    id: 'a1',
    toolUseId: 't1',
    decision,
    decidedAt: '2026-11-01T10:00:00Z',
  })

const cases = [
  { name: 'Approve call', decision: 'approved', Button: ApproveButton, copy: APPROVE_COPY },
  { name: 'Reject call', decision: 'rejected', Button: RejectButton, copy: REJECT_COPY },
] as const

describe.each(cases)('$name', ({ name, decision, Button, copy }) => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => vi.unstubAllGlobals())

  function setup() {
    const onStart = vi.fn()
    const onDone = vi.fn()
    renderApp(<Button approvalId="a1" argumentsDigest={DIGEST} onStart={onStart} onDone={onDone} />)
    return { onStart, onDone }
  }

  it('posts the decision with the digest it was shown and reports it decided', async () => {
    const fetchMock = stubApi({ 'POST /api/approval/a1/decision': DECIDED(decision) })
    const { onStart, onDone } = setup()

    await userEvent.click(screen.getByRole('button', { name }))

    await waitFor(() => {
      expect(onDone).toHaveBeenCalledWith('decided')
    })
    expect(onStart).toHaveBeenCalledTimes(1)
    const request = fetchMock.mock.calls[0]?.[0]
    expect(new URL(request?.url ?? '').pathname).toBe('/api/approval/a1/decision')
    expect(await request?.json()).toEqual({ decision, argumentsDigest: DIGEST })
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('sends nothing until clicked', () => {
    const fetchMock = stubApi({ 'POST /api/approval/a1/decision': DECIDED(decision) })
    setup()

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('tells a stale decision in our words and still reports it, so the stream catches up', async () => {
    stubApi({ 'POST /api/approval/a1/decision': envelope('conflict', 409) })
    const { onDone } = setup()

    await userEvent.click(screen.getByRole('button', { name }))

    await waitFor(() => {
      expect(onDone).toHaveBeenCalledWith('stale')
    })
    expect(toast.error).toHaveBeenCalledWith(copy.conflict)
    expect(copy.conflict).not.toContain('hunter2')
  })

  it('toasts any other failure, keeps the choice open and sends no second request', async () => {
    const fetchMock = stubApi({ 'POST /api/approval/a1/decision': envelope('internal', 500) })
    const { onDone } = setup()

    await userEvent.click(screen.getByRole('button', { name }))

    await waitFor(() => {
      expect(onDone).toHaveBeenCalledWith('failed')
    })
    expect(toast.error).toHaveBeenCalledWith(copy.internal)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('is off while the other decision is in flight', () => {
    renderApp(
      <Button
        approvalId="a1"
        argumentsDigest={DIGEST}
        disabled
        onStart={vi.fn()}
        onDone={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name })).toBeDisabled()
  })
})
