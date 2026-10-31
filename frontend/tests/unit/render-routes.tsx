import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { createMemoryRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'

import { createRoutes } from '@/app/routes'
import { ThemeProvider } from '@/shared/ui/theme-provider'

import { createTestClient } from './support'

// The app's route table in a memory router, against whatever API the test stubbed. The client is
// the test's (no stale time) unless the test passes one, such as `createAppClient()`.
export function renderRoutes(path: string, client: QueryClient = createTestClient()) {
  const router = createMemoryRouter(createRoutes(client), { initialEntries: [path] })
  render(
    <QueryClientProvider client={client}>
      <ThemeProvider defaultTheme="system">
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  )
  return router
}
