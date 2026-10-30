import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  SEND_MESSAGE_COPY,
  sendMessageSchema,
  type SentMessage,
} from '@/feature/send-message/model'
import { SendMessageForm } from '@/feature/send-message/ui/send-message-form'

import { envelope, renderApp, stubApi } from './support'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const { toast } = await import('sonner')

const SENT = {
  message: {
    id: 'm1',
    role: 'user',
    text: 'Hello',
    runId: 'r1',
    createdAt: '2026-10-30T10:00:00Z',
  },
  run: { id: 'r1', status: 'queued', errorCode: null, createdAt: '2026-10-30T10:00:00Z' },
}

async function send(text: string) {
  if (text) await userEvent.type(screen.getByLabelText('Message'), text)
  await userEvent.click(screen.getByRole('button', { name: 'Send message' }))
}

describe('sendMessageSchema', () => {
  it('takes the limits from the contract and rejects blank text', () => {
    expect(sendMessageSchema.safeParse({ content: 'hi' }).success).toBe(true)
    expect(sendMessageSchema.safeParse({ content: '   ' }).success).toBe(false)
    expect(sendMessageSchema.safeParse({ content: 'x'.repeat(32_001) }).success).toBe(false)
    expect(sendMessageSchema.safeParse({ content: 'x'.repeat(32_000) }).success).toBe(true)
  })

  it('has copy for a send during a run and for the rate limit', () => {
    expect(SEND_MESSAGE_COPY.conflict).toBeTruthy()
    expect(SEND_MESSAGE_COPY.rate_limited).toBeTruthy()
  })
})

describe('SendMessageForm', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => vi.unstubAllGlobals())

  it('posts the message, hands the run to the caller and clears the box', async () => {
    const fetchMock = stubApi({
      'POST /api/conversation/c1/message': Response.json(SENT, { status: 201 }),
    })
    const onSent = vi.fn<(sent: SentMessage) => void>()
    renderApp(<SendMessageForm conversationId="c1" onSent={onSent} />)

    await send('Hello')

    await waitFor(() => {
      expect(onSent).toHaveBeenCalledTimes(1)
    })
    expect(onSent.mock.calls[0]?.[0].run.id).toBe('r1')
    expect(await (fetchMock.mock.calls[0]?.[0] as Request).json()).toEqual({ content: 'Hello' })
    expect(screen.getByLabelText('Message')).toHaveValue('')
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('shows an empty message on the field and sends nothing', async () => {
    const fetchMock = stubApi({})
    renderApp(<SendMessageForm conversationId="c1" onSent={vi.fn()} />)

    await send('')

    expect(await screen.findByText('Enter a message')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('tells the person a reply is still being written on a 409, and keeps their text', async () => {
    stubApi({ 'POST /api/conversation/c1/message': envelope('conflict', 409) })
    const onSent = vi.fn()
    renderApp(<SendMessageForm conversationId="c1" onSent={onSent} />)

    await send('Hello')

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(SEND_MESSAGE_COPY.conflict)
    })
    expect(onSent).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Message')).toHaveValue('Hello')
    expect(screen.queryByText(/hunter2/)).not.toBeInTheDocument()
  })

  it('tells the person to wait on a 429', async () => {
    stubApi({ 'POST /api/conversation/c1/message': envelope('rate_limited', 429) })
    renderApp(<SendMessageForm conversationId="c1" onSent={vi.fn()} />)

    await send('Hello')

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(SEND_MESSAGE_COPY.rate_limited)
    })
  })

  it('says it cannot reach the server when the network fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('failed'))),
    )
    renderApp(<SendMessageForm conversationId="c1" onSent={vi.fn()} />)

    await send('Hello')

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Can't reach the server"))
    })
  })

  it('keeps the send button off while a run is writing, and the box usable', () => {
    stubApi({})
    renderApp(<SendMessageForm conversationId="c1" busy onSent={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
    expect(screen.getByLabelText('Message')).toBeEnabled()
  })
})
