import { useEffect, useState } from 'react'
import { settings, subscription } from '../api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'

export default function Subscription() {
  const [subscriptionUrl, setSubscriptionUrl] = useState('')
  const [lastRefresh, setLastRefresh] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [messageSuccess, setMessageSuccess] = useState(false)

  useEffect(() => {
    settings.get().then((d) => {
      setSubscriptionUrl(d.subscription_url)
      setLastRefresh(d.last_refresh || '')
    }).finally(() => setLoading(false))
  }, [])

  async function handleSave() {
    setSaving(true)
    setMessage(null)
    try {
      await settings.update({ subscription_url: subscriptionUrl })
      setMessage('Settings saved.')
      setMessageSuccess(true)
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Save failed')
      setMessageSuccess(false)
    } finally {
      setSaving(false)
    }
  }

  async function handleRefresh() {
    setRefreshing(true)
    setMessage(null)
    try {
      await subscription.refresh()
      setMessage('Refresh started. Nodes will update in a moment.')
      setMessageSuccess(true)
      const d = await settings.get()
      setLastRefresh(d.last_refresh || '')
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Refresh failed')
      setMessageSuccess(false)
    } finally {
      setRefreshing(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-muted-foreground">Loading…</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Subscription</h1>
        <p className="text-muted-foreground">Subscription URL and refresh</p>
      </div>

      {message !== null && (
        <Alert variant={messageSuccess ? 'success' : 'destructive'}>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Subscription URL</CardTitle>
          <CardDescription>
            Base64-encoded list of share links (vmess, vless, trojan, ss). Refreshed every 1 minute.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="subscription-url">URL</Label>
            <Input
              id="subscription-url"
              type="url"
              value={subscriptionUrl}
              onChange={(e) => setSubscriptionUrl(e.target.value)}
              placeholder="https://…"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : 'Save settings'}
            </Button>
            <Button
              variant="secondary"
              onClick={handleRefresh}
              disabled={refreshing || !subscriptionUrl}
            >
              {refreshing ? 'Refreshing…' : 'Refresh now'}
            </Button>
          </div>
          {lastRefresh && (
            <p className="text-sm text-muted-foreground">Last refresh: {lastRefresh}</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
