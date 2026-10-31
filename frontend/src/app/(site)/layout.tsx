import { Outlet } from 'react-router'

import { useCurrentUser } from '@/entity/user/api/user'
import { AppShell } from '@/shared/ui/pattern/app-shell'
import { AccountMenu } from '@/widget/account-menu/ui/account-menu'

import { NAV } from '../nav'

// The shell's account slot. With the server's auth it is the account widget (it reads the session
// and renders a skeleton while it loads); without, the theme menu alone.
const account = <AccountMenu />

// The site frame: header with the nav table and the account slot, the page's one `main`, footer.
// An entry with a role shows only to an account that has it.
export default function SiteLayout() {
  const { user } = useCurrentUser()
  const nav = NAV.filter((entry) => entry.role === undefined || entry.role === user?.role)
  return (
    <AppShell name="AI Software Engineering Assistant" nav={nav} account={account}>
      <Outlet />
    </AppShell>
  )
}
