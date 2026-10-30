import type { Run, RunEvent } from '@/shared/api'

export type RunErrorCode = NonNullable<Run['errorCode']>
export type ToolStatus = 'running' | 'succeeded' | 'failed' | 'denied'

export type RunBlock =
  | { kind: 'text'; text: string }
  | {
      kind: 'tool'
      toolUseId: string
      name: string
      input: Record<string, unknown>
      status: ToolStatus
      output?: string
    }

// What the person sees of one run, built by folding its events in order. `lastSequence` is the
// highest sequence applied (-1 before any), so a replayed event is ignored and the stream can
// reopen with `Last-Event-ID`.
export type RunView = {
  lastSequence: number
  blocks: RunBlock[]
  finished: { status: 'completed' | 'failed'; errorCode: Run['errorCode'] } | null
}

export const initialRunView: RunView = { lastSequence: -1, blocks: [], finished: null }

export function applyRunEvent(view: RunView, event: RunEvent): RunView {
  if (event.sequence <= view.lastSequence) return view
  const next = { ...view, lastSequence: event.sequence }

  switch (event.type) {
    case 'text_delta': {
      const last = view.blocks.at(-1)
      if (last?.kind === 'text') {
        return {
          ...next,
          blocks: [...view.blocks.slice(0, -1), { kind: 'text', text: last.text + event.text }],
        }
      }
      return { ...next, blocks: [...view.blocks, { kind: 'text', text: event.text }] }
    }
    case 'tool_call_started':
      return {
        ...next,
        blocks: [
          ...view.blocks,
          {
            kind: 'tool',
            toolUseId: event.toolUseId,
            name: event.name,
            input: event.input,
            status: 'running',
          },
        ],
      }
    case 'tool_call_finished':
      return {
        ...next,
        blocks: view.blocks.map((block) =>
          block.kind === 'tool' && block.toolUseId === event.toolUseId
            ? { ...block, status: event.status, output: event.output }
            : block,
        ),
      }
    case 'run_finished':
      return { ...next, finished: { status: event.status, errorCode: event.errorCode } }
    default:
      return next
  }
}

// Our words for how a run ended, keyed by the run's `errorCode`; the server's text is never shown.
export const RUN_ERROR_COPY: Record<RunErrorCode, string> = {
  refused: 'The agent declined to answer this message. Rephrase it and try again.',
  truncated: 'The answer was cut off because it ran too long. Ask for a shorter one.',
  turn_limit: 'The agent used too many steps and stopped. Try a narrower question.',
  upstream_unavailable: 'The model service is unavailable right now. Send your message again.',
  interrupted: 'This run was interrupted before it finished. Send your message again.',
  internal: 'Something went wrong while writing the answer. Send your message again.',
}

export function runErrorCopy(code: Run['errorCode']): string {
  return (code === null ? undefined : RUN_ERROR_COPY[code]) ?? RUN_ERROR_COPY.internal
}

export const isActiveRun = (run: Pick<Run, 'status'> | null | undefined): boolean =>
  run?.status === 'queued' || run?.status === 'running'

export const TOOL_STATUS_LABEL: Record<ToolStatus, string> = {
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
  denied: 'Denied',
}
