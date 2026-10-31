import { zodResolver } from '@hookform/resolvers/zod'
import { SearchIcon } from 'lucide-react'
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { useSearchParams } from 'react-router'

import { Button } from '@/shared/ui/button'
import { Form } from '@/shared/ui/form/form'
import { TextField } from '@/shared/ui/form/text-field'

import { searchSchema, type SearchInput } from '../model'

// A search is a read, so there is no mutation: submitting writes `q` to the URL, which is what the
// results read, so a reload or the back button keeps them.
export function SearchForm({ q }: { q: string }) {
  const [, setSearchParams] = useSearchParams()
  const form = useForm<SearchInput, unknown, SearchInput>({
    resolver: zodResolver(searchSchema),
    defaultValues: { q },
  })

  // The box follows the URL (the back button, a link), not only what was typed.
  const { reset } = form
  useEffect(() => {
    reset({ q })
  }, [q, reset])

  const onSubmit = form.handleSubmit((values) => {
    setSearchParams({ q: values.q.trim() })
  })

  return (
    <Form form={form} onSubmit={onSubmit} className="flex max-w-3xl flex-col items-start gap-4">
      <div className="w-full">
        <TextField
          name="q"
          label="Search the knowledge base"
          type="search"
          autoComplete="off"
          spellCheck={false}
        />
      </div>
      <Button type="submit">
        <SearchIcon aria-hidden />
        Search
      </Button>
    </Form>
  )
}
