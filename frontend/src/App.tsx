import { useTranslation } from 'react-i18next'
import { Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from './auth'
import { AppShell } from './components/AppShell'
import { NoticeProvider } from './components/Notice'
import { Banner, PageLoading } from './components/ui'
import AboutPage from './pages/AboutPage'
import HistoryPage from './pages/HistoryPage'
import LivePage from './pages/LivePage'
import LoginPage from './pages/LoginPage'
import SchedulePage from './pages/SchedulePage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  const { t } = useTranslation()
  const { config, failed } = useAuth()

  if (!config) {
    return (
      <div className="mx-auto max-w-md px-4 py-16">
        {failed ? <Banner tone="bad">{t('errors.network')}</Banner> : <PageLoading />}
      </div>
    )
  }
  if (!config.signed_in) return <LoginPage />

  return (
    <NoticeProvider>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<LivePage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="schedule" element={<SchedulePage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="about" element={<AboutPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </NoticeProvider>
  )
}
