import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../../api/client'
import type { NotifyKind, Settings } from '../../api/types'
import { useNotice } from '../../components/Notice'
import { Banner, Button, Field, PageLoading, Section, SelectField, Switch } from '../../components/ui'
import { useLoad } from '../../lib/useLoad'

/** Tarif und Warnungen teilen sich Laden und Speichern, zeigen aber je einen eigenen Reiter. */
export default function PlanTab({ part }: { part: 'plan' | 'alerts' }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const settings = useLoad(() => api.get<Settings>('/api/settings'))
  const [down, setDown] = useState('')
  const [up, setUp] = useState('')
  const [threshold, setThreshold] = useState('75')
  const [pingLimit, setPingLimit] = useState('40')
  const [kind, setKind] = useState<NotifyKind>('')
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [urlError, setUrlError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  useEffect(() => {
    const data = settings.data
    if (!data) return
    setDown(data.plan_down == null ? '' : String(data.plan_down))
    setUp(data.plan_up == null ? '' : String(data.plan_up))
    setThreshold(String(data.threshold_pct))
    setPingLimit(String(data.alert_ping_ms))
    setKind(data.notify_kind)
  }, [settings.data])

  async function save(body: Record<string, unknown>, message = t('common.saved')) {
    setError(null)
    try {
      settings.set(await api.put<Settings>('/api/settings', body))
      notify(message)
      return true
    } catch (caught) {
      setError(errorMessage(caught))
      return false
    }
  }

  async function savePlan() {
    setSaving(true)
    await save({
      plan_down: down ? Number(down) : null,
      plan_up: up ? Number(up) : null,
      threshold_pct: Number(threshold),
    })
    setSaving(false)
  }

  async function saveNotify() {
    if (kind && !url.trim() && !settings.data?.notify_url_set) {
      setUrlError(t('plan.urlRequired'))
      return
    }
    if (url.trim() && !/^https?:\/\//i.test(url.trim())) {
      setUrlError(t('plan.urlInvalid'))
      return
    }
    setSaving(true)
    const ok = await save({ notify_kind: kind, notify_url: url.trim() || undefined, notify_token: token.trim() || undefined })
    if (ok) {
      setUrl('')
      setToken('')
    }
    setSaving(false)
  }

  async function sendTest() {
    setTesting(true)
    try {
      await api.post('/api/settings/notify/test')
      notify(t('plan.testSent'))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setTesting(false)
    }
  }

  const data = settings.data
  if (!data) return settings.error ? <Banner tone="bad">{settings.error}</Banner> : <PageLoading />

  return (
    <div className="flex flex-col gap-5">
      {error && <Banner tone="bad">{error}</Banner>}
      {part === 'plan' && (
      <Section title={t('plan.title')} intro={t('plan.intro')}>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t('plan.down')} type="number" min={0} inputMode="decimal" value={down} placeholder="1000" onChange={(event) => setDown(event.target.value)} />
          <Field label={t('plan.up')} type="number" min={0} inputMode="decimal" value={up} placeholder="50" onChange={(event) => setUp(event.target.value)} />
          <SelectField label={t('plan.threshold')} value={threshold} onChange={setThreshold}>
            {[95, 90, 80, 75, 50].map((value) => (
              <option key={value} value={value}>
                {t('plan.thresholdOption', { pct: value })}
              </option>
            ))}
          </SelectField>
        </div>
        <div>
          <Button size="sm" loading={saving} onClick={() => void savePlan()}>
            {t('common.save')}
          </Button>
        </div>
      </Section>

      )}

      {part === 'alerts' && (
        <>
      <Section title={t('plan.alerts')} intro={t('plan.alertsIntro')}>
        <Switch label={t('plan.alertBelow')} checked={data.alert_below_plan} onChange={(value) => void save({ alert_below_plan: value })} />
        <Switch label={t('plan.alertFailed')} checked={data.alert_failed} onChange={(value) => void save({ alert_failed: value })} />
        <Switch label={t('plan.alertPing', { ms: data.alert_ping_ms })} checked={data.alert_ping_enabled} onChange={(value) => void save({ alert_ping_enabled: value })} />
        {data.alert_ping_enabled && (
          <div className="flex max-w-xs items-end gap-2">
            <Field label={t('plan.pingLimit')} type="number" min={1} value={pingLimit} onChange={(event) => setPingLimit(event.target.value)} />
            <Button variant="ghost" size="sm" className="mb-1" onClick={() => void save({ alert_ping_ms: Math.max(1, Number(pingLimit) || 1) })}>
              {t('common.save')}
            </Button>
          </div>
        )}
      </Section>

      <Section title={t('plan.notify')} intro={t('plan.notifyIntro')}>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)]">
          <SelectField label={t('plan.notifyKind')} value={kind} onChange={(value) => setKind(value as NotifyKind)}>
            <option value="">{t('plan.notifyNone')}</option>
            <option value="ntfy">ntfy</option>
            <option value="gotify">Gotify</option>
            <option value="webhook">{t('plan.webhook')}</option>
          </SelectField>
          {kind && (
            <Field
              label={t(`plan.url.${kind}`)}
              type="url"
              value={url}
              placeholder={data.notify_url_set ? data.notify_url_masked : t(`plan.urlPlaceholder.${kind}`)}
              error={urlError}
              hint={data.notify_url_set ? t('plan.keepHint') : undefined}
              onChange={(event) => {
                setUrl(event.target.value)
                setUrlError(null)
              }}
            />
          )}
        </div>
        {kind && (
          <Field
            label={t(`plan.token.${kind}`)}
            type="password"
            autoComplete="off"
            value={token}
            placeholder={data.notify_token_set ? '••••••••' : t('plan.optional')}
            onChange={(event) => setToken(event.target.value)}
          />
        )}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" loading={saving} onClick={() => void saveNotify()}>
            {t('common.save')}
          </Button>
          {data.notify_kind && data.notify_url_set && (
            <Button variant="ghost" size="sm" loading={testing} onClick={() => void sendTest()}>
              {t('plan.sendTest')}
            </Button>
          )}
        </div>
      </Section>
        </>
      )}
    </div>
  )
}
