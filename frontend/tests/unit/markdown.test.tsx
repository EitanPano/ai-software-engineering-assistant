import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Markdown } from '@/shared/ui/markdown'

// Assistant text and repository content are attacker-controlled: rendered as Markdown, never as
// raw HTML (.doc/conventions.md › Agent security).
describe('Markdown', () => {
  it('renders emphasis, lists and code', () => {
    render(<Markdown>{'**bold** and `code`\n\n- one\n- two'}</Markdown>)

    expect(screen.getByText('bold').tagName).toBe('STRONG')
    expect(screen.getByText('code').tagName).toBe('CODE')
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('leaves raw HTML inert', () => {
    const { container } = render(
      <Markdown>{'hello <img src="x" onerror="alert(1)"> <script>alert(1)</script>'}</Markdown>,
    )

    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('[onerror]')).toBeNull()
    // Shown as the literal text it is.
    expect(container.textContent).toContain('<img src="x"')
  })

  it('drops a javascript: link target', () => {
    render(<Markdown>{'[click](javascript:alert(1))'}</Markdown>)

    const link = screen.queryByRole('link', { name: 'click' })
    expect(link?.getAttribute('href') ?? '').not.toMatch(/javascript:/i)
  })

  it('opens a normal link safely', () => {
    render(<Markdown>{'[docs](https://example.com/a)'}</Markdown>)

    const link = screen.getByRole('link', { name: 'docs' })
    expect(link).toHaveAttribute('href', 'https://example.com/a')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })
})
