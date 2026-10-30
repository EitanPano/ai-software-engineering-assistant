import type { QueryClient } from '@tanstack/react-query'
import { Outlet, type RouteObject } from 'react-router'

import { conversationListQuery, conversationQuery } from '@/entity/conversation/api/conversation'
import { healthQuery } from '@/entity/health/api/health'
import { messageListQuery } from '@/entity/message/api/message'
import { redirectIfSignedIn, requireAccount, returnToOf } from '@/shared/auth/session'

import AuthError from './(auth)/error'
import AuthLayout from './(auth)/layout'
import AuthLoading from './(auth)/loading'
import SignInPage from './(auth)/sign-in/page'
import SignUpPage from './(auth)/sign-up/page'
import ConversationPage from './(site)/conversation/[id]/page'
import ConversationListPage from './(site)/conversation/page'
import SiteError from './(site)/error'
import ForbiddenPage from './(site)/forbidden/page'
import SiteLayout from './(site)/layout'
import SiteLoading from './(site)/loading'
import SiteNotFound from './(site)/not-found'
import HomePage from './(site)/page'
import ProfilePage from './(site)/profile/page'
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
                  path: 'conversation',
                  loader: async ({ request }) => {
                    await requireAccount(queryClient, returnToOf(request))
                    // Throws on failure (prefetch would swallow it), so the group's boundary shows.
                    return queryClient.infiniteQuery(conversationListQuery())
                  },
                  Component: ConversationListPage,
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
