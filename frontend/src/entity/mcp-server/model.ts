import type { ListingTool, McpServer, McpServerListing, McpServerPage } from '@/shared/api'

export type { ListingTool, McpServer, McpServerListing, McpServerPage }

export type Tone = 'success' | 'warning' | 'muted' | 'info'

const PIN_LABEL: Record<McpServer['pinStatus'], string> = {
  not_required: 'No pin needed',
  unpinned: 'Not accepted yet',
  current: 'Listing accepted',
  changed: 'Listing changed',
}

const PIN_TONE: Record<McpServer['pinStatus'], Tone> = {
  not_required: 'muted',
  unpinned: 'warning',
  current: 'success',
  changed: 'warning',
}

const CHANGE_LABEL: Record<ListingTool['change'], string> = {
  added: 'Added',
  removed: 'Removed',
  changed: 'Changed',
  unchanged: 'Unchanged',
}

const CHANGE_TONE: Record<ListingTool['change'], Tone> = {
  added: 'info',
  removed: 'warning',
  changed: 'warning',
  unchanged: 'muted',
}

export const pinLabel = (status: McpServer['pinStatus']): string => PIN_LABEL[status]
export const pinTone = (status: McpServer['pinStatus']): Tone => PIN_TONE[status]
export const enabledLabel = (enabled: boolean): string => (enabled ? 'Enabled' : 'Disabled')
export const changeLabel = (change: ListingTool['change']): string => CHANGE_LABEL[change]
export const changeTone = (change: ListingTool['change']): Tone => CHANGE_TONE[change]

// The review is the filled action when the stored listing is not the accepted one.
export const needsReview = (server: Pick<McpServer, 'pinStatus'>): boolean =>
  server.pinStatus === 'unpinned' || server.pinStatus === 'changed'

// `knowledge` has no pin, so it has no review.
export const canReview = (server: Pick<McpServer, 'pinStatus'>): boolean =>
  server.pinStatus !== 'not_required'

// Nothing to accept when every tool reads as it was accepted.
export const matchesPin = (listing: Pick<McpServerListing, 'items'>): boolean =>
  listing.items.every((tool) => tool.change === 'unchanged')
