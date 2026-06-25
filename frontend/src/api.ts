const API_BASE = ''

// Config section types
export type ConfigSectionName = 'dns' | 'outbounds' | 'route' | 'routing' | 'all'

export interface ConfigSectionInfo {
  name: ConfigSectionName
  label: string
  description: string
}

export interface ConfigStructureResponse {
  sections: ConfigSectionInfo[]
  core_type: 'sing-box' | 'xray'
}

export interface ConfigSectionResponse {
  section: ConfigSectionName
  data: Record<string, unknown>
  core_type: 'sing-box' | 'xray'
}

export interface ConfigUpdateRequest {
  data: Record<string, unknown>
}

export interface ConfigUpdateResponse {
  ok: boolean
  message: string
}

function getToken(): string {
  return localStorage.getItem('token') || ''
}

export async function api<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken()
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (res.status === 401) {
    localStorage.removeItem('token')
    window.location.reload()
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || String(err))
  }
  return res.json()
}

export const auth = {
  login: (username: string, password: string) =>
    api<{ token: string; username: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  me: () => api<{ username: string }>('/api/auth/me'),
}

export const settings = {
  get: () =>
    api<{
      subscription_url: string
      http_port: number
      socks_port: number
      core_type: string
      last_refresh: string
      selected_node_raw: string
      refresh_interval_minutes: number
      auto_switch_best: boolean
      latency_test_domain: string
      proxy_display_host: string
      proxy_username: string
      proxy_password: string
      use_custom_config: boolean
      custom_config: string
      dns_servers: string
      dns_final: string
    }>('/api/settings'),
  update: (body: {
    subscription_url?: string
    http_port?: number
    socks_port?: number
    core_type?: string
    refresh_interval_minutes?: number
    auto_switch_best?: boolean
    latency_test_domain?: string
    proxy_display_host?: string
    proxy_username?: string
    proxy_password?: string
    use_custom_config?: boolean
    custom_config?: string
    dns_servers?: string
    dns_final?: string
  }) => api<{ ok: boolean }>('/api/settings', { method: 'PUT', body: JSON.stringify(body) }),
}

export const subscription = {
  refresh: () => api<{ ok: boolean }>('/api/subscription/refresh', { method: 'POST' }),
}

export const nodes = {
  list: () =>
    api<{
      nodes: {
        id: number
        source: string
        raw_link: string
        name: string
        latency_ms: number | null
        real_latency_ms: number | null
        last_check: string | null
      }[]
    }>('/api/nodes'),
  select: (raw_link: string) =>
    api<{ ok: boolean }>('/api/nodes/select', {
      method: 'POST',
      body: JSON.stringify({ raw_link }),
    }),
  update: (id: number, raw_link: string) =>
    api<{ ok: boolean }>(`/api/nodes/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ raw_link }),
    }),
  delete: (id: number) =>
    api<{ ok: boolean }>(`/api/nodes/${id}`, { method: 'DELETE' }),
  latencyTest: (raw_link: string, node_id?: number) =>
    api<{
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
    }>('/api/nodes/latency-test', {
      method: 'POST',
      body: JSON.stringify({ raw_link, node_id: node_id ?? undefined }),
    }),
}

export const domains = {
  list: () =>
    api<{ domains: { id: number; type: string; value: string; outbound: string }[] }>('/api/domains'),
  add: (type: string, value: string, outbound: string = 'proxy') =>
    api<{ id: number; type: string; value: string; outbound: string }>('/api/domains', {
      method: 'POST',
      body: JSON.stringify({ type, value, outbound }),
    }),
  delete: (id: number) =>
    api<{ ok: boolean }>(`/api/domains/${id}`, { method: 'DELETE' }),
  bulk: (text: string, outbound: string = 'proxy') =>
    api<{ added: number; message: string }>('/api/domains/bulk', {
      method: 'POST',
      body: JSON.stringify({ text, outbound }),
    }),
}

export const manual = {
  apply: (share_link?: string, raw_json?: string) =>
    api<{ ok: boolean }>('/api/manual/apply', {
      method: 'POST',
      body: JSON.stringify({ share_link, raw_json }),
    }),
}

export const status = {
  get: () =>
    api<{
      core: { running: boolean; pid: number | null; started_at: number | null }
      core_type: string
      http_port: number
      socks_port: number
      proxy_display_host: string
      proxy_username: string
      proxy_password: string
      latency_test_domain: string
      last_refresh: string
      selected_node_raw: string
      selected_node_name: string
      selected_node_latency_ms: number | null
      selected_node_real_latency_ms: number | null
      usage: { connections: number | null; upload_bytes: number | null; download_bytes: number | null }
    }>('/api/status'),
}

export const core = {
  start: () =>
    api<{ ok: boolean; running: boolean }>('/api/core/start', { method: 'POST' }),
  stop: () =>
    api<{ ok: boolean; running: boolean }>('/api/core/stop', { method: 'POST' }),
  restart: () =>
    api<{ ok: boolean; running: boolean }>('/api/core/restart', { method: 'POST' }),
  logs: (tail?: number) =>
    api<{ lines: string[] }>(`/api/core/logs${tail != null ? `?tail=${tail}` : '?tail=2000'}`),
  fullLogs: () => api<{ lines: string[] }>('/api/core/logs'),
  latencyTest: (url?: string) =>
    api<{
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
    }>('/api/core/latency-test', {
      method: 'POST',
      body: JSON.stringify({ url: url || undefined }),
    }),
  getConfig: () =>
    api<{ config: Record<string, unknown> | null; exists: boolean; path: string; is_custom: boolean }>('/api/config'),
}

export const config = {
  getStructure: () =>
    api<ConfigStructureResponse>('/api/config/structure'),

  getSection: (section: ConfigSectionName) =>
    api<ConfigSectionResponse>(`/api/config/section/${section}`),

  updateSection: (section: ConfigSectionName, data: Record<string, unknown>) =>
    api<ConfigUpdateResponse>(`/api/config/section/${section}`, {
      method: 'PUT',
      body: JSON.stringify({ data }),
    }),
}
