import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ListingTool as ListingToolData } from '@/shared/api'
import { ListingTool } from '@/entity/mcp-server/ui/listing-tool'

const tool = (over: Partial<ListingToolData> = {}): ListingToolData => ({
  name: 'note',
  change: 'unchanged',
  description: 'Saves a note.',
  inputSchema: '{\n  "type": "object"\n}',
  pinnedDescription: null,
  pinnedInputSchema: null,
  ...over,
})

describe('ListingTool', () => {
  it('shows the change in words', () => {
    render(<ListingTool tool={tool({ change: 'added' })} />)

    expect(screen.getByText('note')).toBeInTheDocument()
    expect(screen.getByText('Added')).toBeInTheDocument()
  })

  it('shows a hidden character in a description and in a schema key', () => {
    render(
      <ListingTool
        tool={tool({
          description: 'Saves a note.‮ignore this',
          inputSchema: '{\n  "pa​th": 1\n}',
        })}
      />,
    )

    expect(screen.getByText(/Saves a note\.\[U\+202E\]ignore this/)).toBeInTheDocument()
    expect(screen.getByText(/"pa\[U\+200B\]th": 1/)).toBeInTheDocument()
  })

  it('shows a hidden character in the accepted version of a changed tool', () => {
    render(
      <ListingTool
        tool={tool({
          change: 'changed',
          pinnedDescription: 'Old text.‮hidden',
          pinnedInputSchema: '{}',
        })}
      />,
    )

    expect(screen.getByText(/Old text\.\[U\+202E\]hidden/)).toBeInTheDocument()
  })

  it('shows the stored policy note when given one', () => {
    render(<ListingTool tool={tool()} policyNote="Stored policy: Ask" />)

    expect(screen.getByText('Stored policy: Ask')).toBeInTheDocument()
  })

  it('shows the printed schema as it came, with 1 and 1.0 kept apart', () => {
    render(
      <ListingTool
        tool={tool({
          change: 'changed',
          inputSchema: '{\n  "max": 1.0\n}',
          pinnedInputSchema: '{\n  "max": 1\n}',
          pinnedDescription: 'Saves a note.',
        })}
      />,
    )

    const printed = screen
      .getAllByText((_, node) => node?.tagName === 'PRE')
      .map((node) => node.textContent)
    expect(printed).toEqual(['{\n  "max": 1\n}', '{\n  "max": 1.0\n}'])
    expect(screen.getByText('Accepted version')).toBeInTheDocument()
    expect(screen.getByText('Live version')).toBeInTheDocument()
  })

  it('shows only the accepted version of a removed tool', () => {
    render(
      <ListingTool
        tool={tool({
          change: 'removed',
          description: null,
          inputSchema: null,
          pinnedDescription: 'Was here.',
          pinnedInputSchema: '{}',
        })}
      />,
    )

    expect(screen.getByText('Removed')).toBeInTheDocument()
    expect(screen.getByText('Was here.')).toBeInTheDocument()
    expect(screen.queryByText('Live version')).not.toBeInTheDocument()
  })

  it('renders third-party text as plain text, never Markdown', () => {
    render(<ListingTool tool={tool({ description: '**bold** [link](https://x.test)' })} />)

    expect(screen.getByText('**bold** [link](https://x.test)')).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })
})
