import { useEffect, useState } from 'react'
import { settings, nodes as nodesApi, status as statusApi, type Multiplex } from '../api'
import { ProxyEndpoints } from '@/components/ProxyEndpoints'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Pencil, Trash2, Plus, Info, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'

type Node = { id: number; source: string; raw_link: string; name: string; latency_ms: number | null; real_latency_ms: number | null; last_check: string | null; multiplex: Multiplex }
type NodeMode = 'manual' | 'auto'

const MULTIPLEX_OPTIONS: { value: Multiplex; label: string }[] = [
  { value: 'off', label: 'Off' },
  { value: 'h2mux', label: 'h2mux' },
  { value: 'smux', label: 'smux' },
  { value: 'yamux', label: 'yamux' },
]

export default function Proxy() {
  const [loading, setLoading] = useState(true)
  const [pinging, setPinging] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [messageSuccess, setMessageSuccess] = useState(false)

  const [list, setList] = useState<Node[]>([])
  const [selectedRaw, setSelectedRaw] = useState('')
  const [selecting, setSelecting] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [deleteModal, setDeleteModal] = useState<{ id: number; name: string } | null>(null)
  const [editModal, setEditModal] = useState<Node | null>(null)
  const [editRawLink, setEditRawLink] = useState('')
  const [editMultiplex, setEditMultiplex] = useState<Multiplex>('off')
  const [nodeMode, setNodeMode] = useState<NodeMode>('manual')
  const [savingMode, setSavingMode] = useState(false)
  const [updating, setUpdating] = useState(false)

  const [manualOpen, setManualOpen] = useState(false)
  const [manualShareLink, setManualShareLink] = useState('')
  const [manualRawJson, setManualRawJson] = useState('')
  const [manualTab, setManualTab] = useState<'link' | 'json'>('link')
  const [manualActivate, setManualActivate] = useState(true)
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
  const [proxyStatus, setProxyStatus] = useState<Awaited<ReturnType<typeof statusApi.get>> | null>(null)

  function loadSettings() {
    settings.get().then((d) => setSelectedRaw(d.selected_node_raw || '')).catch(() => {})
  }

  function load() {
    setLoading(true)
    statusApi.get().then(setProxyStatus).catch(() => {})
    Promise.all([settings.get(), nodesApi.list()]).then(([setRes, nodesRes]) => {
      setList(nodesRes.nodes)
      setNodeMode(setRes.node_mode || 'manual')
      setSelectedRaw(setRes.selected_node_raw || '')
    }).finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  async function handleModeChange(mode: NodeMode) {
    if (mode === nodeMode) return
    setSavingMode(true)
    setMessage(null)
    try {
      await settings.update({ node_mode: mode })
      setNodeMode(mode)
      setMessage(
        mode === 'auto'
          ? 'Auto mode on: the fastest node is picked by real delay every minute. Core restarted.'
          : 'Manual mode on: you pick the node; switching is live. Core restarted.',
      )
      setMessageSuccess(true)
      load()
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Failed to change mode')
      setMessageSuccess(false)
    } finally {
      setSavingMode(false)
    }
  }

  async function handlePingAll() {
    setPinging(true)
    setMessage(null)
    try {
      const res = await nodesApi.ping()
      const byId = new Map(res.results.map((r) => [r.id, r.latency_ms]))
      setList((prev) => prev.map((n) => (byId.has(n.id) ? { ...n, latency_ms: byId.get(n.id) ?? null } : n)))
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Ping failed')
      setMessageSuccess(false)
    } finally {
      setPinging(false)
    }
  }

  async function handleSelect(node: Node) {
    setSelecting(node.raw_link)
    setMessage(null)
    try {
      const res = await nodesApi.select(node.raw_link, node.id)
      setSelectedRaw(node.raw_link)
      statusApi.get().then(setProxyStatus).catch(() => {})
      setMessage(res.live ? 'Switched live. Open connections were kept.' : 'Node selected and core restarted.')
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
    setEditMultiplex(node.multiplex || 'off')
  }

  async function handleUpdateNode() {
    if (!editModal) return
    setUpdating(true)
    setMessage(null)
    try {
      const rawLink = editRawLink.trim()
      await nodesApi.update(editModal.id, {
        raw_link: rawLink !== editModal.raw_link ? rawLink : undefined,
        multiplex: editMultiplex !== editModal.multiplex ? editMultiplex : undefined,
      })
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

  function displayLatency(n: Node): { text: string; failed: boolean } {
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

  async function handleManualSubmit(e: React.FormEvent) {
    e.preventDefault()
    setManualMessage(null)
    setManualSubmitting(true)
    try {
      await nodesApi.add(
        manualTab === 'link'
          ? { share_link: manualShareLink.trim(), activate: manualActivate }
          : { raw_json: manualRawJson.trim(), activate: manualActivate },
      )
      setMessage(manualActivate ? 'Node added and in use. Core restarted.' : 'Node added.')
      setMessageSuccess(true)
      setManualOpen(false)
      setManualShareLink('')
      setManualRawJson('')
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
        <p className="text-muted-foreground">Endpoints and nodes</p>
      </div>

      {message !== null && (
        <Alert variant={messageSuccess ? 'success' : 'destructive'}>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      )}

      {proxyStatus && (
        <ProxyEndpoints
          ports={proxyStatus}
          host={proxyStatus.proxy_display_host || '127.0.0.1'}
          username={(proxyStatus.proxy_username || '').trim()}
          password={proxyStatus.proxy_password || ''}
          nodeSelected={Boolean(selectedRaw)}
        />
      )}

      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
          <div className="space-y-3">
          <div className="flex items-center gap-1.5">
            <CardTitle>Nodes</CardTitle>
            <Tooltip
              content="Add nodes with +, then choose which one to use. Ping measures TCP connect time from this server; Test measures real latency and speed through the node."
              side="top"
            >
              <span className="shrink-0 text-muted-foreground cursor-help inline-flex">
                <Info className="h-4 w-4" />
              </span>
            </Tooltip>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div role="group" aria-label="Node selection mode" className="inline-flex rounded-md bg-background p-0.5 ring-1 ring-border">
              {(['manual', 'auto'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  aria-pressed={nodeMode === m}
                  disabled={savingMode}
                  onClick={() => handleModeChange(m)}
                  className={cn(
                    'min-h-9 rounded px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50',
                    nodeMode === m ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {m === 'manual' ? 'Manual' : 'Auto (fastest)'}
                </button>
              ))}
            </div>
            <p className="text-sm text-muted-foreground">
              {nodeMode === 'manual'
                ? 'You choose the node. Switching is live on sing-box: open connections are kept.'
                : 'The core measures real delay through every node each minute and uses the fastest.'}
            </p>
          </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={handlePingAll} disabled={pinging || list.length === 0}>
              {pinging ? 'Pinging…' : 'Ping all'}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={async () => {
                setTestingAllNodes(true)
                for (const node of list) {
                  await handleNodeLatencyTest(node)
                }
                setTestingAllNodes(false)
              }}
              disabled={testingAllNodes || list.length === 0}
            >
              {testingAllNodes ? 'Testing…' : 'Test all'}
            </Button>
            <Button onClick={() => setManualOpen(true)} size="icon" variant="outline" aria-label="Add node" title="Add node">
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
                        content="Real latency from Test when available, otherwise TCP connect time from Ping. Click to sort (fastest first); failed (-1) always at end."
                        side="top"
                      >
                        <span className="text-muted-foreground cursor-help" onClick={(e) => e.stopPropagation()}>
                          <Info className="h-3.5 w-3.5" />
                        </span>
                      </Tooltip>
                    </button>
                  </TableHead>
                  <TableHead className="w-[280px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={3} className="text-center text-muted-foreground">
                      No nodes yet. Add a share link or outbound JSON with +.
                    </TableCell>
                  </TableRow>
                )}
                {sortByLatency(list).map((n) => {
                  const isCurrent = proxyStatus?.active_node_id != null ? proxyStatus.active_node_id === n.id : selectedRaw === n.raw_link
                  const latency = displayLatency(n)
                  const test = nodeTestResults[n.id]
                  return (
                    <TableRow
                      key={n.id}
                      className={cn(isCurrent && 'bg-primary/10 border-l-4 border-l-primary')}
                    >
                      <TableCell className="font-mono text-sm max-w-[240px] truncate">
                        {n.name || n.raw_link.slice(0, 40)}
                        {isCurrent && (
                          <span className="ml-2 text-xs font-medium text-primary">(current)</span>
                        )}
                        {n.multiplex !== 'off' && (
                          <span className="ml-2 rounded bg-muted px-1.5 py-0.5 font-sans text-[11px] font-medium text-muted-foreground" title="Connection pooling to this node">
                            MUX {n.multiplex}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <span className={cn('inline-flex items-center gap-1', latency.failed && 'text-destructive font-medium')}>
                          {latency.text}
                          <Tooltip
                            content={
                              <div className="space-y-1">
                                <div>Real: {n.real_latency_ms != null ? `${n.real_latency_ms} ms` : '—'}</div>
                                <div>TCP: {n.latency_ms != null ? `${n.latency_ms} ms` : '—'}</div>
                                {test ? (
                                  <>
                                    <div>Last test — Latency: {test.latency_ms === -1 ? 'Failed' : `${test.latency_ms ?? '—'} ms`}</div>
                                    <div>Duration: {test.duration_ms != null ? `${test.duration_ms} ms` : '—'}</div>
                                    <div>Speed: {test.download_speed_kbps != null ? `${test.download_speed_kbps} Kbps` : '—'}</div>
                                    <div>Size: {test.size_bytes} B</div>
                                  </>
                                ) : (
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
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => handleSelect(n)}
                            disabled={selecting !== null || nodeMode === 'auto'}
                            title={nodeMode === 'auto' ? 'Auto mode picks the fastest node; switch to Manual to choose' : 'Use this node'}
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
                            aria-label="Edit node"
                            title="Edit node"
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => openDeleteModal(n)}
                            disabled={deleting !== null}
                            aria-label="Delete node"
                            title="Delete node"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

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
            <DialogTitle>Edit node</DialogTitle>
            <DialogDescription>
              Change the share link or connection pooling. Saving rebuilds the config and restarts the core.
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
          <div className="space-y-2">
            <Label htmlFor="edit-multiplex">Multiplex (connection pooling)</Label>
            <Select value={editMultiplex} onValueChange={(v) => setEditMultiplex(v as Multiplex)}>
              <SelectTrigger id="edit-multiplex" className="w-[160px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MULTIPLEX_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Reuses a few warm connections to the node instead of a new handshake per request, which cuts
              latency for many short requests. The node&apos;s server must have multiplex enabled with the same
              protocol (Xray servers: any value turns on Xray mux). Ignored for XTLS Vision nodes. Can slow large
              downloads, so measure with Test.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditModal(null)}>
              Cancel
            </Button>
            <Button onClick={handleUpdateNode} disabled={updating || !editRawLink.trim()}>
              {updating ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Manual config modal */}
      <Dialog open={manualOpen} onOpenChange={setManualOpen}>
        <DialogContent className="max-w-2xl" showClose={true}>
          <DialogHeader>
            <DialogTitle>Add node</DialogTitle>
            <DialogDescription>
              Paste a share link or a raw outbound JSON. Adding a link that is already in the list updates it.
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
            <div className="mt-4 flex items-center gap-2">
              <Checkbox id="add-node-activate" checked={manualActivate} onCheckedChange={setManualActivate} />
              <Label htmlFor="add-node-activate" className="cursor-pointer text-sm font-normal">
                Use this node now
              </Label>
            </div>
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
                {manualSubmitting ? 'Adding…' : manualActivate ? 'Add & use' : 'Add'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
