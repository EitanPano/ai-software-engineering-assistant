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

describe('McpServerNotice', () => {
  it('names the server in our words and says the run goes on', () => {
    render(<McpServerNotice name="knowledge" />)

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('knowledge')
    expect(alert).toHaveTextContent(/unavailable/i)
    expect(alert).toHaveTextContent(/continue|without/i)
  })
})
