import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { searchSchema } from '@/feature/search/model'
import { SearchForm } from '@/feature/search/ui/search-form'

import { renderApp } from './support'

describe('search input attacks', () => {
  it('counts 500 characters after trimming, not before', () => {
    expect(searchSchema.safeParse({ q: ` ${'x'.repeat(500)} ` }).success).toBe(true)
    expect(searchSchema.safeParse({ q: `${'x'.repeat(250)} ${'y'.repeat(249)}` }).success).toBe(
      true,
    )
    expect(searchSchema.safeParse({ q: `${'x'.repeat(250)} ${'y'.repeat(250)}` }).success).toBe(
      false,
    )
  })

  it('refuses every whitespace-only text, tabs and newlines included', () => {
    for (const q of ['', ' ', '\t', '\n', ' \t\n ']) {
      expect(searchSchema.safeParse({ q }).success).toBe(false)
    }
  })

  it('keeps markup and operators as plain text in the URL', async () => {
    renderApp(<SearchForm q="" />, { route: '/search' })

    await userEvent.type(screen.getByLabelText('Search the knowledge base'), 'a&b=c#d')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByTestId('where')).toHaveTextContent('/search?q=a%26b%3Dc%23d')
  })

  it('survives a rapid double submit with one coherent URL', async () => {
    renderApp(<SearchForm q="" />, { route: '/search' })

    await userEvent.type(screen.getByLabelText('Search the knowledge base'), 'limiter')
    const button = screen.getByRole('button', { name: 'Search' })
    await userEvent.dblClick(button)

    expect(await screen.findByTestId('where')).toHaveTextContent(/^\/search\?q=limiter$/)
  })
})
