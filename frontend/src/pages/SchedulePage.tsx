import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../api/client'
import type { Schedule, ScheduleInput, ServerOption, Source, SourcesState } from '../api/types'
import { SOURCES } from '../api/types'
import { Dialog } from '../components/Dialog'
import { useNotice } from '../components/Notice'
import { Symbol } from '../components/Symbol'
import { Badge, Banner, Button, Card, EmptyState, Field, PageHeader, PageLoading, SelectField, Switch } from '../components/ui'
import { dateTime, relative } from '../lib/format'
import { useLoad } from '../lib/useLoad'

const DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const
const INTERVALS = [15, 30, 60, 120, 180, 360, 720]

const EMPTY: ScheduleInput = {
  name: '',
  enabled: true,
  mode: 'interval',
  interval_minutes: 120,
  daily_time: '04:00',
  cron: '0 */3 * * *',
  days: 127,
  window_from: '00:00',
  window_to: '00:00',
  source: 'cloudflare',
  server_mode: 'auto',
  server_id: '',
  random_offset: true,
}

export default function SchedulePage() {
  const { t } = useTranslation()
  const notify = useNotice()
  const schedules = useLoad(() => api.get<Schedule[]>('/api/schedules'))
  const sources = useLoad(() => api.get<SourcesState>('/api/sources'))
  const [editing, setEditing] = useState<Schedule | 'new' | null>(null)

  async function toggle(schedule: Schedule, enabled: boolean) {
    const { id: _id, next_run_at: _next, last_run_at: _last, ...input } = schedule
    try {
      await api.put(`/api/schedules/${schedule.id}`, { ...input, enabled })
      void schedules.reload()
    } catch (error) {
      notify(errorMessage(error))
    }
  }

  return (
    <div>
      <PageHeader
        title={t('schedule.title')}
        lead={t('schedule.lead')}
        aside={
          <Button onClick={() => setEditing('new')}>
            <Symbol name="plus" />
            {t('schedule.add')}
          </Button>
        }
      />
      {schedules.error && <Banner tone="bad">{schedules.error}</Banner>}
      {schedules.loading && !schedules.data ? (
        <PageLoading />
      ) : schedules.data?.length ? (
        <div className="flex flex-col gap-3">
          {schedules.data.map((schedule) => (
            <Card key={schedule.id} className="p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold">{schedule.name}</p>
                    <Badge>{t(`sources.${schedule.source}.name`)}</Badge>
                    {schedule.random_offset && <Badge>{t('schedule.offsetBadge')}</Badge>}
                    {sources.data && !sources.data.sources[schedule.source].enabled && <Badge tone="bad">{t('schedule.sourceOff')}</Badge>}
                  </div>
                  <p className="mt-1.5 text-sm text-mist-500">{describe(schedule, t)}</p>
                  <p className="mt-0.5 text-xs text-mist-600">
                    {schedule.enabled && schedule.next_run_at
                      ? t('schedule.nextRun', { when: dateTime(schedule.next_run_at), relative: relative(schedule.next_run_at) })
                      : t('schedule.paused')}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Button variant="ghost" size="sm" onClick={() => setEditing(schedule)}>
                    {t('common.edit')}
                  </Button>
                  <Switch label={t('schedule.enabled', { name: schedule.name })} hideLabel checked={schedule.enabled} onChange={(value) => void toggle(schedule, value)} />
                </div>
              </div>
            </Card>
          ))}
          <p className="text-xs text-mist-600">{t('schedule.noOverlap')}</p>
        </div>
      ) : (
        <EmptyState title={t('schedule.emptyTitle')}>
          <p>{t('schedule.emptyText')}</p>
          <Button className="mt-4" onClick={() => setEditing('new')}>
            {t('schedule.add')}
          </Button>
        </EmptyState>
      )}

      {editing && (
        <ScheduleDialog
          schedule={editing === 'new' ? null : editing}
          sources={sources.data}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            void schedules.reload()
          }}
        />
      )}
    </div>
  )
}

function describe(schedule: Schedule, t: (key: string, options?: Record<string, unknown>) => string): string {
  const parts: string[] = []
  if (schedule.mode === 'interval') parts.push(everyText(schedule.interval_minutes, t))
  else if (schedule.mode === 'daily') parts.push(t('schedule.dailyAt', { time: schedule.daily_time }))
  else parts.push(`cron ${schedule.cron}`)
  if (schedule.mode !== 'cron') {
    if (schedule.window_from !== schedule.window_to) parts.push(t('schedule.between', { from: schedule.window_from, to: schedule.window_to }))
    parts.push(schedule.days === 127 ? t('schedule.everyDay') : DAY_KEYS.filter((_, index) => schedule.days & (1 << index)).map((day) => t(`days.${day}`)).join(', '))
  }
  return parts.join(' · ')
}

function everyText(minutes: number, t: (key: string, options?: Record<string, unknown>) => string): string {
  return minutes % 60 === 0 ? t('schedule.everyHours', { count: minutes / 60 }) : t('schedule.everyMinutes', { count: minutes })
}

function ScheduleDialog({
  schedule,
  sources,
  onClose,
  onSaved,
}: {
  schedule: Schedule | null
  sources: SourcesState | undefined
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useTranslation()
  const notify = useNotice()
  const [form, setForm] = useState<ScheduleInput>(() => {
    if (!schedule) return EMPTY
    const { id: _id, next_run_at: _next, last_run_at: _last, ...input } = schedule
    return input
  })
  const [nameError, setNameError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<string[]>([])
  const [servers, setServers] = useState<ServerOption[]>([])
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const set = <K extends keyof ScheduleInput>(key: K, value: ScheduleInput[K]) => setForm((current) => ({ ...current, [key]: value }))

  useEffect(() => {
    const timer = window.setTimeout(() => {
      api
        .post<{ runs: string[] }>('/api/schedules/preview', { ...form, name: form.name || 'preview' })
        .then((answer) => {
          setPreview(answer.runs)
          setError(null)
        })
        .catch((caught) => {
          setPreview([])
          setError(errorMessage(caught))
        })
    }, 250)
    return () => window.clearTimeout(timer)
  }, [form])

  useEffect(() => {
    setServers([])
    if (form.source === 'cloudflare' || !sources?.sources[form.source].enabled) return
    api.get<ServerOption[]>(`/api/sources/${form.source}/servers`).then(setServers, () => setServers([]))
  }, [form.source, sources])

  const custom = form.mode === 'interval' && !INTERVALS.includes(form.interval_minutes)
  const frequency = form.mode === 'cron' ? 'cron' : form.mode === 'daily' ? 'daily' : custom ? 'custom' : String(form.interval_minutes)

  function setFrequency(value: string) {
    if (value === 'cron') set('mode', 'cron')
    else if (value === 'daily') set('mode', 'daily')
    else if (value === 'custom') setForm((current) => ({ ...current, mode: 'interval', interval_minutes: 90 }))
    else setForm((current) => ({ ...current, mode: 'interval', interval_minutes: Number(value) }))
  }

  const favorites = form.source === 'ookla' ? sources?.ookla.favorites : form.source === 'librespeed' ? sources?.librespeed.favorites : []

  async function save() {
    if (!form.name.trim()) {
      setNameError(t('schedule.nameRequired'))
      return
    }
    setSaving(true)
    try {
      if (schedule) await api.put(`/api/schedules/${schedule.id}`, form)
      else await api.post('/api/schedules', form)
      notify(t('schedule.saved'))
      onSaved()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setSaving(false)
    }
  }

  async function remove() {
    if (!schedule) return
    try {
      await api.delete(`/api/schedules/${schedule.id}`)
      notify(t('schedule.deleted'))
      onSaved()
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  return (
    <Dialog
      open
      title={schedule ? t('schedule.editTitle') : t('schedule.addTitle')}
      onClose={onClose}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          {schedule ? (
            confirmDelete ? (
              <Button variant="danger" size="sm" onClick={() => void remove()}>
                {t('schedule.deleteConfirm')}
              </Button>
            ) : (
              <Button variant="link" size="sm" onClick={() => setConfirmDelete(true)}>
                {t('schedule.delete')}
              </Button>
            )
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button loading={saving} onClick={() => void save()}>
              {t('common.save')}
            </Button>
          </div>
        </div>
      }
    >
      <Field
        label={t('schedule.name')}
        value={form.name}
        placeholder={t('schedule.namePlaceholder')}
        error={nameError}
        autoFocus
        onChange={(event) => {
          set('name', event.target.value)
          setNameError(null)
        }}
      />
      <SelectField label={t('schedule.frequency')} value={frequency} onChange={setFrequency}>
        {INTERVALS.map((minutes) => (
          <option key={minutes} value={minutes}>
            {everyText(minutes, t)}
          </option>
        ))}
        <option value="custom">{t('schedule.customInterval')}</option>
        <option value="daily">{t('schedule.onceADay')}</option>
        <option value="cron">{t('schedule.cron')}</option>
      </SelectField>
      {custom && (
        <Field
          label={t('schedule.minutes')}
          type="number"
          min={5}
          max={1440}
          value={form.interval_minutes}
          onChange={(event) => set('interval_minutes', Math.max(5, Number(event.target.value) || 5))}
        />
      )}
      {form.mode === 'daily' && <Field label={t('schedule.time')} type="time" value={form.daily_time} onChange={(event) => set('daily_time', event.target.value)} />}
      {form.mode === 'cron' ? (
        <Field label={t('schedule.cronExpression')} className="font-mono" value={form.cron} hint={t('schedule.cronHint')} onChange={(event) => set('cron', event.target.value)} />
      ) : (
        <>
          {form.mode === 'interval' && (
            <div className="flex flex-col gap-1.5">
              <p className="text-sm font-medium text-mist-300">{t('schedule.window')}</p>
              <div className="flex items-center gap-2">
                <input type="time" aria-label={t('schedule.windowFrom')} className="w-full rounded-xl border border-ink-700 bg-ink-900 px-3 py-2 text-mist-100" value={form.window_from} onChange={(event) => set('window_from', event.target.value)} />
                <span className="text-sm text-mist-500">{t('schedule.windowTo')}</span>
                <input type="time" aria-label={t('schedule.windowUntil')} className="w-full rounded-xl border border-ink-700 bg-ink-900 px-3 py-2 text-mist-100" value={form.window_to} onChange={(event) => set('window_to', event.target.value)} />
              </div>
              <p className="text-xs text-mist-500">{t('schedule.windowHint')}</p>
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-medium text-mist-300">{t('schedule.days')}</p>
            <div className="flex flex-wrap gap-1.5">
              {DAY_KEYS.map((day, index) => {
                const on = (form.days & (1 << index)) !== 0
                return (
                  <button
                    key={day}
                    type="button"
                    aria-pressed={on}
                    onClick={() => set('days', on ? form.days & ~(1 << index) || form.days : form.days | (1 << index))}
                    className={
                      'rounded-full border px-3 py-1 text-sm transition-colors ' +
                      (on ? 'border-accent-500/60 bg-accent-500/15 text-accent-400' : 'border-ink-700 bg-ink-900 text-mist-500 hover:text-mist-100')
                    }
                  >
                    {t(`days.${day}`)}
                  </button>
                )
              })}
            </div>
          </div>
        </>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField label={t('schedule.source')} value={form.source} onChange={(value) => setForm((current) => ({ ...current, source: value as Source, server_mode: 'auto', server_id: '' }))}>
          {SOURCES.map((name) => (
            <option key={name} value={name}>
              {t(`sources.${name}.name`)}
              {sources && !sources.sources[name].enabled ? ` (${t('schedule.off')})` : ''}
            </option>
          ))}
        </SelectField>
        <SelectField
          label={t('schedule.server')}
          value={form.server_mode === 'fixed' ? `fixed:${form.server_id}` : form.server_mode}
          disabled={form.source === 'cloudflare'}
          onChange={(value) => {
            if (value.startsWith('fixed:')) setForm((current) => ({ ...current, server_mode: 'fixed', server_id: value.slice(6) }))
            else setForm((current) => ({ ...current, server_mode: value as 'auto' | 'rotate', server_id: '' }))
          }}
        >
          <option value="auto">{form.source === 'cloudflare' ? t('live.cloudflareAuto') : t('live.nearest')}</option>
          {favorites && favorites.length > 0 && <option value="rotate">{t('schedule.rotate', { count: favorites.length })}</option>}
          {servers.map((server) => (
            <option key={server.id} value={`fixed:${server.id}`}>
              {server.name}
            </option>
          ))}
          {form.server_mode === 'fixed' && !servers.some((server) => server.id === form.server_id) && (
            <option value={`fixed:${form.server_id}`}>{form.server_id}</option>
          )}
        </SelectField>
      </div>
      <Switch label={t('schedule.offset')} hint={t('schedule.offsetHint')} checked={form.random_offset} onChange={(value) => set('random_offset', value)} />
      {error ? (
        <Banner tone="bad">{error}</Banner>
      ) : (
        <p className="text-sm text-mist-500">
          {preview.length ? t('schedule.preview', { runs: preview.map((run) => dateTime(run)).join(' · ') }) : t('schedule.previewNone')}
        </p>
      )}
    </Dialog>
  )
}
