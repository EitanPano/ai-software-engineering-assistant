import { expect, type APIRequestContext, type Page } from '@playwright/test'

import { registerThroughUi } from './auth-support'

// The scripted Anthropic fake (backend/tests/fake_anthropic.py) answers by markers anywhere in the
// user's message, `[[name]]` or `[[name:key]]`, so parallel journeys stay apart.
export const FAKE_URL = 'http://127.0.0.1:8101'
export const MARKER = {
  // Streams "The first part. ", waits for a release of KEY (or 30 s), then "The rest, **done**."
  hold: (key: string) => `[[hold:${key}]]`,
  // A tool call nothing registered (so it is denied), then "Tool done."
  tool: (name: string) => `[[tool:${name}]]`,
  // Two searches of the knowledge base, then an answer citing the last result's file and lines
  // (backend/tests/fake_anthropic.py).
  research: '[[research]]',
  // The run fails with `refused`.
  refuse: '[[refuse]]',
}
export const TEXT = {
  first: 'The first part.',
  rest: 'The rest, ',
  strong: 'done',
  toolName: 'lookup',
  toolDone: 'Tool done.',
  // The `note` tool of the `fixture` MCP server, seeded at `ask` (backend/tests/seed_ask_tool.py);
  // the fake asks for it with the arguments `{"text": "hi"}`.
  askTool: 'fixture__note',
  askArguments: '"text": "hi"',
}

export function uniqueToken(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

// Lets the held scenario go on.
export async function release(request: APIRequestContext, key: string) {
  const response = await request.post(`${FAKE_URL}/release/${key}`)
  expect(response.ok()).toBe(true)
}

// Signs up, starts a conversation from the list and sends one message, all through the UI.
export async function startAndSend(page: Page, message: string) {
  await registerThroughUi(page)
  await page.goto('/conversation')
  await page.getByRole('button', { name: 'Start conversation' }).click()
  await expect(page).toHaveURL(/\/conversation\/[^/]+$/)
  await sendMessage(page, message)
}

export async function sendMessage(page: Page, message: string) {
  await page.getByLabel('Message').fill(message)
  await page.getByRole('button', { name: 'Send message' }).click()
}
