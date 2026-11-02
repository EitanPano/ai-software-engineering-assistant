import { zodResolver } from '@hookform/resolvers/zod'
import { SendIcon } from 'lucide-react'
import { useForm } from 'react-hook-form'

import { Button } from '@/shared/ui/button'
import { Form } from '@/shared/ui/form/form'
import { reportFailure } from '@/shared/ui/form/report-failure'
import { TextareaField } from '@/shared/ui/form/textarea-field'

import { useSendMessage } from '../api/send-message'
import { sendMessageSchema, type SendMessageInput, type SentMessage } from '../model'

// The send form. A failure lands on the field (empty text) or in a toast (a run is still active,
// the limit, an outage) and keeps the person's text; a success hands the run to the caller, which
// follows it, and clears the box. `busy` keeps the button off while the agent writes (a second
// send would be refused), while the box stays usable for the next message. Ctrl or Cmd+Enter sends.
export function SendMessageForm({
  conversationId,
  busy = false,
  onSent,
}: {
  conversationId: string
  busy?: boolean
  onSent: (sent: SentMessage) => void
}) {
  const form = useForm<SendMessageInput, unknown, SendMessageInput>({
    resolver: zodResolver(sendMessageSchema),
    defaultValues: { content: '' },
  })
  const send = useSendMessage(conversationId)

  const onSubmit = form.handleSubmit(async (values) => {
    let sent: SentMessage
    try {
      sent = await send.mutateAsync(values)
    } catch (error) {
      reportFailure(form, error)
      return
    }
    form.reset()
    onSent(sent)
  })

  return (
    <Form
      form={form}
      onSubmit={onSubmit}
      onKeyDown={(event) => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
          event.preventDefault()
          void onSubmit()
        }
      }}
      className="sticky bottom-0 z-10 -mx-4 flex flex-col gap-2 border-t border-border bg-background px-4 py-3 sm:static sm:mx-0 sm:border-0 sm:p-0"
    >
      <TextareaField name="content" label="Message" rows={2} className="max-h-48" />
      <div className="flex sm:justify-end">
        <Button type="submit" disabled={busy || send.isPending} className="w-full sm:w-auto">
          <SendIcon aria-hidden />
          {send.isPending ? 'Sending…' : 'Send message'}
        </Button>
      </div>
    </Form>
  )
}
