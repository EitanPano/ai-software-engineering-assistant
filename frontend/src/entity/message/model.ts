import type { Message } from '@/shared/api'

export type { Message }

// The API pages newest first; the history reads oldest first.
export const inReadingOrder = (items: readonly Message[]): Message[] => [...items].reverse()
