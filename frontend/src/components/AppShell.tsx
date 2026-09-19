import { useTranslation } from 'react-i18next'
import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../auth'
import { useLoad } from '../lib/useLoad'
import { api } from '../api/client'
import type { AboutInfo } from '../api/types'
import { Logo } from './Logo'
import { LanguageSwitcher, ThemeSwitcher } from './Switchers'
import { Symbol, type SymbolName } from './Symbol'

type NavItem = { to: string; label: string; symbol: SymbolName; end: boolean; right?: boolean }

function navClass(isActive: boolean, compact: boolean, right = false): string {
  return (
    (compact ? 'shrink-0 px-3 ' : 'px-3.5 ') +
    (right ? 'ml-auto ' : '') +
    'inline-flex items-center gap-2 rounded-full py-1.5 text-sm font-medium transition-colors ' +
    (isActive ? 'bg-accent-500/15 text-accent-400' : 'text-mist-500 hover:bg-ink-850 hover:text-mist-100')
  )
}

/** Rahmen wie nexcrate und Nexview: Kopfzeile mit Pillen, Einstellungen rechts, Inhalt, Fusszeile. */
export function AppShell() {
  const { t } = useTranslation()
  const { config, signOut } = useAuth()
  const about = useLoad(() => api.get<AboutInfo>('/api/about'))

  const items: NavItem[] = [
    { to: '/', label: t('nav.live'), symbol: 'live', end: true },
    { to: '/history', label: t('nav.history'), symbol: 'history', end: false },
    { to: '/schedule', label: t('nav.schedule'), symbol: 'schedule', end: false },
    { to: '/settings', label: t('nav.settings'), symbol: 'settings', end: false, right: true },
  ]

  const render = (item: NavItem, compact: boolean) => (
    <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => navClass(isActive, compact, item.right)}>
      {/* Auf schmalen Telefonen fallen die Symbole weg, sonst passen die vier Punkte nicht. */}
      <span className={compact ? 'hidden min-[441px]:inline' : ''}>
        <Symbol name={item.symbol} />
      </span>
      {item.label}
    </NavLink>
  )

  return (
    <div className="np-glow flex min-h-dvh flex-col">
      <header className="sticky top-0 z-20 border-b border-ink-700/80 bg-ink-950/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3 sm:px-6">
          <NavLink to="/" className="shrink-0" aria-label={t('nav.home')}>
            <Logo withWordmark />
          </NavLink>
          <nav className="hidden flex-1 items-center gap-1 lg:flex" aria-label={t('nav.main')}>
            {items.map((item) => render(item, false))}
          </nav>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <ThemeSwitcher />
            <LanguageSwitcher />
            {config?.password_required && (
              <button
                type="button"
                onClick={() => void signOut()}
                className="rounded-full border border-ink-700 bg-ink-850 p-1.5 text-mist-500 hover:text-mist-100"
                title={t('auth.signOut')}
                aria-label={t('auth.signOut')}
              >
                <Symbol name="logout" />
              </button>
            )}
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto border-t border-ink-700/60 px-4 py-2 lg:hidden" aria-label={t('nav.main')}>
          {items.map((item) => render(item, true))}
        </nav>
      </header>

      <main className="relative z-10 mx-auto w-full max-w-7xl flex-1 px-4 pt-8 pb-16 sm:px-6">
        <Outlet />
      </main>

      <footer className="relative z-10 border-t border-ink-700/60">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-center gap-x-4 gap-y-2 px-4 py-5 text-xs text-mist-600 sm:px-6">
          <NavLink to="/about" className="transition-colors hover:text-mist-300">
            {t('about.title')}
          </NavLink>
          <span aria-hidden="true">·</span>
          <span className="tabular-nums">v{config?.version ?? ''}</span>
          {about.data?.update_available && (
            <NavLink
              to="/about"
              className="inline-flex items-center gap-1.5 rounded-full bg-accent-500/15 px-2.5 py-1 font-medium text-accent-400 transition-colors hover:bg-accent-500/25"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-accent-400" aria-hidden="true" />
              {t('about.updateShort')}
            </NavLink>
          )}
        </div>
      </footer>
    </div>
  )
}
