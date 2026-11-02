import type { Conversation, ConversationDetail } from '@/shared/api'

export type { Conversation, ConversationDetail }

export const UNTITLED = 'Untitled conversation'

// A conversation has no title until the server sets one from its first message.
export const conversationTitle = (conversation: Pick<Conversation, 'title'>): string =>
  conversation.title?.trim() || UNTITLED
