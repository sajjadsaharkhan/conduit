import { useEffect, useRef, useState } from 'react'
import { status as statusApi, core, config, settings as settingsApi } from '../api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { JsonEditor } from '@/components/ui/json-editor'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import {
  Server,
  Globe,
  ArrowUpDown,
  FileCode,
  Info,
  Save,
  RotateCw,
  CheckCircle,
  AlertCircle,
  Gauge,
  Play,
  Download,
  Upload,
} from 'lucide-react'
import type { ConfigSectionName, ConfigSectionInfo } from '../api'

export default function Core() {
  // Core control state
  const [data, setData] = useState<Awaited<ReturnType<typeof statusApi.get>> | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<'start' | 'stop' | 'restart' | null>(null)
  const [err, setErr] = useState('')
  const [fullLogs, setFullLogs] = useState<string[]>([])
  const [logsLoading, setLogsLoading] = useState(false)
  const logEndRef = useRef<HTMLDivElement>(null)

  // Settings state
  const [coreType, setCoreType] = useState<'sing-box' | 'xray'>('sing-box')
  const [refreshInterval, setRefreshInterval] = useState(1)
  const [autoSwitchBest, setAutoSwitchBest] = useState(true)
  const [settingsLoading, setSettingsLoading] = useState(false)
  const [settingsSaveMsg, setSettingsSaveMsg] = useState<string | null>(null)

  // Config editing state
  const [structure, setStructure] = useState<ConfigSectionInfo[] | null>(null)
  const [activeTab, setActiveTab] = useState<ConfigSectionName>('dns')
  const [sectionData, setSectionData] = useState<Record<string, unknown> | null>(null)
  const [sectionLoading, setSectionLoading] = useState(false)
  const [sectionError, setSectionError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [hasChanges, setHasChanges] = useState(false)
  const [jsonEditorValue, setJsonEditorValue] = useState('')
  const [jsonError, setJsonError] = useState('')
  const [activeParentTab, setActiveParentTab] = useState<'logs' | 'config'>('logs')
  const [importExportLoading, setImportExportLoading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Latency test state
  const [latencyTestDomain, setLatencyTestDomain] = useState('')
  const [latencyTesting, setLatencyTesting] = useState(false)
  const [latencyResult, setLatencyResult] = useState<{
    latency_ms: number | null
    duration_ms: number | null
    download_speed_kbps: number | null
    size_bytes: number
    success: boolean
    error: string | null
    status_code: number | null
    headers: Record<string, string>
    response_preview: string
    proxy_used: string
    has_proxy_auth: boolean
  } | null>(null)
  const [latencyDetailsOpen, setLatencyDetailsOpen] = useState(false)

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

  async function loadStructure() {
    try {
      const res = await config.getStructure()
      setStructure(res.sections)
      setCoreType(res.core_type)
    } catch (e) {
      console.error('Failed to load config structure:', e)
    }
  }

  async function loadSection(section: ConfigSectionName) {
    setSectionLoading(true)
    setSectionError('')
    setSaveMessage(null)
    try {
      const res = await config.getSection(section)
      setSectionData(res.data)
      const jsonStr = JSON.stringify(res.data, null, 2)
      setJsonEditorValue(jsonStr)
      setHasChanges(false)
      setJsonError('')
    } catch (e) {
      setSectionError(e instanceof Error ? e.message : `Failed to load ${section} section`)
      setSectionData(null)
      setJsonEditorValue('')
    } finally {
      setSectionLoading(false)
    }
  }

  useEffect(() => {
    load()
    loadSettings()
    loadStructure()
  }, [])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [fullLogs])

  useEffect(() => {
    if (activeTab) {
      loadSection(activeTab)
    }
  }, [activeTab])

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

  function handleJsonChange(value: string) {
    setJsonEditorValue(value)
    setHasChanges(true)

    try {
      if (value.trim()) {
        JSON.parse(value)
        setJsonError('')
      } else {
        setJsonError('Cannot be empty')
      }
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : 'Invalid JSON')
    }
  }

  async function handleSaveConfig() {
    if (!activeTab || jsonError) return

    setSaving(true)
    setSaveMessage(null)
    try {
      const data = JSON.parse(jsonEditorValue)
      await config.updateSection(activeTab, data)
      setSaveMessage({ type: 'success', text: `${activeTab} section saved successfully` })
      setHasChanges(false)
      setTimeout(() => loadSection(activeTab), 500)
    } catch (e) {
      setSaveMessage({
        type: 'error',
        text: e instanceof Error ? e.message : 'Failed to save section',
      })
    } finally {
      setSaving(false)
    }
  }

  function handleReloadConfig() {
    if (activeTab) {
      loadSection(activeTab)
    }
  }

  async function handleExportConfig() {
    setImportExportLoading(true)
    setSaveMessage(null)
    try {
      const res = await config.getSection('all')
      const configJson = JSON.stringify(res.data, null, 2)
      const blob = new Blob([configJson], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${coreType}-config-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      setSaveMessage({ type: 'success', text: 'Configuration exported successfully' })
    } catch (e) {
      setSaveMessage({
        type: 'error',
        text: e instanceof Error ? e.message : 'Failed to export configuration',
      })
    } finally {
      setImportExportLoading(false)
    }
  }

  function handleImportConfigClick() {
    fileInputRef.current?.click()
  }

  async function handleImportConfigChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    setImportExportLoading(true)
    setSaveMessage(null)

    try {
      const text = await file.text()
      const data = JSON.parse(text)

      // Validate JSON structure
      if (typeof data !== 'object' || data === null) {
        throw new Error('Invalid configuration format')
      }

      await config.updateSection('all', data)
      setSaveMessage({ type: 'success', text: 'Configuration imported successfully. Reload to view changes.' })
      setHasChanges(false)

      // Reload current section if it's the 'all' tab
      if (activeTab === 'all') {
        setTimeout(() => loadSection('all'), 500)
      }
    } catch (e) {
      setSaveMessage({
        type: 'error',
        text: e instanceof Error ? e.message : 'Failed to import configuration',
      })
    } finally {
      setImportExportLoading(false)
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  async function handleSaveLatencyDomain() {
    try {
      await settingsApi.update({ latency_test_domain: latencyTestDomain.trim() || '' })
      setSettingsSaveMsg('Test URL saved.')
      setTimeout(() => setSettingsSaveMsg(null), 3000)
    } catch (e) {
      setSettingsSaveMsg(e instanceof Error ? e.message : 'Failed to save URL')
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
        status_code: null,
        headers: {},
        response_preview: '',
        proxy_used: '',
        has_proxy_auth: false,
      })
    } finally {
      setLatencyTesting(false)
    }
  }

  function getSectionIcon(sectionName: ConfigSectionName) {
    switch (sectionName) {
      case 'dns':
        return <Globe className="h-4 w-4" />
      case 'outbounds':
        return <Server className="h-4 w-4" />
      case 'route':
      case 'routing':
        return <ArrowUpDown className="h-4 w-4" />
      case 'all':
        return <FileCode className="h-4 w-4" />
      default:
        return <FileCode className="h-4 w-4" />
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
        <p className="text-muted-foreground">Control, configuration, settings, and logs</p>
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
              <div className="space-y-2">
                <Label htmlFor="core-type-select" className="text-xs">Core type</Label>
                <Select value={coreType} onValueChange={handleCoreTypeChange}>
                  <SelectTrigger id="core-type-select" className="h-8">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="sing-box">sing-box</SelectItem>
                    <SelectItem value="xray">Xray</SelectItem>
                  </SelectContent>
                </Select>
                {settingsSaveMsg && settingsSaveMsg.includes('Core type') && (
                  <p className="text-xs text-emerald-600">{settingsSaveMsg}</p>
                )}
              </div>
              <p className={`text-sm font-medium ${data?.core.running ? 'text-emerald-500' : 'text-muted-foreground'}`}>
                {data?.core.running ? `Running (PID ${data.core.pid})` : 'Stopped'}
                {data?.core_type && ` · ${data.core_type}`}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button onClick={handleStart} disabled={data?.core.running || !!actionLoading} size="sm">
                  {actionLoading === 'start' ? '…' : 'Start'}
                </Button>
                <Button variant="secondary" onClick={handleStop} disabled={!data?.core.running || !!actionLoading} size="sm">
                  {actionLoading === 'stop' ? '…' : 'Stop'}
                </Button>
                <Button variant="outline" onClick={handleRestart} disabled={!!actionLoading} size="sm">
                  {actionLoading === 'restart' ? '…' : 'Restart'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Latency test */}
        <div className="flex min-h-0">
          <Card className="flex h-full w-full flex-col">
            <CardHeader className="shrink-0 flex flex-row items-start justify-between gap-2 space-y-0 pb-2">
              <div className="flex items-center gap-1.5 min-w-0">
                <CardTitle className="flex items-center gap-2">
                  <Gauge className="h-4 w-4" />
                  Latency test
                </CardTitle>
                <Tooltip
                  content="Download the test URL via the proxy to measure real latency (time to first byte) and download speed. Save the URL first, then run the test. The request goes through your current proxy (HTTP on port 8080)."
                  side="top"
                >
                  <span className="shrink-0 text-muted-foreground cursor-help inline-flex">
                    <Info className="h-4 w-4" />
                  </span>
                </Tooltip>
              </div>
            </CardHeader>
            <CardContent className="flex-1 space-y-3 min-h-0">
              <div className="space-y-2">
                <div className="relative">
                  <Input
                    type="url"
                    value={latencyTestDomain}
                    onChange={(e) => setLatencyTestDomain(e.target.value)}
                    placeholder="https://www.gstatic.com/generate_204"
                    className="h-8 text-sm pr-10"
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleSaveLatencyDomain}
                    title="Save URL"
                    className="absolute right-0 top-0 h-8 w-8 p-0 hover:bg-muted rounded-none border-l"
                  >
                    <Save className="h-4 w-4" />
                  </Button>
                </div>
                <Button
                  onClick={handleLatencyTest}
                  disabled={latencyTesting || !latencyTestDomain.trim()}
                  size="sm"
                  className="w-full"
                >
                  <Play className="h-4 w-4 mr-1" />
                  {latencyTesting ? 'Testing…' : 'Test'}
                </Button>
              </div>
              {settingsSaveMsg && settingsSaveMsg.includes('Test URL') && (
                <p className="text-xs text-emerald-600">{settingsSaveMsg}</p>
              )}
              {latencyResult && (
                <div className="space-y-2">
                  {/* Health Status Badge */}
                  <div className={cn(
                    'flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium w-fit',
                    latencyResult.success
                      ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/20'
                      : 'bg-destructive/10 text-destructive border border-destructive/20'
                  )}>
                    {latencyResult.success ? (
                      <>
                        <CheckCircle className="h-3.5 w-3.5" />
                        <span>Healthy</span>
                      </>
                    ) : (
                      <>
                        <AlertCircle className="h-3.5 w-3.5" />
                        <span>Not Healthy</span>
                      </>
                    )}
                  </div>

                  {/* Performance Metrics */}
                  <div className="rounded-md border border-border bg-muted/30 px-2 py-1.5 text-xs">
                    {latencyResult.success ? (
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        {latencyResult.latency_ms != null && (
                          <span>Latency: <strong>{latencyResult.latency_ms} ms</strong></span>
                        )}
                        {latencyResult.duration_ms != null && (
                          <span>Duration: <strong>{latencyResult.duration_ms} ms</strong></span>
                        )}
                        {latencyResult.download_speed_kbps != null && (
                          <span>Download: <strong>{latencyResult.download_speed_kbps} Kbps</strong></span>
                        )}
                        <Button
                          variant="link"
                          size="sm"
                          className="h-auto p-0 ml-auto"
                          onClick={() => setLatencyDetailsOpen(true)}
                        >
                          Details
                        </Button>
                      </div>
                    ) : (
                      <p className="text-destructive">{latencyResult.error ?? 'Test failed'}</p>
                    )}
                  </div>
                </div>
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

      {/* Latency Test Details Modal */}
      <Dialog open={latencyDetailsOpen} onOpenChange={setLatencyDetailsOpen}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-auto">
          <DialogHeader>
            <DialogTitle>Latency Test Details</DialogTitle>
            <DialogDescription>
              Connection information and response preview
            </DialogDescription>
          </DialogHeader>
          {latencyResult && (
            <div className="space-y-4">
              {/* Connection Info */}
              <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
                <div className="mb-1 font-medium">Connection Info</div>
                <div className="flex flex-wrap gap-x-4 gap-y-1">
                  {latencyResult.status_code && (
                    <span>Status: <strong>{latencyResult.status_code}</strong></span>
                  )}
                  {latencyResult.proxy_used && (
                    <span>Proxy: <strong className="text-xs">{latencyResult.proxy_used}</strong></span>
                  )}
                  {latencyResult.has_proxy_auth && (
                    <span>Auth: <strong>Enabled</strong></span>
                  )}
                </div>
              </div>

              {/* Response Preview */}
              {latencyResult.success && latencyResult.response_preview && (
                <div className="rounded-md border border-border bg-muted/30">
                  <div className="px-3 py-2 border-b border-border">
                    <span className="text-sm font-medium">Response Preview</span>
                    <span className="text-xs text-muted-foreground ml-2">(first ~10KB)</span>
                  </div>
                  <div className="p-3">
                    <pre className="text-xs font-mono whitespace-pre-wrap break-all max-h-[400px] overflow-auto">
                      {latencyResult.response_preview}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Logs & Configuration */}
      <Card>
        <CardContent className="pt-6">
          <Tabs value={activeParentTab} onValueChange={(v) => setActiveParentTab(v as 'logs' | 'config')}>
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="logs">Logs</TabsTrigger>
              <TabsTrigger value="config">Edit Configuration</TabsTrigger>
            </TabsList>

            {/* Logs Tab */}
            <TabsContent value="logs" className="mt-4">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-lg font-semibold">Core logs</h3>
                    <p className="text-sm text-muted-foreground">View core logs in real-time</p>
                  </div>
                  <Button variant="outline" size="sm" onClick={loadFullLogs} disabled={logsLoading}>
                    {logsLoading ? 'Loading…' : 'Reload'}
                  </Button>
                </div>
                <div className="max-h-[500px] overflow-auto rounded-md border border-border bg-muted/30 p-3 font-mono text-xs">
                  {fullLogs.length === 0 && !logsLoading ? (
                    <p className="text-muted-foreground">Click &quot;Reload&quot; to fetch the log buffer.</p>
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
              </div>
            </TabsContent>

            {/* Configuration Tab */}
            <TabsContent value="config" className="mt-4">
              {structure && structure.length > 0 ? (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-lg font-semibold">Edit configuration</h3>
                      <p className="text-sm text-muted-foreground">
                        Editing sections updates the custom configuration. Changes will take effect after restarting the core.
                        Use the &quot;All&quot; tab to view the complete configuration.
                      </p>
                    </div>
                  </div>

                  {/* Save/Reload Bar */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {/* Import/Export Button Group */}
                      <div className="flex items-center gap-0 rounded-md border border-border">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={handleExportConfig}
                          disabled={importExportLoading}
                          className="rounded-r-none border-r-0 pr-3"
                        >
                          <Download className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={handleImportConfigClick}
                          disabled={importExportLoading}
                          className="rounded-l-none border-l-0 pl-3"
                        >
                          <Upload className="h-4 w-4" />
                        </Button>
                      </div>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="application/json,.json"
                        onChange={handleImportConfigChange}
                        className="hidden"
                      />
                      {saveMessage && (
                        <div
                          className={cn(
                            'flex items-center gap-1.5 text-sm',
                            saveMessage.type === 'success' ? 'text-emerald-600' : 'text-destructive',
                          )}
                        >
                          {saveMessage.type === 'success' ? (
                            <CheckCircle className="h-4 w-4" />
                          ) : (
                            <AlertCircle className="h-4 w-4" />
                          )}
                          {saveMessage.text}
                        </div>
                      )}
                      {hasChanges && !saveMessage && <span className="text-sm text-muted-foreground">You have unsaved changes</span>}
                    </div>
                    <div className="flex items-center gap-2">
                      <Button variant="outline" size="sm" onClick={handleReloadConfig} disabled={sectionLoading}>
                        <RotateCw className="h-4 w-4 mr-1" />
                        Reload
                      </Button>
                      <Button size="sm" onClick={handleSaveConfig} disabled={saving || !hasChanges || !!jsonError}>
                        <Save className="h-4 w-4 mr-1" />
                        {saving ? 'Saving…' : 'Save Changes'}
                      </Button>
                    </div>
                  </div>

                  {/* Config Section Tabs */}
                  <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as ConfigSectionName)}>
                    <TabsList className="grid w-full grid-cols-4">
                      {structure.map((section) => (
                        <TabsTrigger key={section.name} value={section.name} className="flex items-center gap-2">
                          {getSectionIcon(section.name)}
                          {section.label}
                        </TabsTrigger>
                      ))}
                    </TabsList>

                    {structure.map((section) => (
                      <TabsContent key={section.name} value={section.name} className="mt-4">
                        <div className="space-y-4">
                          {sectionError && (
                            <Alert variant="destructive">
                              <AlertDescription>{sectionError}</AlertDescription>
                            </Alert>
                          )}

                          {jsonError && (
                            <Alert variant="destructive">
                              <AlertDescription>Invalid JSON: {jsonError}</AlertDescription>
                            </Alert>
                          )}

                          {activeTab === section.name && (
                            <div className="rounded-md border border-border bg-muted/30">
                              {sectionLoading ? (
                                <div className="flex items-center justify-center py-12">
                                  <p className="text-muted-foreground">Loading…</p>
                                </div>
                              ) : sectionData ? (
                                <JsonEditor
                                  value={jsonEditorValue}
                                  onChange={handleJsonChange}
                                  placeholder={`{\n  // ${section.label} configuration\n}`}
                                  className="border-0"
                                />
                              ) : (
                                <div className="text-center py-8">
                                  <p className="text-muted-foreground text-sm">No {section.label} data available</p>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </TabsContent>
                    ))}
                  </Tabs>
                </div>
              ) : (
                <div className="flex items-center justify-center py-12">
                  <p className="text-muted-foreground">No configuration structure available</p>
                </div>
              )}
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  )
}
