import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Tooltip } from '@/components/ui/tooltip'
import { Checkbox } from '@/components/ui/checkbox'
import { Info, Eye, EyeOff } from 'lucide-react'
import { settings as settingsApi } from '../api'

export default function Settings() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const [proxyDisplayHost, setProxyDisplayHost] = useState('127.0.0.1')
  const [proxyDisplaySaving, setProxyDisplaySaving] = useState(false)
  const [proxyDisplayMsg, setProxyDisplayMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const [proxyUsername, setProxyUsername] = useState('')
  const [proxyPassword, setProxyPassword] = useState('')
  const [proxyAuthEnabled, setProxyAuthEnabled] = useState(false)
  const [showProxyPassword, setShowProxyPassword] = useState(false)
  const [proxyAuthSaving, setProxyAuthSaving] = useState(false)
  const [proxyAuthMsg, setProxyAuthMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    settingsApi.get().then((s) => {
      setProxyDisplayHost(s.proxy_display_host || '127.0.0.1')
      const u = (s.proxy_username || '').trim()
      const p = s.proxy_password || ''
      setProxyUsername(u)
      setProxyPassword(p)
      setProxyAuthEnabled(Boolean(u || p))
    }).catch(() => {})
  }, [])

  function setProxyAuthEnabledAndClear(checked: boolean) {
    setProxyAuthEnabled(checked)
    if (!checked) {
      setProxyUsername('')
      setProxyPassword('')
      setShowProxyPassword(false)
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault()
    if (newPassword !== confirmPassword) {
      setMessage({ type: 'error', text: 'New passwords do not match.' })
      return
    }
    if (newPassword.length < 6) {
      setMessage({ type: 'error', text: 'New password must be at least 6 characters.' })
      return
    }
    setSaving(true)
    setMessage(null)
    try {
      await fetch('/api/settings/password', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      }).then((r) => {
        if (!r.ok) return r.json().then((d) => { throw new Error(d.detail || 'Failed') })
        return r.json()
      })
      setMessage({ type: 'success', text: 'Password updated.' })
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (e) {
      setMessage({ type: 'error', text: e instanceof Error ? e.message : 'Failed' })
    } finally {
      setSaving(false)
    }
  }

  async function handleSaveProxyDisplayHost(e: React.FormEvent) {
    e.preventDefault()
    setProxyDisplaySaving(true)
    setProxyDisplayMsg(null)
    try {
      await settingsApi.update({ proxy_display_host: proxyDisplayHost.trim() || '127.0.0.1' })
      setProxyDisplayMsg({ type: 'success', text: 'Proxy display host saved.' })
    } catch {
      setProxyDisplayMsg({ type: 'error', text: 'Failed to save.' })
    } finally {
      setProxyDisplaySaving(false)
    }
  }

  async function handleSaveProxyAuth(e: React.FormEvent) {
    e.preventDefault()
    setProxyAuthSaving(true)
    setProxyAuthMsg(null)
    try {
      await settingsApi.update({
        proxy_username: proxyAuthEnabled ? proxyUsername.trim() : '',
        proxy_password: proxyAuthEnabled ? proxyPassword : '',
      })
      setProxyAuthMsg({ type: 'success', text: 'Proxy authentication saved. Config has been reapplied.' })
    } catch {
      setProxyAuthMsg({ type: 'error', text: 'Failed to save.' })
    } finally {
      setProxyAuthSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Password, account, and display options</p>
      </div>

      {message !== null && (
        <Alert variant={message.type === 'success' ? 'success' : 'destructive'}>
          <AlertDescription>{message.text}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">
        <Card className="h-full flex flex-col">
          <CardHeader>
            <div className="flex items-center gap-1.5">
              <CardTitle>Proxy display host</CardTitle>
              <Tooltip
                content="Used only in the Dashboard 'How to use the proxy' panel. Set your server IP or hostname so the instructions show the correct address."
                side="top"
              >
                <span className="text-muted-foreground cursor-help inline-flex">
                  <Info className="h-4 w-4" />
                </span>
              </Tooltip>
            </div>
            <CardDescription>Host or IP shown in Dashboard proxy instructions (e.g. 127.0.0.1 or your server IP)</CardDescription>
          </CardHeader>
          <CardContent className="flex-1 flex flex-col">
            {proxyDisplayMsg !== null && (
              <Alert variant={proxyDisplayMsg.type === 'success' ? 'success' : 'destructive'} className="mb-4">
                <AlertDescription>{proxyDisplayMsg.text}</AlertDescription>
              </Alert>
            )}
            <form onSubmit={handleSaveProxyDisplayHost} className="flex flex-wrap items-end gap-3">
              <div className="flex-1 min-w-[140px] space-y-2">
                <Label htmlFor="proxy-display-host">Host or IP</Label>
                <Input
                  id="proxy-display-host"
                  type="text"
                  placeholder="127.0.0.1"
                  value={proxyDisplayHost}
                  onChange={(e) => setProxyDisplayHost(e.target.value)}
                />
              </div>
              <Button type="submit" disabled={proxyDisplaySaving}>
                {proxyDisplaySaving ? 'Saving…' : 'Save'}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card className="h-full flex flex-col">
          <CardHeader>
            <div className="flex items-center gap-1.5">
              <CardTitle>Proxy authentication</CardTitle>
              <Tooltip
                content="Optional username and password for the HTTP and SOCKS5 proxies. Used by both sing-box and Xray."
                side="top"
              >
                <span className="text-muted-foreground cursor-help inline-flex">
                  <Info className="h-4 w-4" />
                </span>
              </Tooltip>
            </div>
            <CardDescription>Require username and password to use the HTTP and SOCKS5 proxies.</CardDescription>
          </CardHeader>
          <CardContent className="flex-1 flex flex-col">
            {proxyAuthMsg !== null && (
              <Alert variant={proxyAuthMsg.type === 'success' ? 'success' : 'destructive'} className="mb-4">
                <AlertDescription>{proxyAuthMsg.text}</AlertDescription>
              </Alert>
            )}
            <form onSubmit={handleSaveProxyAuth} className="flex flex-col gap-4 flex-1">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="proxy-auth-enabled"
                  checked={proxyAuthEnabled}
                  onCheckedChange={setProxyAuthEnabledAndClear}
                />
                <Label htmlFor="proxy-auth-enabled" className="cursor-pointer font-normal">
                  Enable proxy authentication
                </Label>
              </div>
              <div className="flex flex-wrap items-end gap-4">
                <div className="min-w-[140px] space-y-2">
                  <Label htmlFor="proxy-username" className={!proxyAuthEnabled ? 'text-muted-foreground' : ''}>Username</Label>
                  <Input
                    id="proxy-username"
                    type="text"
                    placeholder="(optional)"
                    value={proxyUsername}
                    onChange={(e) => setProxyUsername(e.target.value)}
                    autoComplete="off"
                    disabled={!proxyAuthEnabled}
                  />
                </div>
                <div className="min-w-[140px] space-y-2">
                  <Label htmlFor="proxy-password" className={!proxyAuthEnabled ? 'text-muted-foreground' : ''}>Password</Label>
                  <div className="relative">
                    <Input
                      id="proxy-password"
                      type={showProxyPassword ? 'text' : 'password'}
                      placeholder="(optional)"
                      value={proxyPassword}
                      onChange={(e) => setProxyPassword(e.target.value)}
                      autoComplete="off"
                      className="pr-9"
                      disabled={!proxyAuthEnabled}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground disabled:opacity-50"
                      onClick={() => setShowProxyPassword((v) => !v)}
                      aria-label={showProxyPassword ? 'Hide password' : 'Show password'}
                      disabled={!proxyAuthEnabled}
                    >
                      {showProxyPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </Button>
                  </div>
                </div>
                <Button type="submit" disabled={proxyAuthSaving}>
                  {proxyAuthSaving ? 'Saving…' : 'Save'}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Change password</CardTitle>
          <CardDescription>Update your admin password</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleChangePassword} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="current-password">Current password</Label>
              <Input
                id="current-password"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                autoComplete="current-password"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-password">New password</Label>
              <Input
                id="new-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm-password">Confirm new password</Label>
              <Input
                id="confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
              />
            </div>
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving…' : 'Update password'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
