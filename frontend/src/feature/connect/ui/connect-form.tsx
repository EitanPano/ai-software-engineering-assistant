import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router'

import { Button } from '@/shared/ui/button'
import { Form } from '@/shared/ui/form/form'
import { reportFailure } from '@/shared/ui/form/report-failure'
import { TextField } from '@/shared/ui/form/text-field'
import { FormActions } from '@/shared/ui/pattern/form-actions'

import { useConnectSource } from '../api/connect'
import { connectSchema, type ConnectInput } from '../model'

// Connect a repository: a missing or duplicate one lands under the url field, GitHub being down
// is a toast, and a success returns to the list, where the new row is queued.
export function ConnectForm() {
  const form = useForm<ConnectInput, unknown, ConnectInput>({
    resolver: zodResolver(connectSchema),
    defaultValues: { url: '', ref: '' },
  })
  const connect = useConnectSource()
  const navigate = useNavigate()

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      await connect.mutateAsync(values)
    } catch (error) {
      reportFailure(form, error)
      return
    }
    await navigate('/source')
  })

  return (
    <Form form={form} onSubmit={onSubmit} className="flex max-w-xl flex-col gap-4">
      <TextField
        name="url"
        label="Repository URL"
        description="A public repository, for example https://github.com/octocat/Hello-World"
        type="url"
        inputMode="url"
        autoComplete="off"
      />
      <TextField
        name="ref"
        label="Branch, tag or commit (optional)"
        description="Leave empty for the default branch."
        autoComplete="off"
      />
      <FormActions>
        <Button asChild variant="outline">
          <Link to="/source">Cancel</Link>
        </Button>
        <Button type="submit" disabled={connect.isPending}>
          {connect.isPending ? 'Connecting…' : 'Connect repository'}
        </Button>
      </FormActions>
    </Form>
  )
}
