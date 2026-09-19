/** Formen der Antworten des Backends. Namen wie dort, snake_case. */

export type Source = 'cloudflare' | 'librespeed' | 'ookla'
export const SOURCES: Source[] = ['cloudflare', 'librespeed', 'ookla']

export type PublicConfig = {
  version: string
  password_required: boolean
  signed_in: boolean
}

export type Result = {
  id: number
  started_at: string
  finished_at: string | null
  source: Source
  trigger: 'manual' | 'schedule' | 'api'
  schedule_id: number | null
  status: 'running' | 'ok' | 'failed' | 'cancelled'
  error_code: string | null
  server_id: string
  server_name: string
  server_location: string
  isp: string
  external_ip: string
  result_url: string | null
  download_mbps: number | null
  upload_mbps: number | null
  ping_ms: number | null
  jitter_ms: number | null
  ping_low_ms: number | null
  ping_high_ms: number | null
  packet_loss: number | null
  loaded_down_ms: number | null
  loaded_up_ms: number | null
  bytes_down: number | null
  bytes_up: number | null
  below_plan: boolean
}

export type Phase = 'starting' | 'selecting' | 'ping' | 'download' | 'upload'

export type LiveSnapshot = {
  type: 'snapshot'
  running: boolean
  result_id?: number
  source?: Source
  trigger?: string
  started_at?: string
  phase?: Phase
  server?: string
  location?: string
  ping_ms?: number | null
  download_mbps?: number | null
  upload_mbps?: number | null
  current_mbps?: number
  samples?: { phase: string; mbps: number }[]
}

export type LiveEvent =
  | LiveSnapshot
  | { type: 'phase'; phase: Phase }
  | { type: 'server'; name: string; location: string }
  | { type: 'ping'; ms: number }
  | { type: 'value'; phase: 'download' | 'upload'; mbps: number }
  | { type: 'done'; result: Result | null }

export type Described = { avg: number | null; min: number | null; max: number | null; median: number | null }

export type Stats = {
  tests: number
  ok: number
  failed: number
  below_plan: number
  download_mbps: Described
  upload_mbps: Described
  ping_ms: Described
  jitter_ms: Described
  packet_loss: Described
}

export type Schedule = {
  id: number
  name: string
  enabled: boolean
  mode: 'interval' | 'daily' | 'cron'
  interval_minutes: number
  daily_time: string
  cron: string
  days: number
  window_from: string
  window_to: string
  source: Source
  server_mode: 'auto' | 'fixed' | 'rotate'
  server_id: string
  random_offset: boolean
  next_run_at: string | null
  last_run_at: string | null
}

export type ScheduleInput = Omit<Schedule, 'id' | 'next_run_at' | 'last_run_at'>

export type ServerOption = { id: string; name: string; location: string; sponsor: string; host: string }

export type SourcesState = {
  sources: Record<Source, { enabled: boolean; switched_on: boolean }>
  ookla: { accepted_at: string | null; installed: boolean; version: string; favorites: string[] }
  librespeed: {
    public: boolean
    servers: { id: string; name: string; url: string }[]
    favorites: string[]
  }
}

export type NotifyKind = '' | 'ntfy' | 'gotify' | 'webhook'

export type Settings = {
  plan_down: number | null
  plan_up: number | null
  threshold_pct: number
  alert_below_plan: boolean
  alert_ping_enabled: boolean
  alert_ping_ms: number
  alert_failed: boolean
  notify_kind: NotifyKind
  notify_url_masked: string
  notify_url_set: boolean
  notify_token_set: boolean
  retention_days: number
  timezone: string
  timezone_default: string
  update_check: boolean
}

export type ApiKey = {
  id: number
  name: string
  prefix: string
  scope: 'read' | 'run'
  created_at: string
  last_used_at: string | null
}

export type AboutInfo = {
  version: string
  repo_url: string
  release_url: string
  license: string
  update_check: boolean
  update_checked: boolean
  latest_version: string | null
  update_available: boolean
  checked_at: string | null
}
