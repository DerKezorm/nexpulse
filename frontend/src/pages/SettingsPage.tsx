import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { TabRow } from '../components/TabRow'
import { PageHeader } from '../components/ui'
import AccessTab from './settings/AccessTab'
import DataTab from './settings/DataTab'
import PlanTab from './settings/PlanTab'
import SourcesTab from './settings/SourcesTab'

const TABS = ['sources', 'access', 'plan', 'data'] as const
type TabName = (typeof TABS)[number]

export default function SettingsPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  // Der Reiter steht in der Adresse, der erste nicht, wie in nexcrate.
  const tab: TabName = TABS.includes(requested as TabName) ? (requested as TabName) : 'sources'

  return (
    <div>
      <PageHeader title={t('settings.title')} lead={t('settings.lead')} />
      <div className="mb-6">
        <TabRow
          label={t('settings.title')}
          active={tab}
          onChange={(next) => setParams(next === 'sources' ? {} : { tab: next }, { replace: true })}
          tabs={[
            { value: 'sources', label: t('settings.tabs.sources'), symbol: 'globe' },
            { value: 'access', label: t('settings.tabs.access'), symbol: 'key' },
            { value: 'plan', label: t('settings.tabs.plan'), symbol: 'plan' },
            { value: 'data', label: t('settings.tabs.data'), symbol: 'data' },
          ]}
        />
      </div>
      {tab === 'sources' && <SourcesTab />}
      {tab === 'access' && <AccessTab />}
      {tab === 'plan' && <PlanTab />}
      {tab === 'data' && <DataTab />}
    </div>
  )
}
