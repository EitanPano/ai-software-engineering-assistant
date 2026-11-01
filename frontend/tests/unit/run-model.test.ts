import { describe, expect, it } from 'vitest'

import type { RunEvent } from '@/shared/api'
import { RUN_ERROR_COPY, applyRunEvent, initialRunView, runErrorCopy } from '@/entity/run/model'

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
