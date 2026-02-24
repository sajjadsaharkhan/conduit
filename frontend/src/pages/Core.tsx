import { useEffect, useRef, useState } from 'react'
import { status as statusApi, core, settings as settingsApi } from '../api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Tooltip } from '@/components/ui/tooltip'
import { Info } from 'lucide-react'

export default function Core() {
  const [data, setData] = useState<Awaited<ReturnType<typeof statusApi.get>> | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<'start' | 'stop' | 'restart' | null>(null)
  const [err, setErr] = useState('')
  const [fullLogs, setFullLogs] = useState<string[]>([])
  const [logsLoading, setLogsLoading] = useState(false)
  const logEndRef = useRef<HTMLDivElement>(null)

  const [coreType, setCoreType] = useState<'sing-box' | 'xray'>('sing-box')
  const [refreshInterval, setRefreshInterval] = useState(1)
  const [autoSwitchBest, setAutoSwitchBest] = useState(true)
  const [latencyTestDomain, setLatencyTestDomain] = useState('')
  const [settingsLoading, setSettingsLoading] = useState(false)
  const [settingsSaveMsg, setSettingsSaveMsg] = useState<string | null>(null)
  const [latencyTesting, setLatencyTesting] = useState(false)
  const [latencyResult, setLatencyResult] = useState<{
    latency_ms: number | null
    duration_ms: number | null
    download_speed_kbps: number | null
    size_bytes: number
    success: boolean
    error: string | null
  } | null>(null)

  function load() {
    statusApi.get().then(setData).catch((e) => setErr(e.message)).finally(() => setLoading(false))
  }

  function loadSettings() {
    settingsApi.get().then((s) => {
      if (s.core_type === 'xray' || s.core_type === 'sing-box') setCoreType(s.core_type)
      setRefreshInterval(s.refresh_interval_minutes)
      setAutoSwitchBest(s.auto_switch_best)
      setLatencyTestDomain(s.latency_test_domain || '')
    }).catch(() => {})
  }

  useEffect(() => {
    load()
    loadSettings()
  }, [])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [fullLogs])

  async function loadFullLogs() {
    setLogsLoading(true)
    try {
      const res = await core.fullLogs()
      setFullLogs(res.lines)
    } catch {
      setFullLogs([])
    } finally {
      setLogsLoading(false)
    }
  }

  async function handleStart() {
    setActionLoading('start')
    setErr('')
    try {
      await core.start()
      load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Start failed')
    } finally {
      setActionLoading(null)
    }
  }

  async function handleStop() {
    setActionLoading('stop')
    setErr('')
    try {
      await core.stop()
      load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Stop failed')
    } finally {
      setActionLoading(null)
    }
  }

  async function handleRestart() {
    setActionLoading('restart')
    setErr('')
    try {
      await core.restart()
      load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Restart failed')
    } finally {
      setActionLoading(null)
    }
  }

  async function handleCoreTypeChange(value: string) {
    const v = value as 'sing-box' | 'xray'
    setCoreType(v)
    setSettingsSaveMsg(null)
    try {
      await settingsApi.update({ core_type: v })
      setSettingsSaveMsg('Core type updated. Restart the core or select a node to apply.')
      load()
    } catch (e) {
      setSettingsSaveMsg(e instanceof Error ? e.message : 'Failed to update core type')
    }
  }

  async function handleSaveRefreshConfig() {
    setSettingsLoading(true)
    setSettingsSaveMsg(null)
    try {
      await settingsApi.update({
        refresh_interval_minutes: Math.max(1, Math.min(1440, refreshInterval)),
        auto_switch_best: autoSwitchBest,
      })
      setSettingsSaveMsg('Saved.')
      loadSettings()
    } catch (e) {
      setSettingsSaveMsg(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSettingsLoading(false)
    }
  }

  async function handleSaveLatencyDomain() {
    setSettingsLoading(true)
    setSettingsSaveMsg(null)
    try {
      await settingsApi.update({ latency_test_domain: latencyTestDomain.trim() || '' })
      setSettingsSaveMsg('Latency test URL saved.')
      loadSettings()
    } catch (e) {
      setSettingsSaveMsg(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSettingsLoading(false)
    }
  }

  async function handleLatencyTest() {
    const url = latencyTestDomain.trim()
    if (!url) return
    setLatencyTesting(true)
    setLatencyResult(null)
    try {
      const res = await core.latencyTest(url)
      setLatencyResult(res)
    } catch (e) {
      setLatencyResult({
        success: false,
        error: e instanceof Error ? e.message : 'Test failed',
        latency_ms: null,
        duration_ms: null,
        download_speed_kbps: null,
        size_bytes: 0,
      })
    } finally {
      setLatencyTesting(false)
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
        <h1 className="text-3xl font-bold tracking-tight">Core</h1>
        <p className="text-muted-foreground">Control, core type, refresh settings, and logs</p>
      </div>

      {err && (
        <Alert variant="destructive">
          <AlertDescription>{err}</AlertDescription>
        </Alert>
      )}

      {/* One row: same-height panels */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-stretch">
        {/* Core control */}
        <div className="flex min-h-0">
          <Card className="flex h-full w-full flex-col">
            <CardHeader className="shrink-0 flex flex-row items-center gap-1.5">
              <CardTitle>Core control</CardTitle>
              <Tooltip
                content="Start, stop, or restart the proxy process. Status (Running/Stopped and PID) is read from the core process in real time. Use Restart to reload config and apply the current node."
                side="top"
              >
                <span className="shrink-0 text-muted-foreground cursor-help inline-flex">
                  <Info className="h-4 w-4" />
                </span>
              </Tooltip>
            </CardHeader>
            <CardContent className="flex-1 space-y-3 min-h-0">
              <p className={`text-sm font-medium ${data?.core.running ? 'text-emerald-500' : 'text-muted-foreground'}`}>
                {data?.core.running ? `Running (PID ${data.core.pid})` : 'Stopped'}
                {data?.core_type && ` · ${data.core_type}`}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button onClick={handleStart} disabled={data?.core.running || !!actionLoading}>
                  {actionLoading === 'start' ? '…' : 'Start'}
                </Button>
                <Button variant="secondary" onClick={handleStop} disabled={!data?.core.running || !!actionLoading}>
                  {actionLoading === 'stop' ? '…' : 'Stop'}
                </Button>
                <Button variant="outline" onClick={handleRestart} disabled={!!actionLoading}>
                  {actionLoading === 'restart' ? '…' : 'Restart'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Proxy core (Core type) */}
        <div className="flex min-h-0">
          <Card className="flex h-full w-full flex-col">
            <CardHeader className="shrink-0 flex flex-row items-start justify-between gap-2">
              <div className="flex items-center gap-1.5 min-w-0">
                <CardTitle>Core type</CardTitle>
                <Tooltip
                  content="Choose which core runs the proxy (sing-box or Xray). Restart the core or select a node to apply the change."
                  side="top"
                >
                  <span className="shrink-0 text-muted-foreground cursor-help inline-flex">
                    <Info className="h-4 w-4" />
                  </span>
                </Tooltip>
              </div>
            </CardHeader>
            <CardContent className="flex-1 min-h-0">
              <Select value={coreType} onValueChange={handleCoreTypeChange}>
                <SelectTrigger className="w-[180px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="sing-box">sing-box</SelectItem>
                  <SelectItem value="xray">Xray</SelectItem>
                </SelectContent>
              </Select>
              {settingsSaveMsg && settingsSaveMsg.includes('Core type') && (
                <p className="mt-2 text-sm text-emerald-600">{settingsSaveMsg}</p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Refresh & switch */}
        <div className="flex min-h-0">
          <Card className="flex h-full w-full flex-col">
            <CardHeader className="shrink-0 flex flex-row items-start justify-between gap-2 space-y-0 pb-2">
              <div className="flex items-center gap-1.5 min-w-0">
                <CardTitle>Refresh &amp; switch</CardTitle>
                <Tooltip
                  content="How often to refresh the subscription and whether to auto-switch to the best node by latency."
                  side="top"
                >
                  <span className="shrink-0 text-muted-foreground cursor-help inline-flex">
                    <Info className="h-4 w-4" />
                  </span>
                </Tooltip>
              </div>
              <Button size="sm" onClick={handleSaveRefreshConfig} disabled={settingsLoading} className="shrink-0">
                {settingsLoading ? 'Saving…' : 'Save'}
              </Button>
            </CardHeader>
            <CardContent className="flex-1 space-y-4 min-h-0">
              <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 items-center">
                <Label htmlFor="refresh-interval">Interval (min)</Label>
                <div />
                <Input
                  id="refresh-interval"
                  type="number"
                  min={1}
                  max={1440}
                  value={refreshInterval}
                  onChange={(e) => setRefreshInterval(Number(e.target.value) || 1)}
                  className="w-24"
                />
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="auto-switch"
                    checked={autoSwitchBest}
                    onCheckedChange={setAutoSwitchBest}
                  />
                  <Label htmlFor="auto-switch" className="cursor-pointer text-sm font-normal">
                    Auto switch to best node
                  </Label>
                </div>
              </div>
              {settingsSaveMsg && (settingsSaveMsg === 'Saved.' || settingsSaveMsg === 'Save failed') && (
                <p className={`text-sm ${settingsSaveMsg === 'Saved.' ? 'text-emerald-600' : 'text-destructive'}`}>
                  {settingsSaveMsg}
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center gap-1.5">
          <CardTitle>Latency test</CardTitle>
          <Tooltip
            content="Download the test URL via the proxy to measure real latency (time to first byte) and download speed. Save the URL first, then run the test. The request goes through your current proxy (HTTP on port 8080)."
            side="top"
          >
            <span className="shrink-0 text-muted-foreground cursor-help inline-flex">
              <Info className="h-4 w-4" />
            </span>
          </Tooltip>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex-1 min-w-[200px] space-y-2">
              <Label htmlFor="latency-domain">Test URL</Label>
              <Input
                id="latency-domain"
                type="url"
                value={latencyTestDomain}
                onChange={(e) => setLatencyTestDomain(e.target.value)}
                placeholder="https://www.gstatic.com/generate_204"
              />
            </div>
            <Button onClick={handleSaveLatencyDomain} disabled={settingsLoading}>
              {settingsLoading ? 'Saving…' : 'Save URL'}
            </Button>
            <Button
              variant="secondary"
              onClick={handleLatencyTest}
              disabled={latencyTesting || !latencyTestDomain.trim()}
            >
              {latencyTesting ? 'Testing…' : 'Test latency'}
            </Button>
          </div>
          {latencyResult && (
            <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
              {latencyResult.success ? (
                <div className="flex flex-wrap gap-x-4 gap-y-1">
                  {latencyResult.latency_ms != null && (
                    <span>Latency: <strong>{latencyResult.latency_ms} ms</strong></span>
                  )}
                  {latencyResult.duration_ms != null && (
                    <span>Duration: <strong>{latencyResult.duration_ms} ms</strong></span>
                  )}
                  {latencyResult.download_speed_kbps != null && (
                    <span>Download: <strong>{latencyResult.download_speed_kbps} Kbps</strong></span>
                  )}
                  <span>Size: <strong>{latencyResult.size_bytes} B</strong></span>
                </div>
              ) : (
                <p className="text-destructive">{latencyResult.error ?? 'Test failed'}</p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Full logs at the end */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <div>
            <CardTitle>Full logs</CardTitle>
            <CardDescription>Complete log buffer (not real-time)</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={loadFullLogs} disabled={logsLoading}>
            {logsLoading ? 'Loading…' : 'Load logs'}
          </Button>
        </CardHeader>
        <CardContent>
          <div className="max-h-[400px] overflow-auto rounded-md border border-border bg-muted/30 p-3 font-mono text-xs">
            {fullLogs.length === 0 && !logsLoading ? (
              <p className="text-muted-foreground">Click &quot;Load logs&quot; to fetch the full log buffer.</p>
            ) : (
              <pre className="whitespace-pre-wrap break-all">
                {fullLogs.map((line, i) => (
                  <span key={i} className="block leading-relaxed">
                    {line}
                  </span>
                ))}
                <div ref={logEndRef} />
              </pre>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
