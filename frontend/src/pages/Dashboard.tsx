import { useEffect, useRef, useState } from 'react'
import { status as statusApi, core } from '../api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tooltip } from '@/components/ui/tooltip'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { cn } from '@/lib/utils'
import { Info, ArrowUp, ArrowDown, Network } from 'lucide-react'

const LOG_POLL_INTERVAL_MS = 1000
const STATUS_POLL_MS = 5000
const UPTIME_TICK_MS = 1000
const LOG_TAIL_OPTIONS = [100, 250, 500, 1000, 2000] as const

function formatUptime(seconds: number): string {
  const total = Math.floor(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return [h, m, s].map((n) => String(n).padStart(2, '0')).join(':')
}

function formatBytes(n: number | null): string {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`
  return `${(n / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

export default function Dashboard() {
  const [data, setData] = useState<Awaited<ReturnType<typeof statusApi.get>> | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000))
  const [logLines, setLogLines] = useState<string[]>([])
  const [logTail, setLogTail] = useState<number>(500)
  const [realLatencyTesting, setRealLatencyTesting] = useState(false)
  const logContainerRef = useRef<HTMLDivElement>(null)
  const realLatencyTestStartedForRef = useRef<string | null>(null)
  const httpPort = data?.http_port ?? 8080
  const socksPort = data?.socks_port ?? 1080
  const proxyHost = data?.proxy_display_host ?? '127.0.0.1'
  const proxyUser = (data?.proxy_username ?? '').trim()
  const proxyPass = data?.proxy_password ?? ''
  const hasProxyAuth = Boolean(proxyUser && proxyPass)
  const curlTestUrl = (data?.latency_test_domain || 'https://example.com').trim() || 'https://example.com'
  const httpProxyUrl = hasProxyAuth
    ? `http://${encodeURIComponent(proxyUser)}:${encodeURIComponent(proxyPass)}@${proxyHost}:${httpPort}`
    : `http://${proxyHost}:${httpPort}`
  const socksProxyUrl = hasProxyAuth
    ? `socks5://${encodeURIComponent(proxyUser)}:${encodeURIComponent(proxyPass)}@${proxyHost}:${socksPort}`
    : `socks5://${proxyHost}:${socksPort}`

  function loadStatus() {
    statusApi.get().then(setData).catch((e) => setErr(e.message)).finally(() => setLoading(false))
  }

  useEffect(() => {
    loadStatus()
  }, [])

  useEffect(() => {
    const id = setInterval(loadStatus, STATUS_POLL_MS)
    return () => clearInterval(id)
  }, [])

  // When we have a selected node and core is running but no real latency yet, run real test once; result streams in via status poll
  useEffect(() => {
    const raw = data?.selected_node_raw
    if (
      !data ||
      !data.core.running ||
      !raw ||
      data.selected_node_real_latency_ms != null ||
      realLatencyTestStartedForRef.current === raw
    ) {
      return
    }
    realLatencyTestStartedForRef.current = raw
    setRealLatencyTesting(true)
    core
      .latencyTest()
      .then(() => {
        loadStatus()
      })
      .catch(() => {})
      .finally(() => {
        setRealLatencyTesting(false)
      })
  }, [data?.core.running, data?.selected_node_raw, data?.selected_node_real_latency_ms])

  useEffect(() => {
    if (!data?.core.running || data.core.started_at == null) return
    const id = setInterval(() => setNow(Math.floor(Date.now() / 1000)), UPTIME_TICK_MS)
    return () => clearInterval(id)
  }, [data?.core.running, data?.core.started_at])

  useEffect(() => {
    let cancelled = false
    function poll() {
      core.logs(logTail).then((r) => {
        if (!cancelled) setLogLines(r.lines)
      }).catch(() => {})
    }
    poll()
    const id = setInterval(poll, LOG_POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [logTail])

  useEffect(() => {
    const el = logContainerRef.current
    if (!el) return
    // Only auto-scroll the log panel (not the page) when user is already near the bottom
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    if (atBottom) {
      el.scrollTop = el.scrollHeight
    }
  }, [logLines])

  const uptimeSeconds = data?.core.running && data.core.started_at != null
    ? Math.max(0, now - data.core.started_at)
    : 0

  const coreTypeLabel = data?.core_type === 'sing-box' ? 'Sing-box' : data?.core_type === 'xray' ? 'Xray' : data?.core_type || '—'

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-muted-foreground">Loading…</p>
      </div>
    )
  }
  if (err && !data) {
    return (
      <div className="space-y-4">
        <Alert variant="destructive">
          <AlertDescription>Error: {err}</AlertDescription>
        </Alert>
      </div>
    )
  }
  if (!data) return null

  const coreStatusLabel = data.core.running ? 'Running' : 'Stopped'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">Core status, current node, usage, and logs</p>
      </div>

      {err && (
        <Alert variant="destructive">
          <AlertDescription>{err}</AlertDescription>
        </Alert>
      )}

      {/* Row 1: Core status, Current node, Usage — same height */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="flex flex-col">
          <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
            <div className="flex items-center gap-1.5">
              <CardTitle className="text-base">Core status</CardTitle>
              <Tooltip
                content="Current proxy core process: type (sing-box or Xray), uptime since start, process ID, and run state. Use Core page to start, stop, or restart."
                side="top"
              >
                <span className="text-muted-foreground cursor-help inline-flex">
                  <Info className="h-4 w-4" />
                </span>
              </Tooltip>
            </div>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col gap-2 text-sm">
            <div className="flex justify-between items-center">
              <span className="text-muted-foreground">Type</span>
              <span
                className={cn(
                  'inline-flex shrink-0 rounded-md px-2.5 py-1 text-xs font-semibold ring-1 ring-inset',
                  data.core_type === 'sing-box' && 'bg-emerald-500/15 text-emerald-700 ring-emerald-500/30 dark:bg-emerald-500/20 dark:text-emerald-400 dark:ring-emerald-400/30',
                  data.core_type === 'xray' && 'bg-blue-500/15 text-blue-700 ring-blue-500/30 dark:bg-blue-500/20 dark:text-blue-400 dark:ring-blue-400/30',
                  data.core_type !== 'sing-box' && data.core_type !== 'xray' && 'bg-muted text-muted-foreground ring-border'
                )}
              >
                {coreTypeLabel}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Uptime</span>
              <span className="font-mono tabular-nums font-medium">
                {data.core.running ? formatUptime(uptimeSeconds) : '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Process ID</span>
              <span className="font-mono">{data.core.pid != null ? data.core.pid : '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Status</span>
              <span className={data.core.running ? 'font-medium text-emerald-600' : 'text-muted-foreground'}>
                {coreStatusLabel}
              </span>
            </div>
          </CardContent>
        </Card>

        <Card className="flex flex-col">
          <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
            <div className="flex items-center gap-1.5">
              <CardTitle className="text-base">Current node</CardTitle>
              <Tooltip
                content="The proxy node currently in use. Latency is from subscription check or last test. Last refresh is when the node list was updated."
                side="top"
              >
                <span className="text-muted-foreground cursor-help inline-flex">
                  <Info className="h-4 w-4" />
                </span>
              </Tooltip>
            </div>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col gap-2 text-sm">
            <div>
              <span className="text-muted-foreground block text-xs">Node name</span>
              <p className="font-medium truncate" title={data.selected_node_name || data.selected_node_raw || '—'}>
                {data.selected_node_name || data.selected_node_raw || '—'}
              </p>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Latency</span>
              <span className="font-mono">
                {realLatencyTesting
                  ? 'Testing…'
                  : data.selected_node_real_latency_ms != null
                    ? `${data.selected_node_real_latency_ms} ms`
                    : data.selected_node_latency_ms != null
                      ? `${data.selected_node_latency_ms} ms (TCP)`
                      : '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Last refresh</span>
              <span className="text-muted-foreground truncate pl-2 text-right">
                {data.last_refresh || '—'}
              </span>
            </div>
          </CardContent>
        </Card>

        <Card className="flex flex-col">
          <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
            <div className="flex items-center gap-1.5">
              <CardTitle className="text-base">Usage</CardTitle>
              <Tooltip
                content="Connections: open sockets of the core process. Upload/Download: from Xray when core is Xray; sing-box shows —."
                side="top"
              >
                <span className="text-muted-foreground cursor-help inline-flex">
                  <Info className="h-4 w-4" />
                </span>
              </Tooltip>
            </div>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col gap-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground inline-flex items-center gap-1.5">
                <Network className="h-3.5 w-3.5" />
                Connections
              </span>
              <span className="font-mono">{data.usage?.connections != null ? data.usage.connections : '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground inline-flex items-center gap-1.5">
                <ArrowUp className="h-3.5 w-3.5" />
                Upload
              </span>
              <span className="font-mono">{formatBytes(data.usage?.upload_bytes ?? null)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground inline-flex items-center gap-1.5">
                <ArrowDown className="h-3.5 w-3.5" />
                Download
              </span>
              <span className="font-mono">{formatBytes(data.usage?.download_bytes ?? null)}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* How to use the proxy */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-1.5">
            <CardTitle>How to use the proxy</CardTitle>
            <Tooltip
              content="Point your system or app at the proxy using the host and ports below. Use the server IP or hostname instead of 127.0.0.1 when this app runs on another machine."
              side="top"
            >
              <span className="text-muted-foreground cursor-help inline-flex">
                <Info className="h-4 w-4" />
              </span>
            </Tooltip>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/20 px-4 py-3">
            <span className="text-sm font-medium text-muted-foreground">Ports</span>
            <span className="inline-flex items-center gap-1.5 rounded-md bg-background px-2.5 py-1 font-mono text-sm ring-1 ring-border">
              HTTP <span className="font-semibold text-foreground">{httpPort}</span>
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md bg-background px-2.5 py-1 font-mono text-sm ring-1 ring-border">
              SOCKS5 <span className="font-semibold text-foreground">{socksPort}</span>
            </span>
            <Tooltip content="Change these in Settings; restart the core to apply." side="top">
              <span className="cursor-help text-muted-foreground">
                <Info className="h-3.5 w-3.5" />
              </span>
            </Tooltip>
          </div>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="linux" className="w-full">
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="linux">Linux</TabsTrigger>
              <TabsTrigger value="macos">macOS</TabsTrigger>
              <TabsTrigger value="windows">Windows</TabsTrigger>
              <TabsTrigger value="curl">curl</TabsTrigger>
            </TabsList>
            <TabsContent value="linux" className="mt-4">
              <ol className="list-inside list-decimal space-y-3 text-sm">
                <li>
                  <span className="text-muted-foreground">Terminal (current session): set env vars and run your app:</span>
                  <div className="mt-1.5 rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs">
                    <code className="block break-all">
                      export http_proxy={httpProxyUrl} https_proxy={httpProxyUrl}
                    </code>
                  </div>
                </li>
                <li>
                  <span className="text-muted-foreground">Or use GUI: Settings → Network → Proxy and set HTTP/HTTPS proxy to <code className="rounded bg-muted px-1">{proxyHost}</code>:{httpPort}{hasProxyAuth ? ` (username: ${proxyUser})` : ''}.</span>
                </li>
              </ol>
              <p className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
                <Tooltip content="Use your server IP or hostname when the proxy runs on a different machine." side="top">
                  <span className="cursor-help"><Info className="h-3.5 w-3.5" /></span>
                </Tooltip>
                Replace the host with the server IP if connecting from another device. You can set the display host in Settings.
              </p>
            </TabsContent>
            <TabsContent value="macos" className="mt-4">
              <ol className="list-inside list-decimal space-y-3 text-sm">
                <li>Open <strong>System Settings</strong> (or System Preferences) → <strong>Network</strong>.</li>
                <li>Select your connection (Wi‑Fi or Ethernet) → <strong>Details</strong> (or <strong>Advanced</strong>).</li>
                <li>Open the <strong>Proxies</strong> tab.</li>
                <li>Enable <strong>Web Proxy (HTTP)</strong> and <strong>Secure Web Proxy (HTTPS)</strong>.</li>
                <li>Set <strong>Web Proxy Server</strong> to <code className="rounded bg-muted px-1">{proxyHost}</code>, port <code className="rounded bg-muted px-1">{httpPort}</code>{hasProxyAuth ? <>; in proxy settings enter username <code className="rounded bg-muted px-1">{proxyUser}</code> and password</> : ''}.</li>
                <li>
                  <span className="text-muted-foreground">For SOCKS-only apps: enable <strong>SOCKS Proxy</strong>, server <code className="rounded bg-muted px-1">{proxyHost}</code>, port <code className="rounded bg-muted px-1">{socksPort}</code>{hasProxyAuth ? ` (use username ${proxyUser} and password)` : ''}.</span>
                  <Tooltip content="Some apps (e.g. terminal, IDE) use SOCKS; use this port for them." side="top">
                    <span className="ml-1 inline-flex cursor-help text-muted-foreground"><Info className="h-3.5 w-3.5" /></span>
                  </Tooltip>
                </li>
              </ol>
            </TabsContent>
            <TabsContent value="windows" className="mt-4">
              <ol className="list-inside list-decimal space-y-3 text-sm">
                <li>Open <strong>Settings</strong> → <strong>Network &amp; Internet</strong> → <strong>Proxy</strong> (or Control Panel → Internet Options → Connections → LAN settings).</li>
                <li>Under &quot;Manual proxy setup&quot;, turn <strong>Use a proxy server</strong> <em>On</em>.</li>
                <li>Set <strong>Address</strong> to <code className="rounded bg-muted px-1">{proxyHost}</code> and <strong>Port</strong> to <code className="rounded bg-muted px-1">{httpPort}</code>{hasProxyAuth ? <>; use username <code className="rounded bg-muted px-1">{proxyUser}</code> and password where the app supports proxy auth</> : ''}.</li>
                <li>Save. Browsers and most apps will use this. For SOCKS-only apps, set SOCKS host to <code className="rounded bg-muted px-1">{proxyHost}</code> and port <code className="rounded bg-muted px-1">{socksPort}</code> in the app&apos;s settings{hasProxyAuth ? ` (username: ${proxyUser})` : ''}.</li>
              </ol>
              <p className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
                <Tooltip content="System proxy is HTTP; individual apps can be set to SOCKS in their own settings." side="top">
                  <span className="cursor-help"><Info className="h-3.5 w-3.5" /></span>
                </Tooltip>
                Use SOCKS port {socksPort} in app-level proxy settings when needed.
              </p>
            </TabsContent>
            <TabsContent value="curl" className="mt-4">
              <p className="text-sm text-muted-foreground mb-3">Use curl with the HTTP or SOCKS5 proxy (URL from Core → Latency test). Example (HTTP proxy):</p>
              <div className="rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs">
                <code className="block break-all">
                  curl -x {httpProxyUrl} {curlTestUrl} -I
                </code>
              </div>
              <p className="mt-3 text-sm text-muted-foreground">SOCKS5 example:</p>
              <div className="mt-1.5 rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs">
                <code className="block break-all">
                  curl -x {socksProxyUrl} {curlTestUrl} -I
                </code>
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <div>
            <CardTitle>Core logs</CardTitle>
            <p className="text-sm text-muted-foreground">Latest output (realtime)</p>
          </div>
          <Select value={String(logTail)} onValueChange={(v) => setLogTail(Number(v))}>
            <SelectTrigger className="w-[120px]">
              <SelectValue placeholder="Lines" />
            </SelectTrigger>
            <SelectContent>
              {LOG_TAIL_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)}>
                  {n} lines
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardHeader>
        <CardContent>
          <div
            ref={logContainerRef}
            className="max-h-[400px] overflow-auto rounded-md border border-border bg-muted/30 p-3 font-mono text-xs"
          >
            {logLines.length === 0 ? (
              <p className="text-muted-foreground">No logs yet. Start the core to see output.</p>
            ) : (
              <pre className="whitespace-pre-wrap break-all">
                {logLines.map((line, i) => (
                  <span key={i} className="block leading-relaxed">
                    {line}
                  </span>
                ))}
              </pre>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
