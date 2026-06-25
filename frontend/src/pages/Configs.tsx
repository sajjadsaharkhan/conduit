import { useEffect, useState } from 'react'
import { config, core, settings as settingsApi } from '../api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { JsonEditor } from '@/components/ui/json-editor'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
} from 'lucide-react'
import type { ConfigSectionName, ConfigSectionInfo } from '../api'

export default function Configs() {
  const [structure, setStructure] = useState<ConfigSectionInfo[] | null>(null)
  const [coreType, setCoreType] = useState<'sing-box' | 'xray'>('sing-box')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [activeTab, setActiveTab] = useState<ConfigSectionName>('dns')
  const [sectionData, setSectionData] = useState<Record<string, unknown> | null>(null)
  const [sectionLoading, setSectionLoading] = useState(false)
  const [sectionError, setSectionError] = useState('')

  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [hasChanges, setHasChanges] = useState(false)

  const [jsonEditorValue, setJsonEditorValue] = useState('')
  const [jsonError, setJsonError] = useState('')

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

  // Load structure and settings
  useEffect(() => {
    loadStructure()
    loadSettings()
  }, [])

  // Load section data when tab changes
  useEffect(() => {
    if (activeTab) {
      loadSection(activeTab)
    }
  }, [activeTab])

  async function loadStructure() {
    setLoading(true)
    setError('')
    try {
      const res = await config.getStructure()
      setStructure(res.sections)
      setCoreType(res.core_type)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load config structure')
    } finally {
      setLoading(false)
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

  async function loadSettings() {
    try {
      const s = await settingsApi.get()
      setLatencyTestDomain(s.latency_test_domain || '')
    } catch (e) {
      console.error('Failed to load settings:', e)
    }
  }

  function handleJsonChange(value: string) {
    setJsonEditorValue(value)
    setHasChanges(true)

    // Validate JSON
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

  async function handleSave() {
    if (!activeTab || jsonError) return

    setSaving(true)
    setSaveMessage(null)
    try {
      // Parse and validate JSON
      const data = JSON.parse(jsonEditorValue)

      // Save to backend
      await config.updateSection(activeTab, data)

      setSaveMessage({ type: 'success', text: `${activeTab} section saved successfully` })
      setHasChanges(false)

      // Reload section data to confirm
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

  function handleReload() {
    if (activeTab) {
      loadSection(activeTab)
    }
  }

  async function handleSaveLatencyDomain() {
    try {
      await settingsApi.update({ latency_test_domain: latencyTestDomain.trim() || '' })
      setSaveMessage({ type: 'success', text: 'Test URL saved.' })
      setTimeout(() => setSaveMessage(null), 3000)
    } catch (e) {
      setSaveMessage({ type: 'error', text: e instanceof Error ? e.message : 'Failed to save URL' })
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
        <p className="text-muted-foreground">Loading config structure…</p>
      </div>
    )
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    )
  }

  if (!structure) {
    return null
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Core Configs</h1>
        <p className="text-muted-foreground">Manage {coreType} configuration by sections</p>
      </div>

      {/* Info Alert */}
      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription className="text-sm">
          Editing sections updates the custom configuration. Changes will take effect after restarting the core.
          Use the &quot;All&quot; tab to view the complete configuration.
        </AlertDescription>
      </Alert>

      {/* Save/Reload Bar */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
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
              <Button variant="outline" size="sm" onClick={handleReload} disabled={sectionLoading}>
                <RotateCw className="h-4 w-4 mr-1" />
                Reload
              </Button>
              <Button size="sm" onClick={handleSave} disabled={saving || !hasChanges || !!jsonError}>
                <Save className="h-4 w-4 mr-1" />
                {saving ? 'Saving…' : 'Save Changes'}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Latency Test Card */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-1.5">
          <CardTitle className="flex items-center gap-2">
            <Gauge className="h-5 w-5" />
            Latency Test
          </CardTitle>
          <CardDescription>
            Test your proxy connection with detailed metrics and response preview
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex-1 min-w-[200px] space-y-2">
              <Label htmlFor="latency-test-url">Test URL</Label>
              <Input
                id="latency-test-url"
                type="url"
                value={latencyTestDomain}
                onChange={(e) => setLatencyTestDomain(e.target.value)}
                placeholder="https://www.gstatic.com/generate_204"
              />
            </div>
            <Button variant="outline" onClick={handleSaveLatencyDomain}>
              Save URL
            </Button>
            <Button
              onClick={handleLatencyTest}
              disabled={latencyTesting || !latencyTestDomain.trim()}
            >
              {latencyTesting ? 'Testing…' : 'Test Latency'}
            </Button>
          </div>
          {latencyResult && (
            <div className="space-y-3">
              {/* Connection Info */}
              <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
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

              {/* Performance Metrics */}
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

              {/* Response Preview */}
              {latencyResult.success && latencyResult.response_preview && (
                <div className="rounded-md border border-border bg-muted/30">
                  <div className="px-3 py-2 border-b border-border">
                    <span className="text-sm font-medium">Response Preview</span>
                    <span className="text-xs text-muted-foreground ml-2">(first ~10KB)</span>
                  </div>
                  <div className="p-3">
                    <pre className="text-xs font-mono whitespace-pre-wrap break-all max-h-[200px] overflow-auto">
                      {latencyResult.response_preview}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Main Tabs */}
      <Card>
        <CardContent className="pt-6">
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
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-lg font-semibold">{section.label}</h3>
                      <p className="text-sm text-muted-foreground">{section.description}</p>
                    </div>
                  </div>

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
        </CardContent>
      </Card>
    </div>
  )
}
