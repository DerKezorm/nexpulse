import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../../api/client'
import type { Settings } from '../../api/types'
import { useNotice } from '../../components/Notice'
import { buttonClasses } from '../../components/buttonClasses'
import { Banner, PageLoading, Section, SelectField, Switch } from '../../components/ui'
import { useLoad } from '../../lib/useLoad'

const RETENTION = [30, 90, 180, 365, 730, 0]

export default function DataTab() {
  const { t } = useTranslation()
  const notify = useNotice()
  const settings = useLoad(() => api.get<Settings>('/api/settings'))
  const zones = useLoad(() => api.get<string[]>('/api/settings/timezones'))

  async function save(body: Record<string, unknown>) {
    try {
      settings.set(await api.put<Settings>('/api/settings', body))
      notify(t('common.saved'))
    } catch (error) {
      notify(errorMessage(error))
    }
  }

  const data = settings.data
  if (!data) return settings.error ? <Banner tone="bad">{settings.error}</Banner> : <PageLoading />

  return (
    <div className="flex flex-col gap-5">
      <Section title={t('data.results')} intro={t('data.resultsIntro')}>
        <div className="grid gap-3 sm:grid-cols-2">
          <SelectField label={t('data.retention')} value={String(data.retention_days)} onChange={(value) => void save({ retention_days: Number(value) })}>
            {RETENTION.map((days) => (
              <option key={days} value={days}>
                {days ? t('data.days', { count: days }) : t('data.forever')}
              </option>
            ))}
          </SelectField>
          <SelectField label={t('data.timezone')} value={data.timezone} onChange={(value) => void save({ timezone: value })}>
            {(zones.data ?? [data.timezone]).map((zone) => (
              <option key={zone} value={zone}>
                {zone}
              </option>
            ))}
          </SelectField>
        </div>
        <p className="text-xs text-mist-500">{t('data.timezoneHint', { zone: data.timezone_default })}</p>
        <div>
          <a href="/api/results/export.csv" download className={buttonClasses('ghost', 'sm')}>
            {t('data.export')}
          </a>
        </div>
      </Section>
      <Section title={t('data.updates')} intro={t('data.updatesIntro')}>
        <Switch label={t('data.updateCheck')} hint={t('data.updateCheckHint')} checked={data.update_check} onChange={(value) => void save({ update_check: value })} />
      </Section>
    </div>
  )
}
