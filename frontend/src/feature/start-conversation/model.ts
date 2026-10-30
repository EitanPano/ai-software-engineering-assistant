// Copy for starting a conversation, keyed by the envelope's `code` (shared/api/call.ts has the
// defaults). Starting has no input to validate and no rate limit of its own.
export const START_CONVERSATION_COPY = {
  internal: "Couldn't start a conversation. Try again.",
  upstream_unavailable: "Couldn't start a conversation right now. Try again in a moment.",
}
