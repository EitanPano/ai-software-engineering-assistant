import type { ToolPolicy, ToolPolicySet } from '@/shared/api'

export type { ToolPolicy, ToolPolicySet }
export type Effect = NonNullable<ToolPolicy['effect']>

const EFFECT_LABEL: Record<Effect, string> = { allow: 'Allow', ask: 'Ask', deny: 'Deny' }

// A tool with no row is denied; the screen says so in words.
export const NO_RULE_LABEL = 'Denied (no rule)'

const EFFECT_MEANING: Record<Effect, string> = {
  allow: 'Allow, runs without asking',
  ask: 'Ask, waits for your approval',
  deny: 'Deny, never runs',
}

// What the stored effect does, in words, for a screen that is not the policy list. A tool with no
// row, and one the policy document does not name yet, is denied.
export const effectNote = (effect: ToolPolicy['effect'] | undefined): string =>
  effect === undefined || effect === null ? NO_RULE_LABEL : EFFECT_MEANING[effect]

export const effectLabel = (effect: ToolPolicy['effect']): string =>
  effect === null ? NO_RULE_LABEL : EFFECT_LABEL[effect]
