import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { auth } from './api'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { AppLogo } from '@/components/AppLogo'
import {
  LayoutDashboard,
  Link2,
  Server,
  Globe,
  Settings,
  LogOut,
} from 'lucide-react'

export default function Layout() {
  const [user, setUser] = useState<string | null>(null)
  const [checking, setChecking] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    auth.me().then((d) => setUser(d.username)).catch(() => navigate('/', { replace: true })).finally(() => setChecking(false))
  }, [navigate])

  function logout() {
    localStorage.removeItem('token')
    navigate('/')
  }

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <p className="text-muted-foreground">Loading…</p>
      </div>
    )
  }

  const nav = [
    { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/proxy', label: 'Proxy', icon: Link2 },
    { to: '/domains', label: 'Domains', icon: Globe },
    { to: '/core', label: 'Core', icon: Server },
    { to: '/settings', label: 'Settings', icon: Settings },
  ]

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-card overflow-hidden">
        <div className="p-4 shrink-0 border-b border-border/50">
          <AppLogo showName size="md" />
        </div>
        <nav className="flex flex-1 flex-col gap-1 overflow-y-auto px-2">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/dashboard' || to === '/proxy'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-border p-3 shrink-0">
          <div className="mb-2 truncate text-sm text-muted-foreground">{user}</div>
          <Button variant="outline" size="sm" className="w-full" onClick={logout}>
            <LogOut className="mr-2 h-4 w-4" />
            Log out
          </Button>
        </div>
      </aside>
      <main className="flex-1 min-w-0 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}
