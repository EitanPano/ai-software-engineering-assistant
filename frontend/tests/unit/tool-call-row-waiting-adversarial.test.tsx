import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ToolCallRow } from '@/entity/run/ui/tool-call-row'

const waiting = (input: Record<string, unknown>, output?: string) => ({
  kind: 'tool' as const,
  toolUseId: 't1',
  name: 'github__add_issue_comment',
  input,
  status: 'awaiting_approval' as const,
  approval: { approvalId: 'a1', argumentsDigest: 'a'.repeat(64) },
  ...(output === undefined ? {} : { output }),
})

describe('ToolCallRow waiting, adversarial input', () => {
  it('shows empty arguments as an empty object, still in the labelled group', () => {
    render(<ToolCallRow call={waiting({})} actions={<button type="button">Approve call</button>} />)

    const group = screen.getByRole('group', { name: 'Arguments of github__add_issue_comment' })
    expect(group).toHaveTextContent('{}')
    expect(group).not.toHaveAttribute('tabindex')
  })

  it('keeps one unbroken 20000-character body whole and wrappable', () => {
    const body = 'a'.repeat(20_000)
    render(<ToolCallRow call={waiting({ body })} />)

    const group = screen.getByRole('group', { name: 'Arguments of github__add_issue_comment' })
    expect(group.textContent).toContain(body)
    const pre = group.querySelector('pre')
    expect(pre).toHaveClass('break-words', 'whitespace-pre-wrap')
    expect(group.className).not.toMatch(/overflow|max-h/)
  })

  it('keeps HTML in a comment body inert text', () => {
    const body = '<img src=x onerror="alert(1)"><script>boom()</script>'
    const { container } = render(<ToolCallRow call={waiting({ body })} />)

    expect(container.querySelector('img, script')).toBeNull()
    expect(container.textContent).toContain('<script>boom()</script>')
  })

  it('shows a hidden bidi character in the body as a code point a person can read', () => {
    render(<ToolCallRow call={waiting({ body: 'ok‮evil' })} />)

    expect(screen.getByRole('group').textContent).toContain('[U+202E]')
    expect(screen.getByRole('group').textContent).not.toContain('‮')
  })

  it('puts the decision buttons after every line of a 500-line body', () => {
    const body = Array.from({ length: 500 }, (_, index) => `line ${String(index)}`).join('\n')
    render(
      <ToolCallRow
        call={waiting({ body })}
        actions={<button type="button">Approve call</button>}
      />,
    )

    const group = screen.getByRole('group', { name: 'Arguments of github__add_issue_comment' })
    const approve = screen.getByRole('button', { name: 'Approve call' })
    expect(group.compareDocumentPosition(approve) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(group.textContent).toContain('line 499')
  })

  it('still scrolls an output beside whole waiting arguments', () => {
    render(<ToolCallRow call={waiting({ body: 'x' }, 'y'.repeat(5000))} />)

    const output = screen.getByRole('group', { name: 'Output of github__add_issue_comment' })
    expect(output).toHaveAttribute('tabindex', '0')
  })
})
