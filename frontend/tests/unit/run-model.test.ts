import { describe, expect, it } from 'vitest'

import type { RunEvent } from '@/shared/api'
import {
  RUN_ERROR_COPY,
  TOOL_STATUS_LABEL,
  applyRunEvent,
  initialRunView,
  isActiveRun,
  isAwaitingApproval,
  runErrorCopy,
} from '@/entity/run/model'

const at = '2026-10-30T10:00:00Z'
const started = (sequence: number): RunEvent => ({ type: 'run_started', sequence, createdAt: at })
const delta = (sequence: number, text: string): RunEvent => ({
  type: 'text_delta',
  sequence,
  createdAt: at,
  text,
})
const toolStarted = (sequence: number, toolUseId = 't1'): RunEvent => ({
  type: 'tool_call_started',
  sequence,
  createdAt: at,
  toolUseId,
  name: 'search',
  input: { q: 'x' },
})
const toolFinished = (
  sequence: number,
  status: 'succeeded' | 'failed' | 'denied',
  toolUseId = 't1',
): RunEvent => ({
  type: 'tool_call_finished',
  sequence,
  createdAt: at,
  toolUseId,
  status,
  output: 'out',
})

const fold = (events: RunEvent[]) => events.reduce(applyRunEvent, initialRunView)

describe('applyRunEvent', () => {
  it('joins text deltas into one block', () => {
    const view = fold([started(1), delta(2, 'Hel'), delta(3, 'lo')])

    expect(view.blocks).toEqual([{ kind: 'text', text: 'Hello' }])
    expect(view.lastSequence).toBe(3)
    expect(view.finished).toBeNull()
  })

  it('ignores a sequence it has already seen, so a replay renders each event once', () => {
    const view = fold([
      started(1),
      delta(2, 'Hel'),
      delta(3, 'lo'),
      delta(2, 'Hel'),
      delta(3, 'lo'),
    ])

    expect(view.blocks).toEqual([{ kind: 'text', text: 'Hello' }])
  })

  it('accepts a first event with sequence 0', () => {
    expect(fold([started(0), delta(1, 'a')]).blocks).toEqual([{ kind: 'text', text: 'a' }])
  })

  it('shows a tool call running, then with its result, in place between text', () => {
    const running = fold([delta(1, 'Let me look. '), toolStarted(2)])
    expect(running.blocks).toEqual([
      { kind: 'text', text: 'Let me look. ' },
      { kind: 'tool', toolUseId: 't1', name: 'search', input: { q: 'x' }, status: 'running' },
    ])

    const done = [toolFinished(3, 'denied'), delta(4, 'Done.')].reduce(applyRunEvent, running)
    expect(done.blocks).toEqual([
      { kind: 'text', text: 'Let me look. ' },
      {
        kind: 'tool',
        toolUseId: 't1',
        name: 'search',
        input: { q: 'x' },
        status: 'denied',
        output: 'out',
      },
      { kind: 'text', text: 'Done.' },
    ])
  })

  it('keeps parallel tool calls apart by id', () => {
    const view = fold([
      toolStarted(1, 'a'),
      toolStarted(2, 'b'),
      toolFinished(3, 'failed', 'b'),
      toolFinished(4, 'succeeded', 'a'),
    ])

    expect(view.blocks.map((block) => block.kind === 'tool' && block.status)).toEqual([
      'succeeded',
      'failed',
    ])
  })

  it('ignores a result for a tool call it never saw', () => {
    expect(fold([toolFinished(1, 'succeeded', 'nope')]).blocks).toEqual([])
  })

  it('shows a down server as a notice in place, and the run goes on', () => {
    const down: RunEvent = {
      type: 'mcp_server_unavailable',
      sequence: 2,
      createdAt: at,
      name: 'knowledge',
    }
    const view = fold([delta(1, 'Hi. '), down, delta(3, 'Still here.')])

    expect(view.blocks).toEqual([
      { kind: 'text', text: 'Hi. ' },
      { kind: 'notice', name: 'knowledge' },
      { kind: 'text', text: 'Still here.' },
    ])
    expect(view.finished).toBeNull()
  })

  it('shows the same notice once when the event is replayed', () => {
    const down: RunEvent = {
      type: 'mcp_server_unavailable',
      sequence: 1,
      createdAt: at,
      name: 'knowledge',
    }

    expect(fold([down, down]).blocks).toEqual([{ kind: 'notice', name: 'knowledge' }])
  })

  it('records how the run finished', () => {
    const view = fold([
      started(1),
      { type: 'run_finished', sequence: 2, createdAt: at, status: 'failed', errorCode: 'refused' },
    ])

    expect(view.finished).toEqual({ status: 'failed', errorCode: 'refused' })
  })
})

describe('runErrorCopy', () => {
  it('has our own words for every error code', () => {
    for (const code of [
      'refused',
      'truncated',
      'turn_limit',
      'upstream_unavailable',
      'interrupted',
      'internal',
    ] as const) {
      expect(RUN_ERROR_COPY[code]).toBeTruthy()
      expect(runErrorCopy(code)).toBe(RUN_ERROR_COPY[code])
    }
  })

  it('falls back to a generic line for a missing or unknown code', () => {
    expect(runErrorCopy(null)).toBe(RUN_ERROR_COPY.internal)
    expect(runErrorCopy('brand_new' as never)).toBe(RUN_ERROR_COPY.internal)
  })
})

const DIGEST = 'a'.repeat(64)
const requested = (sequence: number, toolUseId = 't1'): RunEvent => ({
  type: 'approval_requested',
  sequence,
  createdAt: at,
  approvalId: 'a1',
  toolUseId,
  argumentsDigest: DIGEST,
})
const decided = (
  sequence: number,
  decision: 'approved' | 'rejected',
  toolUseId = 't1',
): RunEvent => ({
  type: 'approval_decided',
  sequence,
  createdAt: at,
  approvalId: 'a1',
  toolUseId,
  decision,
})

describe('approval events', () => {
  it('puts the call in the waiting status with what the decision must echo', () => {
    const view = fold([started(1), toolStarted(2), requested(3)])

    expect(view.blocks).toEqual([
      expect.objectContaining({
        kind: 'tool',
        status: 'awaiting_approval',
        approval: { approvalId: 'a1', argumentsDigest: DIGEST },
      }),
    ])
    expect(isAwaitingApproval(view)).toBe(true)
  })

  it('marks an approved call approved, not running, and drops the approval', () => {
    const view = fold([started(1), toolStarted(2), requested(3), decided(4, 'approved')])

    expect(view.blocks[0]).toEqual(expect.objectContaining({ status: 'approved' }))
    expect(view.blocks[0]).not.toHaveProperty('approval')
    expect(isAwaitingApproval(view)).toBe(false)
  })

  it('shows each decision at once while another call of the pause still waits', () => {
    const waitingTwo = [
      toolStarted(1, 't1'),
      toolStarted(2, 't2'),
      requested(3, 't1'),
      requested(4, 't2'),
    ]

    const rejected = fold([...waitingTwo, decided(5, 'rejected', 't1')])
    expect(rejected.blocks.map((block) => block.kind === 'tool' && block.status)).toEqual([
      'denied',
      'awaiting_approval',
    ])

    const approved = fold([...waitingTwo, decided(5, 'approved', 't1')])
    expect(approved.blocks.map((block) => block.kind === 'tool' && block.status)).toEqual([
      'approved',
      'awaiting_approval',
    ])
    expect(TOOL_STATUS_LABEL.approved).toBe('Approved')
  })

  it('lets tool_call_finished end an approved call', () => {
    const view = fold([
      toolStarted(1),
      requested(2),
      decided(3, 'approved'),
      toolFinished(4, 'succeeded'),
    ])

    expect(view.blocks[0]).toEqual(expect.objectContaining({ status: 'succeeded' }))
  })

  it('ends a rejected call as denied, with the output the server gave', () => {
    const view = fold([
      started(1),
      toolStarted(2),
      requested(3),
      decided(4, 'rejected'),
      toolFinished(5, 'denied'),
    ])

    expect(view.blocks[0]).toEqual(expect.objectContaining({ status: 'denied', output: 'out' }))
    expect(view.blocks[0]).not.toHaveProperty('approval')
    expect(isAwaitingApproval(view)).toBe(false)
  })

  it('waits on one call while another is decided', () => {
    const view = fold([
      toolStarted(1, 't1'),
      toolStarted(2, 't2'),
      requested(3, 't1'),
      requested(4, 't2'),
      decided(5, 'approved', 't1'),
    ])

    expect(isAwaitingApproval(view)).toBe(true)
  })

  it('ignores an approval event it has seen, and one for an unknown call', () => {
    const view = fold([toolStarted(1), requested(2), requested(2), requested(3, 'nope')])

    expect(view.blocks).toHaveLength(1)
    expect(view.lastSequence).toBe(3)
  })

  it('words the waiting status and counts it as an active run', () => {
    expect(TOOL_STATUS_LABEL.awaiting_approval).toBe('Needs approval')
    expect(isActiveRun({ status: 'awaiting_approval' })).toBe(true)
    expect(isActiveRun({ status: 'completed' })).toBe(false)
    expect(isAwaitingApproval(initialRunView)).toBe(false)
  })
})
