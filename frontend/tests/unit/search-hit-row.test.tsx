import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { chunkLabel, matchedKeyword, visibleText } from '@/entity/chunk/model'
import { SearchHitRow } from '@/entity/chunk/ui/search-hit-row'

import { hit } from './search-support'

describe('chunkLabel', () => {
  it('is path:start-end', () => {
    expect(chunkLabel(hit())).toBe('src/limiter.py:10-24')
  })

  it('is one number for a piece of a single line', () => {
    expect(chunkLabel(hit({ startLine: 7, endLine: 7 }))).toBe('src/limiter.py:7')
  })

  it('shows a bidi control in the path instead of obeying it', () => {
    expect(chunkLabel(hit({ path: 'a‮b.py' }))).toBe('a[U+202E]b.py:10-24')
  })
})

describe('visibleText', () => {
  it('keeps ordinary text, newlines and tabs', () => {
    expect(visibleText('a\tb\nc é 日本')).toBe('a\tb\nc é 日本')
  })

  it.each([
    ['‮', '[U+202E]'],
    ['⁦', '[U+2066]'],
    ['​', '[U+200B]'],
    ['\u0000', '[U+0000]'],
    ['\u001B', '[U+001B]'],
    ['\u0085', '[U+0085]'],
    ['\u007F', '[U+007F]'],
  ])('shows %j as %s', (char, shown) => {
    expect(visibleText(`x${char}y`)).toBe(`x${shown}y`)
  })
})

describe('visibleText, invisible characters the ranges missed', () => {
  it.each([
    ['­', '[U+00AD]'],
    ['͏', '[U+034F]'],
    ['ᅟ', '[U+115F]'],
    ['᠎', '[U+180E]'],
    [' ', '[U+2028]'],
    [' ', '[U+2029]'],
    ['ㅤ', '[U+3164]'],
    ['︀', '[U+FE00]'],
    ['️', '[U+FE0F]'],
    ['ﾠ', '[U+FFA0]'],
    ['￹', '[U+FFF9]'],
    ['\u{E0001}', '[U+E0001]'],
    ['\u{E0041}', '[U+E0041]'],
    ['\u{E0100}', '[U+E0100]'],
    ['\u{1D173}', '[U+1D173]'],
  ])('shows %j as %s', (char, shown) => {
    expect(visibleText(`x${char}y`)).toBe(`x${shown}y`)
  })

  it('drops a carriage return before a newline and shows a lone one', () => {
    expect(visibleText('a\r\nb')).toBe('a\nb')
    expect(visibleText('a\rb')).toBe('a[U+000D]b')
    expect(visibleText('a\r')).toBe('a[U+000D]')
  })
})

describe('matchedKeyword', () => {
  it('is true when full-text or trigram search returned the chunk', () => {
    expect(matchedKeyword(hit({ fullTextRank: 3, trigramRank: null }))).toBe(true)
    expect(matchedKeyword(hit({ fullTextRank: null, trigramRank: 1 }))).toBe(true)
  })

  it('is false for a semantic-only hit', () => {
    expect(matchedKeyword(hit({ fullTextRank: null, trigramRank: null }))).toBe(false)
  })
})

describe('SearchHitRow', () => {
  it('shows the repository, the label, the symbol, the text and a keyword badge in words', () => {
    render(<SearchHitRow hit={hit()} repository="octocat/Hello-World" />)

    expect(screen.getByText('octocat/Hello-World')).toBeInTheDocument()
    expect(screen.getByText('src/limiter.py:10-24')).toBeInTheDocument()
    expect(screen.getByText('check_limit')).toBeInTheDocument()
    expect(screen.getByText(/def check_limit\(key\):/)).toBeInTheDocument()
    expect(screen.getByText('Keyword match')).toBeInTheDocument()
  })

  it('renders a null symbol, a one-line piece and a semantic-only hit without the badge', () => {
    render(
      <SearchHitRow
        hit={hit({ symbol: null, startLine: 3, endLine: 3, fullTextRank: null })}
        repository="octocat/Hello-World"
      />,
    )

    expect(screen.getByText('src/limiter.py:3')).toBeInTheDocument()
    expect(screen.queryByText('Keyword match')).not.toBeInTheDocument()
    expect(screen.queryByText('null')).not.toBeInTheDocument()
  })

  it('renders HTML in the chunk, path and symbol as text, never as elements or links', () => {
    const { container } = render(
      <SearchHitRow
        hit={hit({
          path: '<b>p</b>.py',
          symbol: '<img src=x onerror=alert(1)>',
          content: '<script>alert(1)</script>\n[a link](https://evil.example)\n# not a heading',
        })}
        repository="octocat/Hello-World"
      />,
    )

    expect(container.querySelector('script, img, b, a, h1, h2, h3')).toBeNull()
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument()
    expect(screen.getByText(/\[a link\]\(https:\/\/evil\.example\)/)).toBeInTheDocument()
  })

  it('shows bidi controls in the content visibly', () => {
    render(<SearchHitRow hit={hit({ content: 'access‮ = 1' })} repository="octocat/Hello-World" />)

    expect(screen.getByText(/access\[U\+202E\] = 1/)).toBeInTheDocument()
  })

  it('wraps long unbroken text rather than scrolling sideways', () => {
    render(
      <SearchHitRow hit={hit({ content: 'x'.repeat(6000) })} repository="octocat/Hello-World" />,
    )

    const pre = screen.getByText('x'.repeat(6000))
    expect(pre.tagName).toBe('PRE')
    expect(pre.className).toMatch(/whitespace-pre-wrap/)
    expect(pre.className).toMatch(/break-all|break-words|wrap-anywhere/)
  })
})
