import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { EMPTY_QUERY_MESSAGE, searchSchema } from '@/feature/search/model'
import { SearchForm } from '@/feature/search/ui/search-form'

import { renderApp } from './support'

describe('searchSchema', () => {
  it('trims the text and takes its limit from the contract', () => {
    expect(searchSchema.parse({ q: '  limiter  ' })).toEqual({ q: 'limiter' })
    expect(searchSchema.safeParse({ q: 'x'.repeat(500) }).success).toBe(true)
    expect(searchSchema.safeParse({ q: 'x'.repeat(501) }).success).toBe(false)
  })

  it('words the empty case here', () => {
    const result = searchSchema.safeParse({ q: '   ' })
    expect(result.success).toBe(false)
    expect(result.error?.issues[0]?.message).toBe(EMPTY_QUERY_MESSAGE)
  })
})

describe('SearchForm', () => {
  it('writes the trimmed text to the URL', async () => {
    renderApp(<SearchForm q="" />, { route: '/search' })

    await userEvent.type(screen.getByLabelText('Search the knowledge base'), '  check_limit ')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByTestId('where')).toHaveTextContent('/search?q=check_limit')
  })

  it('starts from the text in the URL', () => {
    renderApp(<SearchForm q="rate limit" />, { route: '/search?q=rate+limit' })

    expect(screen.getByLabelText('Search the knowledge base')).toHaveValue('rate limit')
  })

  it('refuses blank text on the field and leaves the URL alone', async () => {
    renderApp(<SearchForm q="" />, { route: '/search' })

    await userEvent.type(screen.getByLabelText('Search the knowledge base'), '   ')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText(EMPTY_QUERY_MESSAGE)).toBeInTheDocument()
    expect(screen.getByLabelText('Search the knowledge base')).toHaveAttribute(
      'aria-invalid',
      'true',
    )
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/search$/)
  })
})
