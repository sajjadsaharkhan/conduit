import { useState } from 'react'
import { manual } from '../api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Alert, AlertDescription } from '@/components/ui/alert'

export default function Manual() {
  const [shareLink, setShareLink] = useState('')
  const [rawJson, setRawJson] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<'success' | string | null>(null)
  const [activeTab, setActiveTab] = useState<'link' | 'json'>('link')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setMessage(null)
    setSubmitting(true)
    try {
      if (activeTab === 'link') {
        await manual.apply(shareLink.trim(), undefined)
      } else {
        await manual.apply(undefined, rawJson.trim())
      }
      setMessage('success')
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Failed')
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit = activeTab === 'link' ? !!shareLink.trim() : !!rawJson.trim()

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Manual config</h1>
        <p className="text-muted-foreground">
          Paste a single share link (vmess://, vless://, trojan://, ss://) or raw outbound JSON to use without subscription.
        </p>
      </div>

      {message !== null && (
        <Alert variant={message === 'success' ? 'success' : 'destructive'}>
          <AlertDescription>
            {message === 'success' ? 'Config applied. Core restarted.' : message}
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Apply config</CardTitle>
          <CardDescription>Share link or raw JSON outbound</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit}>
            <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as 'link' | 'json')}>
              <TabsList>
                <TabsTrigger value="link">Share link</TabsTrigger>
                <TabsTrigger value="json">Raw JSON</TabsTrigger>
              </TabsList>
              <TabsContent value="link">
                <textarea
                  className="mt-3 flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 font-mono"
                  value={shareLink}
                  onChange={(e) => setShareLink(e.target.value)}
                  placeholder="vmess://… or vless://… or trojan://… or ss://…"
                  rows={3}
                />
              </TabsContent>
              <TabsContent value="json">
                <textarea
                  className="mt-3 flex min-h-[200px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 font-mono"
                  value={rawJson}
                  onChange={(e) => setRawJson(e.target.value)}
                  placeholder='{"type":"vless","server":"…",…}'
                  rows={8}
                />
              </TabsContent>
            </Tabs>
            <Button
              type="submit"
              className="mt-4"
              disabled={submitting || !canSubmit}
            >
              {submitting ? 'Applying…' : 'Apply'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
