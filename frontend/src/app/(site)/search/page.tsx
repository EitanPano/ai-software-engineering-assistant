import { Suspense } from 'react'
import { useSearchParams } from 'react-router'

import { SearchForm } from '@/feature/search/ui/search-form'
import { Page, PageHeader } from '@/shared/ui/pattern/page-layout'
import { SearchResult } from '@/widget/search-result/ui/search-result'
import { SearchResultSkeleton } from '@/widget/search-result/ui/search-result-skeleton'

// Hybrid search over the ready repositories, behind `requireAccount` (routes.tsx). The text lives
// in the URL (`?q=`), so a reload or the back button keeps the results. The loader prefetches
// nothing: it would hold the navigation and the skeleton would never show. The Suspense is keyed
// by the text, so a new search shows the skeleton instead of a held transition.
export default function SearchPage() {
  const [params] = useSearchParams()
  const q = (params.get('q') ?? '').trim()
  return (
    <Page>
      <title>Search · AI Software Engineering Assistant</title>
      <meta name="robots" content="noindex" />
      <PageHeader title="Search" description="Find code in the connected repositories." />
      <SearchForm q={q} />
      <Suspense key={q} fallback={<SearchResultSkeleton />}>
        <SearchResult q={q} />
      </Suspense>
    </Page>
  )
}
