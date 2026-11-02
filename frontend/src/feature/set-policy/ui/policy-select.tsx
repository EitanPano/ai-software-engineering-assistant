import { toast } from 'sonner'

import {
  effectLabel,
  NO_RULE_LABEL,
  type Effect,
  type ToolPolicy,
} from '@/entity/tool-policy/model'
import { ActionError } from '@/shared/lib/action-error'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'

import { useSetPolicy } from '../api/set-policy'
import { SET_POLICY_COPY } from '../model'

// A labelled select per tool. The options are the effects the API sent: the browser holds no rule.
// It is controlled by the stored effect, so a failed write leaves the select where it was.
export function PolicySelect({ mcpServerId, policy }: { mcpServerId: string; policy: ToolPolicy }) {
  const setPolicy = useSetPolicy(mcpServerId)
  const label = `Policy for ${policy.toolName}`

  async function onChange(value: string) {
    const effect = value as Effect
    try {
      await setPolicy.mutateAsync({ toolName: policy.toolName, effect })
    } catch (error) {
      toast.error(error instanceof ActionError ? error.message : SET_POLICY_COPY.internal)
      return
    }
    toast.success(`${policy.toolName} set to ${effectLabel(effect).toLowerCase()}`)
  }

  return (
    <Select
      value={policy.effect ?? ''}
      onValueChange={(value) => void onChange(value)}
      disabled={setPolicy.isPending}
    >
      <SelectTrigger aria-label={label} className="w-full sm:w-48">
        <SelectValue placeholder={NO_RULE_LABEL} />
      </SelectTrigger>
      <SelectContent>
        {policy.effects.map((effect) => (
          <SelectItem key={effect} value={effect}>
            {effectLabel(effect)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
