import type { QueryClient } from '@tanstack/react-query'
import { Outlet, type RouteObject } from 'react-router'

import { conversationListQuery, conversationQuery } from '@/entity/conversation/api/conversation'
import { evalRunListQuery, evalRunQuery } from '@/entity/eval-run/api/eval-run'
import { healthQuery } from '@/entity/health/api/health'
import { mcpServerListQuery, mcpServerQuery } from '@/entity/mcp-server/api/mcp-server'
import { memoryListQuery } from '@/entity/memory/api/memory'
import { messageListQuery } from '@/entity/message/api/message'
import { sourceListQuery } from '@/entity/source/api/source'
import { toolPolicyQuery } from '@/entity/tool-policy/api/tool-policy'
import { redirectIfSignedIn, requireAccount, requireRole, returnToOf } from '@/shared/auth/session'

import AuthError from './(auth)/error'
import AuthLayout from './(auth)/layout'
import AuthLoading from './(auth)/loading'
import SignInPage from './(auth)/sign-in/page'
import SignUpPage from './(auth)/sign-up/page'
import ConversationPage from './(site)/conversation/[id]/page'
import ConversationListPage from './(site)/conversation/page'
import SiteError from './(site)/error'
import EvalRunPage from './(site)/eval-run/[id]/page'
import EvalRunListPage from './(site)/eval-run/page'
import ForbiddenPage from './(site)/forbidden/page'
import SiteLayout from './(site)/layout'
import SiteLoading from './(site)/loading'
import SiteNotFound from './(site)/not-found'
import HomePage from './(site)/page'
import ProfilePage from './(site)/profile/page'
import MemoryPage from './(site)/memory/page'
import ListingError from './(site)/mcp-server/[id]/listing/error'
import ListingPage from './(site)/mcp-server/[id]/listing/page'
import McpServerPage from './(site)/mcp-server/[id]/page'
import McpServerListPage from './(site)/mcp-server/page'
import SearchError from './(site)/search/error'
import SearchPage from './(site)/search/page'
import ConnectSourcePage from './(site)/source/connect/page'
import SourceListPage from './(site)/source/page'
import RootError from './root-error'

// The route table: paths to components and loaders, nothing else. A route group is a pathless
// route with its own HydrateFallback (loading) and ErrorBoundary (error), nested inside the
// group's layout so a failure renders inside the shell. A loader calls `queryClient.query` for
// what the page's widgets read (it returns cached data younger than the stale time, else fetches);
// the widgets then suspend on the same query. The query client is passed in so a test can render
// the table against its own.
export function createRoutes(queryClient: QueryClient): RouteObject[] {
  return [
    {
      path: '/',
      Component: Outlet,
      ErrorBoundary: RootError,
      children: [
        {
          Component: SiteLayout,
          children: [
            {
              // React Router shows the nearest HydrateFallback at or above the first route whose
              // loader is still pending, so this one covers every page below it.
              HydrateFallback: SiteLoading,
              ErrorBoundary: SiteError,
              children: [
                {
                  index: true,
                  loader: () => queryClient.query(healthQuery()),
                  Component: HomePage,
                },
                {
                  path: 'profile',
                  loader: ({ request }) => requireAccount(queryClient, returnToOf(request)),
                  Component: ProfilePage,
                },
                {
                  // No prefetch: the page's Suspense, keyed by the text, shows the skeleton. The
                  // segment's boundary words the search limit; any other failure is the group's.
                  path: 'search',
                  loader: ({ request }) => requireAccount(queryClient, returnToOf(request)),
                  Component: SearchPage,
                  ErrorBoundary: SearchError,
                },
                {
                  path: 'conversation',
                  loader: async ({ request }) => {
                    await requireAccount(queryClient, returnToOf(request))
                    // Throws on failure (prefetch would swallow it), so the group's boundary shows.
                    return queryClient.infiniteQuery(conversationListQuery())
                  },
                  Component: ConversationListPage,
                },
                {
                  path: 'memory',
                  loader: async ({ request }) => {
                    await requireAccount(queryClient, returnToOf(request))
                    // Throws on failure (prefetch would swallow it), so the group's boundary shows.
                    return queryClient.infiniteQuery(memoryListQuery())
                  },
                  Component: MemoryPage,
                },
                {
                  path: 'conversation/:id',
                  loader: async ({ params, request }) => {
                    await requireAccount(queryClient, returnToOf(request))
                    const id = params.id ?? ''
                    return Promise.all([
                      queryClient.query(conversationQuery(id)),
                      queryClient.query(messageListQuery(id)),
                    ])
                  },
                  Component: ConversationPage,
                },
                {
                  // The admin group: its own loader is the gate, so a staff route added here is
                  // guarded without its own call. Children still call requireRole, because
                  // matched loaders run in parallel and a child's fetch must not outrun the
                  // gate. The API checks again.
                  loader: ({ request }) => requireRole(queryClient, 'admin', returnToOf(request)),
                  children: [
                    {
                      path: 'source',
                      loader: async ({ request }) => {
                        await requireRole(queryClient, 'admin', returnToOf(request))
                        return queryClient.infiniteQuery(sourceListQuery())
                      },
                      Component: SourceListPage,
                    },
                    {
                      path: 'source/connect',
                      loader: ({ request }) =>
                        requireRole(queryClient, 'admin', returnToOf(request)),
                      Component: ConnectSourcePage,
                    },
                    {
                      // Reads only: the loader prefetches the list and sends no start.
                      path: 'eval-run',
                      loader: async ({ request }) => {
                        await requireRole(queryClient, 'admin', returnToOf(request))
                        return queryClient.infiniteQuery(evalRunListQuery())
                      },
                      Component: EvalRunListPage,
                    },
                    {
                      path: 'eval-run/:id',
                      loader: async ({ params, request }) => {
                        await requireRole(queryClient, 'admin', returnToOf(request))
                        return queryClient.query(evalRunQuery(params.id ?? ''))
                      },
                      Component: EvalRunPage,
                    },
                    {
                      path: 'mcp-server',
                      loader: async ({ request }) => {
                        await requireRole(queryClient, 'admin', returnToOf(request))
                        return queryClient.infiniteQuery(mcpServerListQuery())
                      },
                      Component: McpServerListPage,
                    },
                    {
                      path: 'mcp-server/:id',
                      loader: async ({ params, request }) => {
                        await requireRole(queryClient, 'admin', returnToOf(request))
                        const id = params.id ?? ''
                        return Promise.all([
                          queryClient.query(mcpServerQuery(id)),
                          queryClient.query(toolPolicyQuery(id)),
                        ])
                      },
                      Component: McpServerPage,
                    },
                    {
                      // Prefetches nothing: this page alone calls a live server, and only when
                      // the admin opens it. The widget suspends on the read; the segment's
                      // boundary words a server that did not answer and a listing it refuses.
                      path: 'mcp-server/:id/listing',
                      loader: ({ request }) =>
                        requireRole(queryClient, 'admin', returnToOf(request)),
                      Component: ListingPage,
                      ErrorBoundary: ListingError,
                    },
                  ],
                },
                { path: 'forbidden', Component: ForbiddenPage },
                { path: '*', Component: SiteNotFound },
              ],
            },
          ],
        },
        {
          Component: AuthLayout,
          children: [
            {
              HydrateFallback: AuthLoading,
              ErrorBoundary: AuthError,
              children: [
                {
                  path: 'sign-in',
                  loader: () => redirectIfSignedIn(queryClient),
                  Component: SignInPage,
                },
                {
                  path: 'sign-up',
                  loader: () => redirectIfSignedIn(queryClient),
                  Component: SignUpPage,
                },
              ],
            },
          ],
        },
      ],
    },
  ]
}
