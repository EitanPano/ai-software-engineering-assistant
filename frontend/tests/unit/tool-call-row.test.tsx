import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { McpServerNotice } from '@/entity/run/ui/mcp-server-notice'
import { ToolCallRow } from '@/entity/run/ui/tool-call-row'

const call = (overrides: Partial<Parameters<typeof ToolCallRow>[0]['call']> = {}) => ({
  kind: 'tool' as const,
  toolUseId: 't1',
  name: 'knowledge__search',
  input: { query: 'ask yes or no' },
  status: 'succeeded' as const,
  ...overrides,
})

describe('ToolCallRow', () => {
  it('shows the name, the status in words and the input as text', () => {
    render(<ToolCallRow call={call({ status: 'running' })} />)

    expect(screen.getByText('knowledge__search')).toBeInTheDocument()
    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(screen.getByText('{"query":"ask yes or no"}')).toBeInTheDocument()
  })

  it('puts a long output in a labelled, keyboard-focusable box', () => {
    render(<ToolCallRow call={call({ output: 'x'.repeat(5000) })} />)

    const box = screen.getByRole('group', { name: 'Output of knowledge__search' })
    expect(box).toHaveAttribute('tabindex', '0')
    expect(box).toHaveClass('overflow-auto')
  })

  it('keeps repository HTML inert text', () => {
    const html = '<img src=x onerror="alert(1)"><script>boom()</script>'
    const { container } = render(<ToolCallRow call={call({ output: html })} />)

    expect(container.querySelector('img, script')).toBeNull()
    expect(screen.getByText(html)).toBeInTheDocument()
  })

  it('shows no output box while the call is running', () => {
    render(<ToolCallRow call={call({ status: 'running' })} />)

    expect(screen.queryByRole('group')).not.toBeInTheDocument()
  })

  it('shows bidi and tag characters in an output as code points, never obeyed', () => {
    render(<ToolCallRow call={call({ output: 'a‮b\u{E0041}c' })} />)

    expect(screen.getByText('a[U+202E]b[U+E0041]c')).toBeInTheDocument()
  })

  it('shows hidden characters in the input as code points too', () => {
    render(<ToolCallRow call={call({ input: { query: 'x‮y\u{E0041}' } })} />)

    expect(screen.getByText(/x\[U\+202E\]y\[U\+E0041\]/)).toBeInTheDocument()
  })
})

describe('ToolCallRow waiting for approval', () => {
  const waiting = (input: Record<string, unknown>) =>
    call({
      status: 'awaiting_approval',
      input,
      approval: { approvalId: 'a1', argumentsDigest: 'a'.repeat(64) },
    })

  it('says it needs approval in words and shows the actions it is given', () => {
    render(
      <ToolCallRow
        call={waiting({ text: 'hi' })}
        actions={<button type="button">Approve call</button>}
      />,
    )

    expect(screen.getByText('Needs approval')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve call' })).toBeInTheDocument()
  })

  it('shows the whole arguments, pretty-printed, in a labelled group with no cap and no scroll', () => {
    const text = 'x'.repeat(5000)
    render(<ToolCallRow call={waiting({ text, nested: { n: 1 } })} />)

    const box = screen.getByRole('group', { name: 'Arguments of knowledge__search' })
    expect(box).not.toHaveAttribute('tabindex')
    expect(box.className).not.toMatch(/overflow|max-h/)
    expect(box.textContent).toContain(text)
    expect(box.textContent).toContain('\n  "nested": {\n    "n": 1\n  }')
  })

  it('shows hidden characters in the arguments as code points', () => {
    render(<ToolCallRow call={waiting({ text: 'a‮b\u{E0041}c' })} />)

    const box = screen.getByRole('group', { name: 'Arguments of knowledge__search' })
    expect(box.textContent).toContain('a[U+202E]b[U+E0041]c')
  })

  it('shows no actions on a decided call', () => {
    render(<ToolCallRow call={call({ status: 'succeeded' })} />)

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByText('Needs approval')).not.toBeInTheDocument()
  })
})

describe('McpServerNotice', () => {
  it('names the server in our words and says the run goes on', () => {
    render(<McpServerNotice name="knowledge" />)

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('knowledge')
    expect(alert).toHaveTextContent(/unavailable/i)
    expect(alert).toHaveTextContent(/continue|without/i)
  })
})
