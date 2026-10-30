import { useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { LoaderCircleIcon, MessageSquareTextIcon } from 'lucide-react'
import { useState } from 'react'

import { conversationKey, conversationQuery } from '@/entity/conversation/api/conversation'
import { messageListKey, messageListQuery } from '@/entity/message/api/message'
import { inReadingOrder } from '@/entity/message/model'
import { MessageItem } from '@/entity/message/ui/message-item'
import { useRunStream } from '@/entity/run/api/use-run-stream'
import { isActiveRun, type RunView } from '@/entity/run/model'
import { RunErrorAlert } from '@/entity/run/ui/run-error-alert'
import { ToolCallRow } from '@/entity/run/ui/tool-call-row'
import { SendMessageForm } from '@/feature/send-message/ui/send-message-form'
import { EmptyState } from '@/shared/ui/pattern/empty-state'
import { ErrorState } from '@/shared/ui/pattern/error-state'

// The run being followed. `done` is set when its last event arrived: the send form is free again
// from then on, while a failed run stays on screen (with its partial text) until the next send.
type Follow = { runId: string; done: boolean }

// The conversation: its stored history, oldest first, then the run in progress as it is written.
// The history is a log that does not announce each delta (`aria-live="off"`); a finished answer is
// announced once, by the status line. On load it follows the conversation's latest run when that
// is still active, and a send hands over the new run.
export function ConversationHistory({ conversationId }: { conversationId: string }) {
  const queryClient = useQueryClient()
  const { data: conversation } = useSuspenseQuery(conversationQuery(conversationId))
  const { data: page } = useSuspenseQuery(messageListQuery(conversationId))
  const [follow, setFollow] = useState<Follow | null>(() =>
    conversation.latestRun !== null && isActiveRun(conversation.latestRun)
      ? { runId: conversation.latestRun.id, done: false }
      : null,
  )
  const [announcement, setAnnouncement] = useState('')

  // While a run is followed its stored turns are hidden: the stream replays the whole run, so a
  // reload mid-run never shows a committed turn twice.
  const stored = inReadingOrder(page.items).filter(
    (message) =>
      message.text.trim() !== '' &&
      !(follow !== null && message.runId === follow.runId && message.role === 'assistant'),
  )

  async function onFinished(view: RunView) {
    setAnnouncement(view.finished?.status === 'completed' ? 'The agent finished answering.' : '')
    setFollow((current) => (current ? { ...current, done: true } : current))
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: messageListKey(conversationId) }),
      queryClient.invalidateQueries({ queryKey: conversationKey(conversationId) }),
    ])
    // The run stays on screen, finished, until the next send or a reload: its tool calls are not
    // stored (a later task), so removing it would make them vanish the moment the answer ends. Its
    // stored turns stay hidden meanwhile, so nothing shows twice.
  }

  const staleFailure =
    follow === null && conversation.latestRun?.status === 'failed' ? conversation.latestRun : null
  const empty = stored.length === 0 && follow === null

  return (
    <div className="flex flex-col gap-6">
      {empty ? (
        <EmptyState
          icon={MessageSquareTextIcon}
          title="Ask the agent something"
          description="Your message and the agent's answer appear here as it is written."
        />
      ) : null}
      <div
        role="log"
        aria-label="Conversation history"
        aria-live="off"
        className="flex max-w-3xl flex-col gap-4"
      >
        <ol className="flex flex-col gap-4">
          {stored.map((message) => (
            <MessageItem key={message.id} message={message} />
          ))}
          {follow === null ? null : (
            <LiveRun key={follow.runId} runId={follow.runId} onFinished={onFinished} />
          )}
        </ol>
        {staleFailure ? <RunErrorAlert errorCode={staleFailure.errorCode} /> : null}
      </div>
      <p role="status" className="sr-only">
        {announcement}
      </p>
      <SendMessageForm
        conversationId={conversationId}
        busy={follow !== null && !follow.done}
        onSent={(sent) => {
          setAnnouncement('')
          setFollow({ runId: sent.run.id, done: false })
        }}
      />
    </div>
  )
}

// One run as it arrives: text and tool calls in order, a marker while it writes, and the failure
// when it ends badly. Rendered under `key={runId}` so a new run starts from nothing.
function LiveRun({
  runId,
  onFinished,
}: {
  runId: string
  onFinished: (view: RunView) => Promise<void>
}) {
  const { view, state, retry } = useRunStream(
    runId,
    (finishedView) => void onFinished(finishedView),
  )

  return (
    <>
      {view.blocks.map((block, index) =>
        block.kind === 'text' ? (
          <MessageItem key={index} message={{ role: 'assistant', text: block.text }} />
        ) : (
          <ToolCallRow key={block.toolUseId} call={block} />
        ),
      )}
      {state === 'streaming' ? (
        <li className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircleIcon aria-hidden className="size-4 motion-safe:animate-spin" />
          Agent is working…
        </li>
      ) : null}
      {state === 'lost' ? (
        <li>
          <ErrorState
            title="Lost the connection to the answer"
            description="The rest of the answer is safe on the server. Reconnect to keep following it."
            onRetry={retry}
          />
        </li>
      ) : null}
      {view.finished?.status === 'failed' ? (
        <li>
          <RunErrorAlert errorCode={view.finished.errorCode} />
        </li>
      ) : null}
    </>
  )
}
