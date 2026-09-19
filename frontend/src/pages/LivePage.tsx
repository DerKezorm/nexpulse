import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { api, errorMessage, errorText } from '../api/client'
import type { Result, Schedule, ServerOption, Settings, Source, SourcesState, Stats } from '../api/types'
import { SOURCES } from '../api/types'
import { Gauge, Sparkline } from '../components/Gauge'
import { useNotice } from '../components/Notice'
import { Symbol } from '../components/Symbol'
import { Badge, Banner, Button, Card, PageHeader, SELECT_CLASS } from '../components/ui'
import { dateTime, ms, percent, relative, speed } from '../lib/format'
import { useLive } from '../lib/useLive'
import { useLoad } from '../lib/useLoad'

const AUTO = ''

export default function LivePage() {
  const { t } = useTranslation()
  const notify = useNotice()
  const sources = useLoad(() => api.get<SourcesState>('/api/sources'))
  const latest = useLoad(() => api.get<Result | null>('/api/results/latest'))
  const stats = useLoad(() => api.get<Stats>('/api/results/stats?range=7d'))
  const settings = useLoad(() => api.get<Settings>('/api/settings'))
  const schedules = useLoad(() => api.get<Schedule[]>('/api/schedules'))

  const [source, setSource] = useState<Source>('cloudflare')
  const [serverId, setServerId] = useState(AUTO)
  const [servers, setServers] = useState<ServerOption[]>([])
  const [serversLoading, setServersLoading] = useState(false)
  const [starting, setStarting] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const { state: live, connected } = useLive((result) => {
    void latest.reload()
    void stats.reload()
    void schedules.reload()
    if (!result) return
    if (result.status === 'ok') notify(t('live.saved'))
    else if (result.status === 'failed') setFailure(errorText(result.error_code))
  })

  const enabled = SOURCES.filter((name) => sources.data?.sources[name].enabled)

  useEffect(() => {
    if (enabled.length && !enabled.includes(source)) setSource(enabled[0])
  }, [enabled, source])

  useEffect(() => {
    setServerId(AUTO)
    setServers([])
    if (source === 'cloudflare' || !enabled.includes(source)) return
    let cancelled = false
    setServersLoading(true)
    api
      .get<ServerOption[]>(`/api/sources/${source}/servers`)
      .then((found) => !cancelled && setServers(found))
      .catch(() => !cancelled && setServers([]))
      .finally(() => !cancelled && setServersLoading(false))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, sources.data])

  async function start() {
    setFailure(null)
    setStarting(true)
    try {
      await api.post('/api/tests', { source, server_id: serverId || null })
    } catch (error) {
      setFailure(errorMessage(error))
    } finally {
      setStarting(false)
    }
  }

  async function cancel() {
    try {
      await api.post('/api/tests/cancel')
    } catch (error) {
      notify(errorMessage(error))
    }
  }

  const upload = live.phase === 'upload'
  const shown = live.running ? live.current : live.phase === 'done' ? (live.download ?? 0) : (latest.data?.download_mbps ?? 0)
  const planDown = settings.data?.plan_down ?? 0
  const next = (schedules.data ?? [])
    .filter((schedule) => schedule.enabled && schedule.next_run_at)
    .map((schedule) => schedule.next_run_at as string)
    .sort()[0]

  return (
    <div>
      <PageHeader
        title={t('live.title')}
        lead={t('live.lead')}
        aside={
          next ? (
            <Badge>
              <span className="h-1.5 w-1.5 rounded-full bg-accent-500" />
              {t('live.nextScheduled', { when: relative(next) })}
            </Badge>
          ) : null
        }
      />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] lg:items-stretch">
        {/* Links Messung und Verbindung, rechts das letzte Ergebnis: So sind beide Spalten
            etwa gleich hoch, und kein Block haengt allein unten. */}
        <div className="flex flex-col gap-5">
        <Card className="p-5 sm:p-6">
          {/* Tacho links, die drei Werte daneben: So passt die Messung ohne Scrollen auf den Schirm. */}
          <div className="grid items-center gap-3 sm:grid-cols-[minmax(0,1fr)_10.5rem] sm:gap-4">
            <div className="relative mx-auto w-full max-w-[270px] text-center sm:max-w-[340px]">
              <Gauge value={shown} upload={upload} max={planDown} />
              <div className="absolute inset-x-0 top-[41%] text-center">
                <p className="text-4xl font-bold tracking-tighter tabular-nums sm:text-5xl">{speed(shown)}</p>
                <p className="mt-0.5 text-sm text-mist-500">Mbit/s</p>
                <p className="mt-1.5 inline-flex min-h-5 items-center gap-1.5 text-xs text-mist-500 sm:text-sm" aria-live="polite">
                  {live.running && live.phase === 'download' && <Symbol name="down" className="h-3.5 w-3.5 text-accent-500" />}
                  {live.running && live.phase === 'upload' && <Symbol name="up" className="h-3.5 w-3.5 text-up-400" />}
                  {live.running ? t(`live.phase.${live.phase}`) : live.phase === 'done' ? t('live.phase.done') : t('live.phase.idle')}
                </p>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-1 sm:gap-3">
              <PhaseTile label={t('metrics.ping')} value={ms(live.running || live.phase === 'done' ? live.ping : latest.data?.ping_ms)} unit="ms" active={live.running && live.phase === 'ping'} />
              <PhaseTile
                label={t('metrics.download')}
                value={speed(live.running || live.phase === 'done' ? live.download : latest.data?.download_mbps)}
                unit="Mbit/s"
                active={live.running && live.phase === 'download'}
                symbol="down"
              />
              <PhaseTile
                label={t('metrics.upload')}
                value={speed(live.running || live.phase === 'done' ? live.upload : latest.data?.upload_mbps)}
                unit="Mbit/s"
                active={live.running && live.phase === 'upload'}
                symbol="up"
                upload
              />
            </div>
          </div>
          {live.samples.length > 1 && (
            <div className="mt-2">
              <Sparkline samples={live.samples} />
            </div>
          )}

          <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_auto] xl:items-end">
            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] xl:contents">
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-mist-300">{t('live.source')}</span>
                <select className={SELECT_CLASS} value={source} disabled={live.running} onChange={(event) => setSource(event.target.value as Source)}>
                  {enabled.map((name) => (
                    <option key={name} value={name}>
                      {t(`sources.${name}.name`)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-mist-300">{t('live.server')}</span>
                <select
                  className={SELECT_CLASS}
                  value={serverId}
                  disabled={live.running || source === 'cloudflare' || serversLoading}
                  onChange={(event) => setServerId(event.target.value)}
                >
                  <option value={AUTO}>{source === 'cloudflare' ? t('live.cloudflareAuto') : t('live.nearest')}</option>
                  {servers.map((server) => (
                    <option key={server.id} value={server.id}>
                      {server.sponsor && server.sponsor !== server.name ? `${server.sponsor} · ` : ''}
                      {server.name}
                      {server.location && !server.name.includes(server.location) ? ` · ${server.location}` : ''}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {live.running ? (
              <Button variant="ghost" className="py-3" onClick={() => void cancel()}>
                {t('live.cancel')}
              </Button>
            ) : (
              <Button className="py-3" loading={starting} disabled={!enabled.length} onClick={() => void start()}>
                <Symbol name="play" />
                {t('live.start')}
              </Button>
            )}
          </div>
          {failure && (
            <div className="mt-4">
              <Banner tone="bad">{failure}</Banner>
            </div>
          )}
          {!connected && (
            <div className="mt-4">
              <Banner>{t('live.reconnecting')}</Banner>
            </div>
          )}
        </Card>
          <Connection result={latest.data ?? null} live={live.running ? { server: live.server, location: live.location } : null} settings={settings.data} />
        </div>

        <LastResult result={latest.data ?? null} stats={stats.data} />
      </div>
    </div>
  )
}

function PhaseTile({
  label,
  value,
  unit,
  active,
  symbol,
  upload = false,
}: {
  label: string
  value: string
  unit: string
  active: boolean
  symbol?: 'down' | 'up'
  upload?: boolean
}) {
  return (
    <div className={'rounded-xl border bg-ink-900 px-3 py-2.5 transition-colors ' + (active ? (upload ? 'border-up-400' : 'border-accent-500') : 'border-ink-700')}>
      <p className="flex items-center gap-1.5 truncate text-xs text-mist-600">
        {symbol && <Symbol name={symbol} className={'h-3 w-3 ' + (upload ? 'text-up-400' : 'text-accent-500')} />}
        {label}
      </p>
      <p className="text-lg font-bold tabular-nums sm:text-2xl">
        {value}
        <span className="ml-1 block text-xs font-normal text-mist-500 sm:inline">{unit}</span>
      </p>
    </div>
  )
}

function Delta({ value, average, lowerIsBetter = false }: { value: number | null; average: number | null | undefined; lowerIsBetter?: boolean }) {
  const { t } = useTranslation()
  if (value == null || !average) return null
  const change = ((value - average) / average) * 100
  const good = lowerIsBetter ? change <= 0 : change >= 0
  // Unter einem halben Prozent ist es weder besser noch schlechter, sondern gleich.
  const tone = Math.abs(change) < 0.5 ? 'text-mist-500' : good ? 'text-accent-400' : 'text-bad-500'
  return (
    <p className="text-xs">
      <span className={tone}>
        {Math.round(change) > 0 ? '+' : ''}
        {Math.round(change)} %
      </span>{' '}
      <span className="text-mist-600">{t('live.vsAverage')}</span>
    </p>
  )
}

function Tile({ label, value, unit, children }: { label: string; value: string; unit: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col justify-center rounded-xl border border-ink-700 bg-ink-900 px-3.5 py-2.5">
      <p className="text-xs text-mist-600">{label}</p>
      <p className="text-xl font-bold tabular-nums">
        {value}
        <span className="ml-1 text-xs font-normal text-mist-500">{unit}</span>
      </p>
      {children}
    </div>
  )
}

function LastResult({ result, stats }: { result: Result | null; stats: Stats | undefined }) {
  const { t } = useTranslation()
  if (!result) {
    return (
      <Card>
        <h2 className="text-lg font-semibold">{t('live.lastResult')}</h2>
        <p className="mt-2 text-sm text-mist-500">{t('live.noResultYet')}</p>
      </Card>
    )
  }
  return (
    <Card className="flex flex-col">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">{t('live.lastResult')}</h2>
        <Badge>
          {dateTime(result.started_at)} · {t(`trigger.${result.trigger}`)}
        </Badge>
      </div>
      {/* Die Kacheln fuellen die Hoehe der linken Spalte, statt unten Leere zu lassen. */}
      <div className="mt-4 grid flex-1 auto-rows-fr grid-cols-2 gap-2.5">
        <Tile label={t('metrics.download')} value={speed(result.download_mbps)} unit="Mbit/s">
          <Delta value={result.download_mbps} average={stats?.download_mbps.avg} />
        </Tile>
        <Tile label={t('metrics.upload')} value={speed(result.upload_mbps)} unit="Mbit/s">
          <Delta value={result.upload_mbps} average={stats?.upload_mbps.avg} />
        </Tile>
        <Tile label={t('metrics.ping')} value={ms(result.ping_ms)} unit="ms">
          <Delta value={result.ping_ms} average={stats?.ping_ms.avg} lowerIsBetter />
        </Tile>
        <Tile label={t('metrics.jitter')} value={ms(result.jitter_ms, 1)} unit="ms">
          <Delta value={result.jitter_ms} average={stats?.jitter_ms.avg} lowerIsBetter />
        </Tile>
        <Tile label={t('metrics.packetLoss')} value={percent(result.packet_loss)} unit={result.packet_loss == null ? '' : '%'}>
          {result.packet_loss == null && <p className="text-xs text-mist-600">{t('live.lossNotMeasured')}</p>}
        </Tile>
        <Tile label={t('metrics.loaded')} value={`${ms(result.loaded_down_ms)} / ${ms(result.loaded_up_ms)}`} unit="ms">
          <p className="text-xs text-mist-600">{t('live.loadedHint')}</p>
        </Tile>
      </div>
      {result.below_plan && (
        <div className="mt-3">
          <Banner tone="bad">{t('live.belowPlan')}</Banner>
        </div>
      )}
    </Card>
  )
}

function Connection({
  result,
  live,
  settings,
}: {
  result: Result | null
  live: { server: string; location: string } | null
  settings: Settings | undefined
}) {
  const { t } = useTranslation()
  const server = live ? [live.server, live.location].filter(Boolean).join(' · ') : result ? [result.server_name, result.server_location].filter(Boolean).join(' · ') : ''
  return (
    <Card>
      <h2 className="text-lg font-semibold">{t('live.connection')}</h2>
      <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
        <dt className="text-mist-600">{t('live.server')}</dt>
        <dd className="truncate text-right">{server || '–'}</dd>
        <dt className="text-mist-600">{t('live.provider')}</dt>
        <dd className="truncate text-right">{result?.isp || '–'}</dd>
        <dt className="text-mist-600">{t('live.externalIp')}</dt>
        <dd className="truncate text-right font-mono text-xs leading-5">{result?.external_ip || '–'}</dd>
        <dt className="text-mist-600">{t('live.plan')}</dt>
        <dd className="text-right">
          {settings?.plan_down || settings?.plan_up ? (
            `${settings.plan_down ?? '–'} / ${settings.plan_up ?? '–'} Mbit/s`
          ) : (
            <Link to="/settings?tab=plan" className="text-accent-400 hover:underline">
              {t('live.setPlan')}
            </Link>
          )}
        </dd>
      </dl>
      {result?.result_url && (
        <a href={result.result_url} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-sm text-accent-400 hover:underline">
          {t('live.ooklaResult')} <Symbol name="external" className="h-3.5 w-3.5" />
        </a>
      )}
    </Card>
  )
}
