import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../../api/client'
import type { ServerOption, Source, SourcesState } from '../../api/types'
import { Dialog } from '../../components/Dialog'
import { useNotice } from '../../components/Notice'
import { Symbol } from '../../components/Symbol'
import { Badge, Banner, Button, Card, Field, PageLoading, Switch } from '../../components/ui'
import { dateTime } from '../../lib/format'
import { useLoad } from '../../lib/useLoad'

const OOKLA_LINKS = [
  { key: 'license', href: 'https://www.speedtest.net/about/eula' },
  { key: 'terms', href: 'https://www.speedtest.net/about/terms' },
  { key: 'privacy', href: 'https://www.speedtest.net/about/privacy' },
]

export default function SourcesTab() {
  const { t } = useTranslation()
  const notify = useNotice()
  const state = useLoad(() => api.get<SourcesState>('/api/sources'))
  const [activating, setActivating] = useState(false)
  const [removingOokla, setRemovingOokla] = useState(false)

  async function update(body: Record<string, unknown>) {
    try {
      state.set(await api.put<SourcesState>('/api/sources', body))
    } catch (error) {
      notify(errorMessage(error))
    }
  }

  async function removeOokla() {
    try {
      state.set(await api.delete<SourcesState>('/api/sources/ookla'))
      setRemovingOokla(false)
      notify(t('sources.ookla.removed'))
    } catch (error) {
      notify(errorMessage(error))
    }
  }

  if (!state.data) return state.error ? <Banner tone="bad">{state.error}</Banner> : <PageLoading />
  const data = state.data
  const toggle = (source: Source, on: boolean) => void update({ sources: { [source]: on } })

  return (
    <div className="flex flex-col gap-4">
      <SourceCard
        mark="CF"
        title={t('sources.cloudflare.name')}
        badge={<Badge tone="accent">{t('sources.default')}</Badge>}
        on={data.sources.cloudflare.switched_on}
        onToggle={(on) => toggle('cloudflare', on)}
      >
        <p>{t('sources.cloudflare.text')}</p>
        <Links links={[{ label: t('sources.cloudflare.site'), href: 'https://speed.cloudflare.com' }]} />
      </SourceCard>

      <SourceCard mark="LS" title={t('sources.librespeed.name')} on={data.sources.librespeed.switched_on} onToggle={(on) => toggle('librespeed', on)}>
        <p>{t('sources.librespeed.text')}</p>
        <Links links={[{ label: t('sources.librespeed.site'), href: 'https://librespeed.org' }]} />
        <div className="mt-2">
          <Switch
            label={t('sources.librespeed.public')}
            hint={t('sources.librespeed.publicHint')}
            checked={data.librespeed.public}
            onChange={(value) => void update({ librespeed_public: value })}
          />
        </div>
        <OwnServers state={data} onChange={state.set} />
        {data.sources.librespeed.enabled && (
          <Favorites
            source="librespeed"
            favorites={data.librespeed.favorites}
            onChange={(favorites) => void update({ librespeed_favorites: favorites })}
          />
        )}
      </SourceCard>

      <SourceCard
        mark="O"
        title={t('sources.ookla.name')}
        badge={data.ookla.accepted_at ? <Badge tone="accent">{t('sources.ookla.active')}</Badge> : <Badge>{t('sources.ookla.inactive')}</Badge>}
        on={data.sources.ookla.switched_on && Boolean(data.ookla.accepted_at)}
        disabled={!data.ookla.accepted_at}
        onToggle={(on) => toggle('ookla', on)}
      >
        <p>{t('sources.ookla.text')}</p>
        <Links links={[{ label: t('sources.ookla.site'), href: 'https://www.speedtest.net/apps/cli' }, ...OOKLA_LINKS.map((link) => ({ label: t(`sources.ookla.${link.key}`), href: link.href }))]} />
        {data.ookla.accepted_at ? (
          <>
            <p className="text-xs text-mist-600">{t('sources.ookla.acceptedAt', { when: dateTime(data.ookla.accepted_at) })}</p>
            {data.sources.ookla.enabled && (
              <Favorites source="ookla" favorites={data.ookla.favorites} onChange={(favorites) => void update({ ookla_favorites: favorites })} />
            )}
            <div>
              <Button variant="link" size="sm" className="px-0" onClick={() => setRemovingOokla(true)}>
                {t('sources.ookla.remove')}
              </Button>
            </div>
          </>
        ) : (
          <div>
            <Button variant="ghost" size="sm" onClick={() => setActivating(true)}>
              {t('sources.ookla.activate')}
            </Button>
          </div>
        )}
      </SourceCard>

      <SourceCard
        mark="IP3"
        title={t('sources.iperf3.name')}
        on={data.sources.iperf3.switched_on && data.iperf3.available}
        disabled={!data.iperf3.available}
        onToggle={(on) => toggle('iperf3', on)}
      >
        <p>{t('sources.iperf3.text')}</p>
        <Links links={[{ label: t('sources.iperf3.site'), href: 'https://software.es.net/iperf/' }]} />
        {data.iperf3.available ? (
          <>
            <Targets state={data} onChange={state.set} />
            {data.sources.iperf3.enabled && (
              <Favorites
                source="iperf3"
                favorites={data.iperf3.favorites}
                onChange={(favorites) => void update({ iperf3_favorites: favorites })}
              />
            )}
          </>
        ) : (
          <Banner tone="bad">{t('sources.iperf3.unavailable')}</Banner>
        )}
      </SourceCard>

      {activating && (
        <ActivateOokla
          onClose={() => setActivating(false)}
          onDone={(next) => {
            state.set(next)
            setActivating(false)
            notify(t('sources.ookla.activated'))
          }}
        />
      )}
      <Dialog
        open={removingOokla}
        title={t('sources.ookla.removeTitle')}
        onClose={() => setRemovingOokla(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRemovingOokla(false)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" onClick={() => void removeOokla()}>
              {t('sources.ookla.remove')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-mist-300">{t('sources.ookla.removeText')}</p>
      </Dialog>
    </div>
  )
}

function SourceCard({
  mark,
  title,
  badge,
  on,
  disabled = false,
  onToggle,
  children,
}: {
  mark: string
  title: string
  badge?: React.ReactNode
  on: boolean
  disabled?: boolean
  onToggle: (on: boolean) => void
  children: React.ReactNode
}) {
  const { t } = useTranslation()
  return (
    <Card className="p-5">
      <div className="flex items-start gap-4">
        <div className="hidden h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-ink-800 text-sm font-bold text-accent-400 sm:flex">{mark}</div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold">{title}</h2>
              {badge}
            </div>
            <Switch label={t('sources.use', { name: title })} hideLabel checked={on} disabled={disabled} onChange={onToggle} />
          </div>
          <div className="mt-2 flex flex-col gap-3 text-sm text-mist-500">{children}</div>
        </div>
      </div>
    </Card>
  )
}

function Links({ links }: { links: { label: string; href: string }[] }) {
  return (
    <p className="flex flex-wrap gap-x-4 gap-y-1">
      {links.map((link) => (
        <a key={link.href} href={link.href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent-400 hover:underline">
          {link.label}
          <Symbol name="external" className="h-3.5 w-3.5" />
        </a>
      ))}
    </p>
  )
}

function OwnServers({ state, onChange }: { state: SourcesState; onChange: (next: SourcesState) => void }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  async function add() {
    if (!url.trim()) {
      setError(t('sources.librespeed.urlRequired'))
      return
    }
    setAdding(true)
    try {
      onChange(await api.post<SourcesState>('/api/sources/librespeed/servers', { name: name.trim() || url.trim(), url: url.trim() }))
      setName('')
      setUrl('')
      notify(t('sources.librespeed.added'))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setAdding(false)
    }
  }

  async function remove(id: string) {
    try {
      onChange(await api.delete<SourcesState>(`/api/sources/librespeed/servers/${id}`))
    } catch (caught) {
      notify(errorMessage(caught))
    }
  }

  return (
    <div className="flex flex-col gap-2 border-t border-ink-700 pt-3">
      <p className="font-medium text-mist-200">{t('sources.librespeed.own')}</p>
      {state.librespeed.servers.length === 0 && <p className="text-xs">{t('sources.librespeed.ownNone')}</p>}
      {state.librespeed.servers.map((server) => (
        <div key={server.id} className="flex items-center justify-between gap-3">
          <span className="min-w-0 truncate text-mist-300">
            {server.name} <span className="text-mist-600">· {server.url}</span>
          </span>
          <Button variant="link" size="sm" onClick={() => void remove(server.id)}>
            {t('common.remove')}
          </Button>
        </div>
      ))}
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto] sm:items-end">
        <Field label={t('sources.librespeed.serverName')} value={name} placeholder="Homelab" onChange={(event) => setName(event.target.value)} />
        <Field
          label={t('sources.librespeed.serverUrl')}
          value={url}
          placeholder="http://speed.example.com"
          error={error}
          onChange={(event) => {
            setUrl(event.target.value)
            setError(null)
          }}
        />
        <Button variant="ghost" loading={adding} onClick={() => void add()} className={error ? 'sm:mb-6' : ''}>
          {t('common.add')}
        </Button>
      </div>
    </div>
  )
}

/** Die eigenen iperf3-Ziele. Ein Verzeichnis gibt es nicht, hier steht alles, was es gibt. */
function Targets({ state, onChange }: { state: SourcesState; onChange: (next: SourcesState) => void }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const [name, setName] = useState('')
  const [host, setHost] = useState('')
  const [port, setPort] = useState(String(state.iperf3.port))
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  async function add() {
    if (!host.trim()) {
      setError(t('sources.iperf3.hostRequired'))
      return
    }
    setAdding(true)
    try {
      onChange(
        await api.post<SourcesState>('/api/sources/iperf3/servers', {
          name: name.trim() || host.trim(),
          host: host.trim(),
          port: Number(port) || state.iperf3.port,
        }),
      )
      setName('')
      setHost('')
      setPort(String(state.iperf3.port))
      notify(t('sources.iperf3.added'))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setAdding(false)
    }
  }

  async function remove(id: string) {
    try {
      onChange(await api.delete<SourcesState>(`/api/sources/iperf3/servers/${id}`))
    } catch (caught) {
      notify(errorMessage(caught))
    }
  }

  return (
    <div className="flex flex-col gap-2 border-t border-ink-700 pt-3">
      <p className="font-medium text-mist-200">{t('sources.iperf3.own')}</p>
      {state.iperf3.servers.length === 0 && <p className="text-xs">{t('sources.iperf3.ownNone')}</p>}
      {state.iperf3.servers.map((server) => (
        <div key={server.id} className="flex items-center justify-between gap-3">
          <span className="min-w-0 truncate text-mist-300">
            {server.name}{' '}
            <span className="text-mist-600">
              · {server.host}:{server.port}
            </span>
          </span>
          <Button variant="link" size="sm" onClick={() => void remove(server.id)}>
            {t('common.remove')}
          </Button>
        </div>
      ))}
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_5.5rem_auto] sm:items-end">
        <Field label={t('sources.iperf3.serverName')} value={name} placeholder="VPS" onChange={(event) => setName(event.target.value)} />
        <Field
          label={t('sources.iperf3.serverHost')}
          value={host}
          placeholder="vps.example.com"
          error={error}
          onChange={(event) => {
            setHost(event.target.value)
            setError(null)
          }}
        />
        <Field
          label={t('sources.iperf3.serverPort')}
          value={port}
          inputMode="numeric"
          onChange={(event) => setPort(event.target.value.replace(/[^0-9]/g, ''))}
        />
        <Button variant="ghost" loading={adding} onClick={() => void add()} className={error ? 'sm:mb-6' : ''}>
          {t('common.add')}
        </Button>
      </div>
      {adding && <p className="text-xs">{t('sources.iperf3.checking')}</p>}
      {/* Ein stehender Hinweis, kein Fehler: tone="bad" waere rot und wuerde als Alarm vorgelesen. */}
      <Banner>{t('sources.iperf3.warning')}</Banner>
    </div>
  )
}

function Favorites({ source, favorites, onChange }: { source: Source; favorites: string[]; onChange: (favorites: string[]) => void }) {
  const { t } = useTranslation()
  const servers = useLoad(() => api.get<ServerOption[]>(`/api/sources/${source}/servers`), [source])
  const list = servers.data ?? []
  return (
    <details className="border-t border-ink-700 pt-3">
      <summary className="cursor-pointer font-medium text-mist-200">
        {t('sources.favorites')} {favorites.length > 0 && <span className="text-mist-500">({favorites.length})</span>}
      </summary>
      <p className="mt-1 text-xs">{t('sources.favoritesHint')}</p>
      {servers.loading ? (
        <PageLoading />
      ) : servers.error ? (
        <Banner tone="bad">{servers.error}</Banner>
      ) : (
        <div className="mt-2 flex max-h-64 flex-col gap-1 overflow-y-auto pr-1">
          {list.map((server) => {
            const checked = favorites.includes(server.id)
            return (
              <label key={server.id} className="flex items-center gap-2.5 rounded-lg px-2 py-1 hover:bg-ink-800">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-accent-500"
                  checked={checked}
                  onChange={() => onChange(checked ? favorites.filter((id) => id !== server.id) : [...favorites, server.id])}
                />
                <span className="text-mist-300">
                  {server.name}
                  {server.location && !server.name.includes(server.location) && <span className="text-mist-600"> · {server.location}</span>}
                </span>
              </label>
            )
          })}
        </div>
      )}
    </details>
  )
}

function ActivateOokla({ onClose, onDone }: { onClose: () => void; onDone: (state: SourcesState) => void }) {
  const { t } = useTranslation()
  const [accepted, setAccepted] = useState(false)
  const [missing, setMissing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function activate() {
    if (!accepted) {
      setMissing(true)
      return
    }
    setBusy(true)
    setError(null)
    try {
      onDone(await api.post<SourcesState>('/api/sources/ookla/activate', { accept_license: true }))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open
      title={t('sources.ookla.activateTitle')}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button loading={busy} onClick={() => void activate()}>
            {t('sources.ookla.download')}
          </Button>
        </>
      }
    >
      <p className="text-sm text-mist-300">{t('sources.ookla.activateText')}</p>
      <Banner tone="bad">
        <p className="font-semibold">{t('sources.ookla.warningTitle')}</p>
        <p className="mt-1">{t('sources.ookla.warningText')}</p>
      </Banner>
      <Links links={OOKLA_LINKS.map((link) => ({ label: t(`sources.ookla.${link.key}`), href: link.href }))} />
      <p className="text-xs text-mist-500">{t('sources.ookla.dataNote')}</p>
      <label className="flex items-start gap-2.5 text-sm text-mist-200">
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 accent-accent-500"
          checked={accepted}
          onChange={(event) => {
            setAccepted(event.target.checked)
            setMissing(false)
          }}
        />
        {t('sources.ookla.accept')}
      </label>
      {missing && <p className="text-xs text-bad-500">{t('sources.ookla.acceptFirst')}</p>}
      {busy && <p className="text-sm text-mist-500">{t('sources.ookla.downloading')}</p>}
      {error && <Banner tone="bad">{error}</Banner>}
    </Dialog>
  )
}
