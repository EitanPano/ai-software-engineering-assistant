import type { Run, RunEvent } from '@/shared/api'

export type RunErrorCode = NonNullable<Run['errorCode']>
export type ToolStatus =
  'running' | 'awaiting_approval' | 'approved' | 'succeeded' | 'failed' | 'denied'

// What a decision must echo: the id to decide and the digest of the arguments the person was shown.
export type PendingApproval = { approvalId: string; argumentsDigest: string }

export type RunBlock =
  | { kind: 'text'; text: string }
  // A tool server that was down for this run; the run goes on without its tools.
  | { kind: 'notice'; name: string }
  | {
      kind: 'tool'
      toolUseId: string
      name: string
      input: Record<string, unknown>
      status: ToolStatus
      output?: string
      // Present only while the call waits for a person.
      approval?: PendingApproval
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
    case 'approval_requested':
      return {
        ...next,
        blocks: view.blocks.map((block) =>
          block.kind === 'tool' && block.toolUseId === event.toolUseId
            ? {
                ...block,
                status: 'awaiting_approval',
                approval: { approvalId: event.approvalId, argumentsDigest: event.argumentsDigest },
              }
            : block,
        ),
      }
    case 'approval_decided':
      // Shown at once, as decided. The run resumes only after the last decision of a pause, so an
      // approved call has not started (`approved`, not `running`) and a rejected one is `denied`
      // now, however long another call of the pause waits. `tool_call_finished` ends it.
      return {
        ...next,
        blocks: view.blocks.map((block) => {
          if (block.kind !== 'tool' || block.toolUseId !== event.toolUseId) return block
          const { approval: _approval, ...rest } = block
          return { ...rest, status: event.decision === 'approved' ? 'approved' : 'denied' }
        }),
      }
    case 'mcp_server_unavailable':
      return { ...next, blocks: [...view.blocks, { kind: 'notice', name: event.name }] }
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
  run?.status === 'queued' || run?.status === 'running' || run?.status === 'awaiting_approval'

// True while any tool call in the view waits for a person's decision.
export const isAwaitingApproval = (view: RunView): boolean =>
  view.blocks.some((block) => block.kind === 'tool' && block.status === 'awaiting_approval')

export const TOOL_STATUS_LABEL: Record<ToolStatus, string> = {
  running: 'Running',
  awaiting_approval: 'Needs approval',
  approved: 'Approved',
  succeeded: 'Succeeded',
  failed: 'Failed',
  denied: 'Denied',
}
