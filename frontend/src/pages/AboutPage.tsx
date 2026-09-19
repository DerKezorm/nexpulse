import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { AboutInfo } from '../api/types'
import { Logo } from '../components/Logo'
import { useNotice } from '../components/Notice'
import { Symbol } from '../components/Symbol'
import { Banner, Button, Card, PageHeader, PageLoading } from '../components/ui'
import { dateTime } from '../lib/format'
import { useLoad } from '../lib/useLoad'

/** Wer misst womit: Anbieter, ihre Bedingungen und ihr Datenschutz. */
const PROVIDERS = [
  {
    key: 'cloudflare',
    links: [
      { key: 'site', href: 'https://speed.cloudflare.com' },
      { key: 'source', href: 'https://github.com/cloudflare/speedtest' },
      { key: 'privacy', href: 'https://www.cloudflare.com/privacypolicy/' },
    ],
  },
  {
    key: 'librespeed',
    links: [
      { key: 'site', href: 'https://librespeed.org' },
      { key: 'source', href: 'https://github.com/librespeed/speedtest' },
      { key: 'servers', href: 'https://librespeed.org/backend-servers/servers.php' },
    ],
  },
  {
    key: 'ookla',
    links: [
      { key: 'site', href: 'https://www.speedtest.net/apps/cli' },
      { key: 'license', href: 'https://www.speedtest.net/about/eula' },
      { key: 'terms', href: 'https://www.speedtest.net/about/terms' },
      { key: 'privacy', href: 'https://www.speedtest.net/about/privacy' },
    ],
  },
] as const

export default function AboutPage() {
  const { t } = useTranslation()
  const notify = useNotice()
  const about = useLoad(() => api.get<AboutInfo>('/api/about'))
  const [checking, setChecking] = useState(false)

  async function check() {
    setChecking(true)
    try {
      about.set(await api.post<AboutInfo>('/api/about/check'))
    } catch (error) {
      notify(errorMessage(error))
    } finally {
      setChecking(false)
    }
  }

  const info = about.data
  if (!info) return about.error ? <Banner tone="bad">{about.error}</Banner> : <PageLoading />

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t('about.title')} />
      <Card>
        <div className="flex flex-wrap items-center gap-4">
          <Logo className="h-14 w-14" />
          <div>
            <p className="text-2xl font-bold tracking-tight">
              NEX<span className="text-accent-500">PULSE</span> <span className="text-base font-medium text-mist-500 tabular-nums">v{info.version}</span>
            </p>
            <p className="text-sm text-mist-500">{t('about.tagline')}</p>
          </div>
        </div>
        <div className="mt-5 flex flex-col gap-3 border-t border-ink-700 pt-4">
          {!info.update_check ? (
            <p className="text-sm text-mist-500">
              {t('about.checkOff')}{' '}
              <Link to="/settings?tab=data" className="text-accent-400 hover:underline">
                {t('about.checkOffLink')}
              </Link>
            </p>
          ) : info.update_available ? (
            <Banner tone="ok">
              {t('about.updateAvailable', { version: info.latest_version })}{' '}
              <a href={info.release_url} target="_blank" rel="noreferrer" className="font-semibold underline">
                {t('about.releaseNotes')}
              </a>
            </Banner>
          ) : (
            <p className="text-sm text-mist-500">
              {info.update_checked
                ? info.latest_version
                  ? t('about.upToDate', { when: dateTime(info.checked_at) })
                  : t('about.noRelease', { when: dateTime(info.checked_at) })
                : t('about.notChecked')}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {info.update_check && (
              <Button variant="ghost" size="sm" loading={checking} onClick={() => void check()}>
                <Symbol name="refresh" />
                {t('about.checkNow')}
              </Button>
            )}
            <a href={info.repo_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 px-2 text-sm text-accent-400 hover:underline">
              GitHub <Symbol name="external" className="h-3.5 w-3.5" />
            </a>
            <a href={info.release_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 px-2 text-sm text-accent-400 hover:underline">
              {t('about.releases')} <Symbol name="external" className="h-3.5 w-3.5" />
            </a>
            <a href="/api/docs" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 px-2 text-sm text-accent-400 hover:underline">
              {t('about.apiDocs')} <Symbol name="external" className="h-3.5 w-3.5" />
            </a>
          </div>
          <p className="text-xs text-mist-600">{t('about.license', { license: info.license })}</p>
        </div>
      </Card>

      <Card>
        <h2 className="text-lg font-semibold">{t('about.providers')}</h2>
        <p className="mt-1 text-sm text-mist-500">{t('about.providersIntro')}</p>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          {PROVIDERS.map((provider) => (
            <div key={provider.key} className="rounded-xl border border-ink-700 bg-ink-900 p-4">
              <p className="font-semibold">{t(`sources.${provider.key}.name`)}</p>
              <p className="mt-1 text-sm text-mist-500">{t(`about.provider.${provider.key}`)}</p>
              <ul className="mt-3 flex flex-col gap-1 text-sm">
                {provider.links.map((link) => (
                  <li key={link.href}>
                    <a href={link.href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent-400 hover:underline">
                      {t(`about.links.${link.key}`)}
                      <Symbol name="external" className="h-3.5 w-3.5" />
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <p className="mt-4 text-xs text-mist-600">{t('about.trademarks')}</p>
      </Card>
    </div>
  )
}
