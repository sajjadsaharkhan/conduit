import { useState } from 'react'
import { Check, Copy, Globe2, Route } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { copyText } from '@/lib/clipboard'
import { cn } from '@/lib/utils'
import { MODE_INFO, portFor, proxyUrl, type ProxyMode, type ProxyPorts, type ProxyProtocol } from '@/lib/proxy-endpoints'

type Props = {
  ports: ProxyPorts
  host: string
  username: string
  password: string
  nodeSelected: boolean
}

const MODES: { mode: ProxyMode; icon: typeof Route }[] = [
  { mode: 'hybrid', icon: Route },
  { mode: 'full', icon: Globe2 },
]

const PROTOCOLS: { protocol: ProxyProtocol; label: string }[] = [
  { protocol: 'http', label: 'HTTP' },
  { protocol: 'socks5', label: 'SOCKS5' },
]

function EndpointRow({ label, port, url, displayUrl }: { label: string; port: number | null; url: string; displayUrl: string }) {
  const [copied, setCopied] = useState(false)

  async function onCopy() {
    if (await copyText(url)) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  if (port == null) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-md border border-dashed border-border px-3 py-2.5 text-sm text-muted-foreground">
        <span className="font-medium">{label}</span>
        <span>Disabled</span>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-3 rounded-md border border-border bg-background px-3 py-2">
      <span className="w-14 shrink-0 text-sm font-medium">{label}</span>
      <span className="shrink-0 rounded bg-muted px-2 py-0.5 font-mono text-xs font-semibold">{port}</span>
      <code className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground" title={displayUrl}>
        {displayUrl}
      </code>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-9 w-9 shrink-0"
        onClick={onCopy}
        aria-label={copied ? `${label} URL copied` : `Copy ${label} URL`}
      >
        {copied ? <Check className="text-emerald-400" /> : <Copy />}
      </Button>
      <span className="sr-only" aria-live="polite">{copied ? 'Copied' : ''}</span>
    </div>
  )
}

export function ProxyEndpoints({ ports, host, username, password, nodeSelected }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Proxy endpoints</CardTitle>
        <CardDescription>
          Each mode has its own ports. Copy a URL into your app or system proxy settings. Ports are set with the
          CONDUIT_* environment variables.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2">
        {MODES.map(({ mode, icon: Icon }) => (
          <section
            key={mode}
            aria-labelledby={`proxy-mode-${mode}`}
            className={cn(
              'flex flex-col gap-3 rounded-lg border p-4',
              mode === 'full' ? 'border-primary/40 bg-primary/5' : 'border-border bg-muted/20',
            )}
          >
            <div className="flex items-start gap-2.5">
              <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', mode === 'full' ? 'text-primary' : 'text-muted-foreground')} aria-hidden />
              <div className="space-y-1">
                <h3 id={`proxy-mode-${mode}`} className="text-sm font-semibold leading-none">{MODE_INFO[mode].label}</h3>
                <p className="text-sm text-muted-foreground">{MODE_INFO[mode].summary}</p>
              </div>
            </div>
            {PROTOCOLS.map(({ protocol, label }) => {
              const port = portFor(ports, mode, protocol)
              return (
                <EndpointRow
                  key={protocol}
                  label={label}
                  port={port}
                  url={port == null ? '' : proxyUrl(protocol, host, port, username, password)}
                  displayUrl={port == null ? '' : proxyUrl(protocol, host, port, username, password, true)}
                />
              )
            })}
            {mode === 'full' && !nodeSelected && (
              <p className="text-xs text-muted-foreground">
                These ports open once a node is selected, so traffic can never fall back to direct.
              </p>
            )}
          </section>
        ))}
      </CardContent>
    </Card>
  )
}
