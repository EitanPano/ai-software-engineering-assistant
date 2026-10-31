import type { NavEntry } from '@/shared/ui/pattern/nav-links'

// The one table that puts a screen in the shell's navigation: a feature adds its entry here. An
// entry with a `role` is shown only to an account with that role (cosmetic: the route's loader and
// the API enforce it).
export const NAV: NavEntry[] = [
  { to: '/', label: 'Home' },
  { to: '/conversation', label: 'Conversations' },
  { to: '/search', label: 'Search' },
  { to: '/source', label: 'Sources', role: 'admin' },
]
