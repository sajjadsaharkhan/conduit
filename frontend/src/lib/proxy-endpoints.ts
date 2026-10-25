export type ProxyMode = 'hybrid' | 'full'
export type ProxyProtocol = 'http' | 'socks5'

export type ProxyPorts = {
  hybrid_http_port: number | null
  full_http_port: number | null
  hybrid_socks_port: number | null
  full_socks_port: number | null
}

export const MODE_INFO: Record<ProxyMode, { label: string; summary: string }> = {
  hybrid: {
    label: 'Hybrid',
    summary: 'Follows your Domains rules. Matching domains use the node; everything else goes direct.',
  },
  full: {
    label: 'Full tunnel',
    summary: 'Everything goes through the selected node. Domains rules are ignored.',
  },
}

export function portFor(ports: ProxyPorts, mode: ProxyMode, protocol: ProxyProtocol): number | null {
  if (protocol === 'http') return mode === 'hybrid' ? ports.hybrid_http_port : ports.full_http_port
  return mode === 'hybrid' ? ports.hybrid_socks_port : ports.full_socks_port
}

/** Proxy URL; pass mask=true to hide the password for on-screen display. */
export function proxyUrl(
  protocol: ProxyProtocol,
  host: string,
  port: number,
  username: string,
  password: string,
  mask = false,
): string {
  const auth = username && password
    ? `${encodeURIComponent(username)}:${mask ? '••••••' : encodeURIComponent(password)}@`
    : ''
  return `${protocol}://${auth}${host}:${port}`
}
