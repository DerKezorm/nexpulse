import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, errorMessage, errorText } from '../api/client'
import type { Result, Settings, Stats } from '../api/types'
import { SOURCES } from '../api/types'
import { Dialog } from '../components/Dialog'
import { HistoryChart, type Metric } from '../components/HistoryChart'
import { useNotice } from '../components/Notice'
import { Symbol } from '../components/Symbol'
import { TabRow } from '../components/TabRow'
import { buttonClasses } from '../components/buttonClasses'
import { Badge, Banner, Button, Card, EmptyState, PageHeader, PageLoading, SELECT_CLASS } from '../components/ui'
import { dateTime, ms, percent, speed } from '../lib/format'
import { useLoad } from '../lib/useLoad'

type Range = '24h' | '7d' | '30d' | '90d'

export default function HistoryPage() {
  const { t } = useTranslation()
  const notify = useNotice()
  const [range, setRange] = useState<Range>('7d')
  const [source, setSource] = useState('')
  const [metric, setMetric] = useState<Metric>('speed')
  const [shown, setShown] = useState(15)
  const [removing, setRemoving] = useState<Result | null>(null)

  const query = `range=${range}${source ? `&source=${source}` : ''}`
  const results = useLoad(() => api.get<Result[]>(`/api/results?${query}`), [query])
  const stats = useLoad(() => api.get<Stats>(`/api/results/stats?${query}`), [query])
  const settings = useLoad(() => api.get<Settings>('/api/settings'))

  const planDown = settings.data?.plan_down ?? null
  const planUp = settings.data?.plan_up ?? null
  const threshold = settings.data?.threshold_pct ?? 75
  const newestFirst = [...(results.data ?? [])].reverse()

  async function remove() {
    if (!removing) return
    try {
      await api.delete(`/api/results/${removing.id}`)
      notify(t('history.deleted'))
      setRemoving(null)
      void results.reload()
      void stats.reload()
    } catch (error) {
      notify(errorMessage(error))
    }
  }

  return (
    <div>
      <PageHeader
        title={t('history.title')}
        lead={t('history.lead', { days: settings.data?.retention_days || '∞' })}
        aside={
          <div className="flex flex-wrap items-center gap-2">
            <TabRow
              small
              label={t('history.range')}
              active={range}
              onChange={setRange}
              tabs={(['24h', '7d', '30d', '90d'] as Range[]).map((value) => ({ value, label: t(`history.ranges.${value}`) }))}
            />
            <select className={SELECT_CLASS + ' py-1.5'} value={source} onChange={(event) => setSource(event.target.value)} aria-label={t('history.source')}>
              <option value="">{t('history.allSources')}</option>
              {SOURCES.map((name) => (
                <option key={name} value={name}>
                  {t(`sources.${name}.name`)}
                </option>
              ))}
            </select>
          </div>
        }
      />

      {results.error && <Banner tone="bad">{results.error}</Banner>}

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label={t('history.avgDown')} value={speed(stats.data?.download_mbps.avg)} unit="Mbit/s" share={planDown ? (stats.data?.download_mbps.avg ?? 0) / planDown : null} />
        <StatCard label={t('history.avgUp')} value={speed(stats.data?.upload_mbps.avg)} unit="Mbit/s" share={planUp ? (stats.data?.upload_mbps.avg ?? 0) / planUp : null} />
        <StatCard label={t('history.avgPing')} value={ms(stats.data?.ping_ms.avg, 1)} unit="ms" />
        <StatCard
          label={t('history.belowPlan', { pct: threshold })}
          value={String(stats.data?.below_plan ?? 0)}
          unit={t('history.ofTests', { count: stats.data?.ok ?? 0 })}
          note={stats.data?.failed ? t('history.failedCount', { count: stats.data.failed }) : undefined}
        />
      </div>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <TabRow
            small
            label={t('history.metric')}
            active={metric}
            onChange={setMetric}
            tabs={[
              { value: 'speed', label: t('history.metrics.speed') },
              { value: 'ping', label: t('history.metrics.ping') },
              { value: 'loss', label: t('history.metrics.loss') },
            ]}
          />
        </div>
        <div className="mt-4">
          {results.loading && !results.data ? (
            <PageLoading />
          ) : results.data && results.data.some((result) => result.status === 'ok') ? (
            <HistoryChart results={results.data} metric={metric} planDown={planDown} planUp={planUp} shortRange={range === '24h'} />
          ) : (
            <EmptyState title={t('history.emptyTitle')}>{t('history.emptyText')}</EmptyState>
          )}
        </div>
      </Card>

      <Card className="mt-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">{t('history.tests')}</h2>
          <a href="/api/results/export.csv" className={buttonClasses('ghost', 'sm')} download>
            {t('history.exportCsv')}
          </a>
        </div>
        {newestFirst.length === 0 ? (
          <p className="mt-3 text-sm text-mist-500">{t('history.noTests')}</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-700 text-left text-xs text-mist-600">
                  <th className="px-3 pb-2 font-medium">{t('history.columns.time')}</th>
                  <th className="px-3 pb-2 font-medium">{t('history.columns.source')}</th>
                  <th className="px-3 pb-2 text-right font-medium">{t('history.columns.down')}</th>
                  <th className="px-3 pb-2 text-right font-medium">{t('history.columns.up')}</th>
                  <th className="px-3 pb-2 text-right font-medium">{t('history.columns.ping')}</th>
                  <th className="hidden px-3 pb-2 text-right font-medium md:table-cell">{t('history.columns.jitter')}</th>
                  <th className="hidden px-3 pb-2 font-medium md:table-cell">{t('history.columns.server')}</th>
                  <th className="px-3 pb-2" />
                </tr>
              </thead>
              <tbody>
                {newestFirst.slice(0, shown).map((result) => (
                  <tr key={result.id} className="border-b border-ink-700 last:border-0">
                    <td className="px-3 py-2.5 whitespace-nowrap">{dateTime(result.started_at)}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        <Badge>{t(`sources.${result.source}.name`)}</Badge>
                        {result.trigger !== 'schedule' && <Badge tone="accent">{t(`trigger.${result.trigger}`)}</Badge>}
                      </div>
                    </td>
                    {result.status === 'ok' ? (
                      <>
                        <td className={'px-3 py-2.5 text-right tabular-nums ' + (result.below_plan ? 'text-bad-500' : '')}>{speed(result.download_mbps)}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums">{speed(result.upload_mbps)}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums">{ms(result.ping_ms)} ms</td>
                        <td className="hidden px-3 py-2.5 text-right tabular-nums md:table-cell">{ms(result.jitter_ms, 1)} ms</td>
                      </>
                    ) : (
                      <td colSpan={4} className="px-3 py-2.5 text-bad-500">
                        {result.status === 'cancelled' ? t('history.cancelled') : errorText(result.error_code) || t('history.failed')}
                      </td>
                    )}
                    <td className="hidden max-w-56 truncate px-3 py-2.5 text-mist-500 md:table-cell">
                      {result.server_name}
                      {result.packet_loss != null && ` · ${t('metrics.packetLoss')} ${percent(result.packet_loss)} %`}
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <button type="button" onClick={() => setRemoving(result)} className="rounded-full p-1.5 text-mist-600 hover:bg-ink-800 hover:text-bad-500" aria-label={t('history.delete')}>
                        <Symbol name="trash" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {newestFirst.length > shown && (
              <div className="mt-3 text-center">
                <Button variant="ghost" size="sm" onClick={() => setShown((count) => count + 30)}>
                  {t('history.showMore', { count: newestFirst.length - shown })}
                </Button>
              </div>
            )}
          </div>
        )}
      </Card>

      <Dialog
        open={removing != null}
        title={t('history.deleteTitle')}
        onClose={() => setRemoving(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRemoving(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" onClick={() => void remove()}>
              {t('history.delete')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-mist-300">{removing && t('history.deleteText', { when: dateTime(removing.started_at) })}</p>
      </Dialog>
    </div>
  )
}

function StatCard({ label, value, unit, share, note }: { label: string; value: string; unit: string; share?: number | null; note?: string }) {
  const { t } = useTranslation()
  return (
    <div className="rounded-2xl border border-ink-700 bg-ink-850/60 px-4 py-3.5">
      <p className="text-xs text-mist-600">{label}</p>
      <p className="mt-0.5 text-2xl font-bold tabular-nums">
        {value}
        <span className="ml-1 text-xs font-normal text-mist-500">{unit}</span>
      </p>
      {share != null && (
        <>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-700">
            <div className="h-full rounded-full bg-accent-500" style={{ width: `${Math.min(100, share * 100)}%` }} />
          </div>
          <p className="mt-1 text-xs text-mist-600">{t('history.ofPlan', { pct: Math.round(share * 100) })}</p>
        </>
      )}
      {note && <p className="mt-1 text-xs text-bad-500">{note}</p>}
    </div>
  )
}
