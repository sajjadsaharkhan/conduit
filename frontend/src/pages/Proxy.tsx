import { useEffect, useState } from 'react'
import { settings, subscription, nodes as nodesApi, manual } from '../api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { Link2, Server, Pencil, Trash2, Plus, Info, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'

type Node = { id: number; source: string; raw_link: string; name: string; latency_ms: number | null; real_latency_ms: number | null; last_check: string | null }

export default function Proxy() {
  const [tab, setTab] = useState('nodes')
  const [subscriptionUrl, setSubscriptionUrl] = useState('')
  const [lastRefresh, setLastRefresh] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [messageSuccess, setMessageSuccess] = useState(false)

  const [list, setList] = useState<Node[]>([])
  const [selectedRaw, setSelectedRaw] = useState('')
  const [selecting, setSelecting] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [deleteModal, setDeleteModal] = useState<{ id: number; name: string } | null>(null)
  const [editModal, setEditModal] = useState<Node | null>(null)
  const [editRawLink, setEditRawLink] = useState('')
  const [updating, setUpdating] = useState(false)

  const [manualOpen, setManualOpen] = useState(false)
  const [manualShareLink, setManualShareLink] = useState('')
  const [manualRawJson, setManualRawJson] = useState('')
  const [manualTab, setManualTab] = useState<'link' | 'json'>('link')
  const [manualSubmitting, setManualSubmitting] = useState(false)
  const [manualMessage, setManualMessage] = useState<string | null>(null)
  const [testingNodeId, setTestingNodeId] = useState<number | null>(null)
  const [nodeTestResults, setNodeTestResults] = useState<Record<number, {
    latency_ms: number | null
    duration_ms: number | null
    download_speed_kbps: number | null
    size_bytes: number
  }>>({})
  const [testingAllNodes, setTestingAllNodes] = useState(false)
  const [latencySort, setLatencySort] = useState<'asc' | 'desc' | null>(null)

  function loadSettings() {
    settings.get().then((d) => {
      setSubscriptionUrl(d.subscription_url)
      setLastRefresh(d.last_refresh || '')
    }).catch(() => {})
  }

  function load() {
    setLoading(true)
    Promise.all([settings.get(), nodesApi.list()]).then(([setRes, nodesRes]) => {
      setSubscriptionUrl(setRes.subscription_url)
      setLastRefresh(setRes.last_refresh || '')
      setList(nodesRes.nodes)
      setSelectedRaw(setRes.selected_node_raw || '')
    }).finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  async function handleSaveSubscription() {
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
      load()
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Refresh failed')
      setMessageSuccess(false)
    } finally {
      setRefreshing(false)
    }
  }

  async function handleSelect(raw_link: string) {
    setSelecting(raw_link)
    setMessage(null)
    try {
      await nodesApi.select(raw_link)
      setSelectedRaw(raw_link)
      setMessage('Node selected and core restarted.')
      setMessageSuccess(true)
      loadSettings()
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Failed')
      setMessageSuccess(false)
    } finally {
      setSelecting(null)
    }
  }

  function openDeleteModal(node: Node) {
    setDeleteModal({ id: node.id, name: node.name || node.raw_link.slice(0, 40) })
  }

  async function handleDelete(id: number) {
    setDeleting(id)
    setMessage(null)
    setDeleteModal(null)
    try {
      await nodesApi.delete(id)
      setMessage('Node deleted.')
      setMessageSuccess(true)
      load()
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Failed to delete')
      setMessageSuccess(false)
    } finally {
      setDeleting(null)
    }
  }

  function openEditModal(node: Node) {
    setEditModal(node)
    setEditRawLink(node.raw_link)
  }

  async function handleUpdateNode() {
    if (!editModal) return
    setUpdating(true)
    setMessage(null)
    try {
      await nodesApi.update(editModal.id, editRawLink.trim())
      setMessage('Node updated.')
      setMessageSuccess(true)
      setEditModal(null)
      load()
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Failed to update')
      setMessageSuccess(false)
    } finally {
      setUpdating(false)
    }
  }

  async function handleNodeLatencyTest(node: Node) {
    setTestingNodeId(node.id)
    try {
      const res = await nodesApi.latencyTest(node.raw_link, node.id)
      setNodeTestResults((prev) => ({
        ...prev,
        [node.id]: {
          latency_ms: res.success ? res.latency_ms : -1,
          duration_ms: res.success ? res.duration_ms : null,
          download_speed_kbps: res.success ? res.download_speed_kbps : null,
          size_bytes: res.success ? res.size_bytes : 0,
        },
      }))
      if (res.success && res.latency_ms != null) {
        setList((prev) =>
          prev.map((n) => (n.id === node.id ? { ...n, real_latency_ms: res.latency_ms } : n))
        )
      }
    } catch {
      setNodeTestResults((prev) => ({
        ...prev,
        [node.id]: {
          latency_ms: -1,
          duration_ms: null,
          download_speed_kbps: null,
          size_bytes: 0,
        },
      }))
    } finally {
      setTestingNodeId(null)
    }
  }

  function latencySortKey(n: Node): number | null {
    const r = nodeTestResults[n.id]
    if (r != null && r.latency_ms != null && r.latency_ms >= 0) return r.latency_ms
    if (n.real_latency_ms != null && n.real_latency_ms >= 0) return n.real_latency_ms
    if (n.latency_ms != null && n.latency_ms >= 0) return n.latency_ms
    return null
  }

  function sortByLatency<T extends Node>(arr: T[]): T[] {
    if (!latencySort) return arr
    const valid: T[] = []
    const invalid: T[] = []
    for (const n of arr) {
      if (latencySortKey(n) !== null) valid.push(n)
      else invalid.push(n)
    }
    valid.sort((a, b) => {
      const ka = latencySortKey(a)!
      const kb = latencySortKey(b)!
      return latencySort === 'asc' ? ka - kb : kb - ka
    })
    return [...valid, ...invalid]
  }

  async function handleManualSubmit(e: React.FormEvent) {
    e.preventDefault()
    setManualMessage(null)
    setManualSubmitting(true)
    try {
      if (manualTab === 'link') {
        await manual.apply(manualShareLink.trim(), undefined)
      } else {
        await manual.apply(undefined, manualRawJson.trim())
      }
      setManualMessage('Config applied. Core restarted.')
      setManualOpen(false)
      load()
    } catch (e) {
      setManualMessage(e instanceof Error ? e.message : 'Failed')
    } finally {
      setManualSubmitting(false)
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
        <h1 className="text-3xl font-bold tracking-tight">Proxy</h1>
        <p className="text-muted-foreground">Subscription, nodes, and manual config</p>
      </div>

      {message !== null && (
        <Alert variant={messageSuccess ? 'success' : 'destructive'}>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="nodes">
            <Server className="mr-2 h-4 w-4" />
            Nodes
          </TabsTrigger>
          <TabsTrigger value="subscription">
            <Link2 className="mr-2 h-4 w-4" />
            Subscription
          </TabsTrigger>
        </TabsList>

        <TabsContent value="subscription" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Subscription URL</CardTitle>
              <CardDescription>
                Base64-encoded list of share links. Update URL and save, then refresh to fetch nodes.
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
                <Button onClick={handleSaveSubscription} disabled={saving}>
                  {saving ? 'Saving…' : 'Update subscription URL'}
                </Button>
                <Button variant="secondary" onClick={handleRefresh} disabled={refreshing || !subscriptionUrl}>
                  {refreshing ? 'Refreshing…' : 'Refresh now'}
                </Button>
              </div>
              {lastRefresh && (
                <p className="text-sm text-muted-foreground">Last refresh: {lastRefresh}</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="nodes" className="mt-6">
          <Card>
            <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
              <div className="flex items-center gap-1.5">
                <CardTitle>Node list</CardTitle>
                <Tooltip
                  content="Best node by latency is auto-selected periodically. Select a node or edit/delete. Use Test to run a real latency/speed check for that node. Add manual config with +."
                  side="top"
                >
                  <span className="shrink-0 text-muted-foreground cursor-help inline-flex">
                    <Info className="h-4 w-4" />
                  </span>
                </Tooltip>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={async () => {
                    setTestingAllNodes(true)
                    for (const node of list) {
                      try {
                        const res = await nodesApi.latencyTest(node.raw_link, node.id)
                        setNodeTestResults((prev) => ({
                          ...prev,
                          [node.id]: {
                            latency_ms: res.success ? res.latency_ms : -1,
                            duration_ms: res.success ? res.duration_ms : null,
                            download_speed_kbps: res.success ? res.download_speed_kbps : null,
                            size_bytes: res.success ? res.size_bytes : 0,
                          },
                        }))
                      } catch {
                        setNodeTestResults((prev) => ({
                          ...prev,
                          [node.id]: {
                            latency_ms: -1,
                            duration_ms: null,
                            download_speed_kbps: null,
                            size_bytes: 0,
                          },
                        }))
                      }
                    }
                    setTestingAllNodes(false)
                  }}
                  disabled={testingAllNodes || list.length === 0}
                >
                  {testingAllNodes ? 'Testing…' : 'Test all'}
                </Button>
                <Button onClick={() => setManualOpen(true)} size="icon" variant="outline" title="Add manual config">
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="rounded-md border border-border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 hover:opacity-80 focus:outline-none focus:ring-2 focus:ring-ring rounded"
                          onClick={() => setLatencySort((s) => (s === 'asc' ? 'desc' : s === 'desc' ? null : 'asc'))}
                        >
                          Latency (ms)
                          {latencySort === 'asc' && <ArrowUp className="h-3.5 w-3.5" />}
                          {latencySort === 'desc' && <ArrowDown className="h-3.5 w-3.5" />}
                          {latencySort === null && <ArrowUpDown className="h-3.5 w-3.5 text-muted-foreground" />}
                          <Tooltip
                            content="TCP connect latency (from subscription). Use Test for real latency/speed. Click to sort (fastest first); failed (-1) always at end."
                            side="top"
                          >
                            <span className="text-muted-foreground cursor-help" onClick={(e) => e.stopPropagation()}>
                              <Info className="h-3.5 w-3.5" />
                            </span>
                          </Tooltip>
                        </button>
                      </TableHead>
                      <TableHead>Source</TableHead>
                      <TableHead className="w-[280px]">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {list.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={4} className="text-center text-muted-foreground">
                          No nodes. Add a subscription URL and refresh.
                        </TableCell>
                      </TableRow>
                    )}
                    {(() => {
                      const subscriptionNodes = sortByLatency(list.filter((n) => n.source === 'subscription'))
                      const manualNodes = sortByLatency(list.filter((n) => n.source === 'manual'))
                      const displayLatency = (n: Node) => {
                        const r = nodeTestResults[n.id]
                        if (r != null) {
                          if (r.latency_ms === -1) return { text: '-1', failed: true }
                          return { text: String(r.latency_ms ?? '—'), failed: false }
                        }
                        // Prefer real latency (via proxy) over TCP
                        if (n.real_latency_ms != null && n.real_latency_ms >= 0) return { text: String(n.real_latency_ms), failed: false }
                        if (n.latency_ms != null && n.latency_ms >= 0) return { text: `${n.latency_ms} (TCP)`, failed: false }
                        return { text: '—', failed: false }
                      }
                      return (
                        <>
                          {subscriptionNodes.map((n) => (
                            <TableRow
                              key={n.id}
                              className={cn(
                                selectedRaw === n.raw_link && 'bg-primary/10 border-l-4 border-l-primary'
                              )}
                            >
                              <TableCell className="font-mono text-sm max-w-[200px] truncate">
                                {n.name || n.raw_link.slice(0, 40)}
                                {selectedRaw === n.raw_link && (
                                  <span className="ml-2 text-xs font-medium text-primary">(current)</span>
                                )}
                              </TableCell>
                              <TableCell>
                                <span className={cn('inline-flex items-center gap-1', displayLatency(n).failed && 'text-destructive font-medium')}>
                                  {displayLatency(n).text}
                                  <Tooltip
                                    content={
                                      <div className="space-y-1">
                                        <div>Real: {n.real_latency_ms != null ? `${n.real_latency_ms} ms` : '—'}</div>
                                        <div>TCP: {n.latency_ms != null ? `${n.latency_ms} ms` : '—'}</div>
                                        {nodeTestResults[n.id] && (
                                          <>
                                            <div>Last test — Latency: {nodeTestResults[n.id].latency_ms === -1 ? 'Failed' : `${nodeTestResults[n.id].latency_ms ?? '—'} ms`}</div>
                                            <div>Duration: {nodeTestResults[n.id].duration_ms != null ? `${nodeTestResults[n.id].duration_ms} ms` : '—'}</div>
                                            <div>Speed: {nodeTestResults[n.id].download_speed_kbps != null ? `${nodeTestResults[n.id].download_speed_kbps} Kbps` : '—'}</div>
                                            <div>Size: {nodeTestResults[n.id].size_bytes} B</div>
                                          </>
                                        )}
                                        {!nodeTestResults[n.id] && (
                                          <div className="text-muted-foreground">Click Test for real latency/speed</div>
                                        )}
                                      </div>
                                    }
                                    side="top"
                                  >
                                    <span className="text-muted-foreground cursor-help inline-flex">
                                      <Info className="h-3.5 w-3.5" />
                                    </span>
                                  </Tooltip>
                                </span>
                              </TableCell>
                              <TableCell>{n.source}</TableCell>
                              <TableCell>
                                <div className="flex flex-wrap items-center gap-2">
                                  <Button
                                    size="sm"
                                    variant="secondary"
                                    onClick={() => handleSelect(n.raw_link)}
                                    disabled={selecting !== null}
                                  >
                                    {selecting === n.raw_link ? '…' : 'Use'}
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => handleNodeLatencyTest(n)}
                                    disabled={testingNodeId !== null || testingAllNodes}
                                    title="Real latency/speed test via proxy"
                                  >
                                    {testingNodeId === n.id ? '…' : 'Test'}
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => openEditModal(n)}
                                    disabled={updating}
                                    title="Edit share link"
                                  >
                                    <Pencil className="h-4 w-4" />
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="destructive"
                                    onClick={() => openDeleteModal(n)}
                                    disabled={deleting !== null}
                                    title="Delete node"
                                  >
                                    <Trash2 className="h-4 w-4" />
                                  </Button>
                                </div>
                              </TableCell>
                            </TableRow>
                          ))}
                          {manualNodes.length > 0 && (
                            <>
                              <TableRow className="bg-muted/40 hover:bg-muted/40">
                                <TableCell colSpan={4} className="py-1.5 text-xs font-medium text-muted-foreground">
                                  Manual config
                                </TableCell>
                              </TableRow>
                              {manualNodes.map((n) => (
                                <TableRow
                                  key={n.id}
                                  className={cn(
                                    selectedRaw === n.raw_link && 'bg-primary/10 border-l-4 border-l-primary'
                                  )}
                                >
                                  <TableCell className="font-mono text-sm max-w-[200px] truncate">
                                    {n.name || n.raw_link.slice(0, 40)}
                                    {selectedRaw === n.raw_link && (
                                      <span className="ml-2 text-xs font-medium text-primary">(current)</span>
                                    )}
                                  </TableCell>
                                  <TableCell>
                                    <span className={cn('inline-flex items-center gap-1', displayLatency(n).failed && 'text-destructive font-medium')}>
                                      {displayLatency(n).text}
                                      <Tooltip
                                        content={
                                          <div className="space-y-1">
                                            <div>Real: {n.real_latency_ms != null ? `${n.real_latency_ms} ms` : '—'}</div>
                                            <div>TCP: {n.latency_ms != null ? `${n.latency_ms} ms` : '—'}</div>
                                            {nodeTestResults[n.id] && (
                                              <>
                                                <div>Last test — Latency: {nodeTestResults[n.id].latency_ms === -1 ? 'Failed' : `${nodeTestResults[n.id].latency_ms ?? '—'} ms`}</div>
                                                <div>Duration: {nodeTestResults[n.id].duration_ms != null ? `${nodeTestResults[n.id].duration_ms} ms` : '—'}</div>
                                                <div>Speed: {nodeTestResults[n.id].download_speed_kbps != null ? `${nodeTestResults[n.id].download_speed_kbps} Kbps` : '—'}</div>
                                                <div>Size: {nodeTestResults[n.id].size_bytes} B</div>
                                              </>
                                            )}
                                            {!nodeTestResults[n.id] && (
                                              <div className="text-muted-foreground">Click Test for real latency/speed</div>
                                            )}
                                          </div>
                                        }
                                        side="top"
                                      >
                                        <span className="text-muted-foreground cursor-help inline-flex">
                                          <Info className="h-3.5 w-3.5" />
                                        </span>
                                      </Tooltip>
                                    </span>
                                  </TableCell>
                                  <TableCell>{n.source}</TableCell>
                                  <TableCell>
                                    <div className="flex flex-wrap items-center gap-2">
                                      <Button
                                        size="sm"
                                        variant="secondary"
                                        onClick={() => handleSelect(n.raw_link)}
                                        disabled={selecting !== null}
                                      >
                                        {selecting === n.raw_link ? '…' : 'Use'}
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => handleNodeLatencyTest(n)}
                                        disabled={testingNodeId !== null || testingAllNodes}
                                        title="Real latency/speed test via proxy"
                                      >
                                        {testingNodeId === n.id ? '…' : 'Test'}
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => openEditModal(n)}
                                        disabled={updating}
                                        title="Edit share link"
                                      >
                                        <Pencil className="h-4 w-4" />
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="destructive"
                                        onClick={() => openDeleteModal(n)}
                                        disabled={deleting !== null}
                                        title="Delete node"
                                      >
                                        <Trash2 className="h-4 w-4" />
                                      </Button>
                                    </div>
                                  </TableCell>
                                </TableRow>
                              ))}
                            </>
                          )}
                        </>
                      )
                    })()}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Delete confirmation modal */}
      <Dialog open={!!deleteModal} onOpenChange={(open) => !open && setDeleteModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete node?</DialogTitle>
            <DialogDescription>
              This will remove &quot;{deleteModal?.name}&quot; from the list. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteModal(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteModal && handleDelete(deleteModal.id)}
              disabled={deleting !== null}
            >
              {deleting !== null ? 'Deleting…' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit node modal */}
      <Dialog open={!!editModal} onOpenChange={(open) => !open && setEditModal(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit share link</DialogTitle>
            <DialogDescription>
              Update the share link for this node. The node will be re-parsed and you may need to select it again.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="edit-raw-link">Share link</Label>
            <textarea
              id="edit-raw-link"
              className="flex min-h-[100px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={editRawLink}
              onChange={(e) => setEditRawLink(e.target.value)}
              placeholder="vmess://… or vless://…"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditModal(null)}>
              Cancel
            </Button>
            <Button onClick={handleUpdateNode} disabled={updating || !editRawLink.trim()}>
              {updating ? 'Updating…' : 'Update'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Manual config modal */}
      <Dialog open={manualOpen} onOpenChange={setManualOpen}>
        <DialogContent className="max-w-2xl" showClose={true}>
          <DialogHeader>
            <DialogTitle>Manual config</DialogTitle>
            <DialogDescription>
              Paste a share link or raw outbound JSON to use without subscription.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleManualSubmit}>
            <Tabs value={manualTab} onValueChange={(v) => setManualTab(v as 'link' | 'json')} className="mt-2">
              <TabsList>
                <TabsTrigger value="link">Share link</TabsTrigger>
                <TabsTrigger value="json">Raw JSON</TabsTrigger>
              </TabsList>
              <TabsContent value="link">
                <textarea
                  className="mt-3 flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                  value={manualShareLink}
                  onChange={(e) => setManualShareLink(e.target.value)}
                  placeholder="vmess://… or vless://…"
                  rows={3}
                />
              </TabsContent>
              <TabsContent value="json">
                <textarea
                  className="mt-3 flex min-h-[200px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                  value={manualRawJson}
                  onChange={(e) => setManualRawJson(e.target.value)}
                  placeholder='{"type":"vless","server":"…",…}'
                  rows={8}
                />
              </TabsContent>
            </Tabs>
            {manualMessage && (
              <Alert variant="destructive" className="mt-3">
                <AlertDescription>{manualMessage}</AlertDescription>
              </Alert>
            )}
            <DialogFooter className="mt-4">
              <Button type="button" variant="outline" onClick={() => setManualOpen(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={manualSubmitting || (manualTab === 'link' ? !manualShareLink.trim() : !manualRawJson.trim())}
              >
                {manualSubmitting ? 'Applying…' : 'Apply'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
