import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../../api/client'
import type { ApiKey } from '../../api/types'
import { useAuth } from '../../auth'
import { Dialog } from '../../components/Dialog'
import { useNotice } from '../../components/Notice'
import { Symbol } from '../../components/Symbol'
import { Badge, Button, Field, Section, Switch } from '../../components/ui'
import { dateTime, relative } from '../../lib/format'
import { useLoad } from '../../lib/useLoad'

const ENDPOINTS = [
  ['GET', '/api/v1/status', 'read'],
  ['GET', '/api/v1/latest', 'read'],
  ['GET', '/api/v1/results?from=…&to=…', 'read'],
  ['GET', '/api/v1/stats?range=7d', 'read'],
  ['POST', '/api/v1/tests', 'run'],
  ['GET', '/api/v1/tests/{id}', 'read'],
] as const

export default function AccessTab() {
  const { t } = useTranslation()
  const notify = useNotice()
  const { config, refresh } = useAuth()
  const keys = useLoad(() => api.get<ApiKey[]>('/api/keys'))
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [savingPassword, setSavingPassword] = useState(false)
  const [creating, setCreating] = useState(false)
  const [revoking, setRevoking] = useState<ApiKey | null>(null)

  const hasPassword = Boolean(config?.password_required)

  async function savePassword(value: string) {
    if (value && value.length < 10) {
      setPasswordError(t('access.passwordShort'))
      return
    }
    setSavingPassword(true)
    try {
      await api.put('/api/auth/password', { password: value })
      await refresh()
      setPassword('')
      setPasswordOpen(false)
      notify(value ? t('access.passwordSet') : t('access.passwordRemoved'))
    } catch (error) {
      setPasswordError(errorMessage(error))
    } finally {
      setSavingPassword(false)
    }
  }

  async function revoke() {
    if (!revoking) return
    try {
      await api.delete(`/api/keys/${revoking.id}`)
      setRevoking(null)
      notify(t('access.keyRevoked'))
      void keys.reload()
    } catch (error) {
      notify(errorMessage(error))
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <Section
        title={t('access.password')}
        intro={t('access.passwordIntro')}
        aside={
          <Switch
            label={t('access.passwordSwitch')}
            hideLabel
            checked={hasPassword || passwordOpen}
            onChange={(on) => {
              setPasswordError(null)
              if (on) setPasswordOpen(true)
              else if (hasPassword) void savePassword('')
              else setPasswordOpen(false)
            }}
          />
        }
      >
        {hasPassword && !passwordOpen && (
          <div className="flex flex-wrap items-center gap-3">
            <Badge tone="accent">{t('access.passwordActive')}</Badge>
            <Button variant="ghost" size="sm" onClick={() => setPasswordOpen(true)}>
              {t('access.changePassword')}
            </Button>
          </div>
        )}
        {passwordOpen && (
          <div className="flex max-w-sm flex-col gap-3">
            <Field
              label={hasPassword ? t('access.newPassword') : t('access.password')}
              type="password"
              autoComplete="new-password"
              value={password}
              placeholder={t('access.passwordPlaceholder')}
              error={passwordError}
              onChange={(event) => {
                setPassword(event.target.value)
                setPasswordError(null)
              }}
            />
            <div className="flex gap-2">
              <Button size="sm" loading={savingPassword} onClick={() => void savePassword(password)}>
                {t('access.savePassword')}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setPasswordOpen(false)}>
                {t('common.cancel')}
              </Button>
            </div>
          </div>
        )}
        <p className="text-xs text-mist-600">
          {t('access.forgotten')} <code className="font-mono">docker exec nexpulse python -m app.cli remove-password</code>
        </p>
      </Section>

      <Section
        title={t('access.keys')}
        intro={t('access.keysIntro')}
        aside={
          <Button variant="ghost" size="sm" onClick={() => setCreating(true)}>
            <Symbol name="key" />
            {t('access.createKey')}
          </Button>
        }
      >
        {keys.data && keys.data.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-700 text-left text-xs text-mist-600">
                  <th className="px-3 pb-2 font-medium">{t('access.keyName')}</th>
                  <th className="px-3 pb-2 font-medium">{t('access.keyScope')}</th>
                  <th className="hidden px-3 pb-2 font-medium sm:table-cell">{t('access.keyCreated')}</th>
                  <th className="px-3 pb-2 font-medium">{t('access.keyUsed')}</th>
                  <th className="px-3 pb-2" />
                </tr>
              </thead>
              <tbody>
                {keys.data.map((key) => (
                  <tr key={key.id} className="border-b border-ink-700 last:border-0">
                    <td className="px-3 py-2.5">
                      {key.name} <span className="font-mono text-xs text-mist-600">{key.prefix}…</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge tone={key.scope === 'run' ? 'accent' : 'neutral'}>{t(`access.scope.${key.scope}`)}</Badge>
                    </td>
                    <td className="hidden px-3 py-2.5 text-mist-500 sm:table-cell">{dateTime(key.created_at)}</td>
                    <td className="px-3 py-2.5 text-mist-500">{key.last_used_at ? relative(key.last_used_at) : t('access.never')}</td>
                    <td className="px-3 py-2.5 text-right">
                      <Button variant="link" size="sm" className="hover:text-bad-500" onClick={() => setRevoking(key)}>
                        {t('access.revoke')}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-mist-500">{t('access.noKeys')}</p>
        )}
        <details>
          <summary className="cursor-pointer text-sm text-mist-500">{t('access.endpoints')}</summary>
          <div className="mt-2 flex flex-col gap-1 font-mono text-xs break-all text-mist-300">
            {ENDPOINTS.map(([method, path, scope]) => (
              <p key={path}>
                <span className="inline-block w-12 text-mist-500">{method}</span>
                {path} <span className="text-mist-600">· {t(`access.scope.${scope}`)}</span>
              </p>
            ))}
            <p className="mt-1 font-sans text-mist-500">
              {t('access.headerHint')}{' '}
              <a href="/api/docs" target="_blank" rel="noreferrer" className="text-accent-400 hover:underline">
                /api/docs
              </a>
            </p>
          </div>
        </details>
      </Section>

      {creating && (
        <CreateKey
          onClose={() => setCreating(false)}
          onCreated={() => {
            void keys.reload()
          }}
        />
      )}
      <Dialog
        open={revoking != null}
        title={t('access.revokeTitle')}
        onClose={() => setRevoking(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRevoking(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" onClick={() => void revoke()}>
              {t('access.revoke')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-mist-300">{revoking && t('access.revokeText', { name: revoking.name })}</p>
      </Dialog>
    </div>
  )
}

function CreateKey({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const [name, setName] = useState('')
  const [scope, setScope] = useState<'read' | 'run'>('read')
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function create() {
    if (!name.trim()) {
      setError(t('access.keyNameRequired'))
      return
    }
    setBusy(true)
    try {
      const answer = await api.post<ApiKey & { key: string }>('/api/keys', { name: name.trim(), scope })
      setCreated(answer.key)
      onCreated()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function copy() {
    if (!created) return
    try {
      await navigator.clipboard.writeText(created)
      notify(t('access.copied'))
    } catch {
      notify(t('access.copyFailed'))
    }
  }

  if (created) {
    return (
      <Dialog
        open
        title={t('access.keyCreated')}
        onClose={onClose}
        footer={
          <>
            <Button variant="ghost" onClick={() => void copy()}>
              <Symbol name="copy" />
              {t('access.copy')}
            </Button>
            <Button onClick={onClose}>{t('common.done')}</Button>
          </>
        }
      >
        <p className="text-sm text-mist-300">{t('access.keyOnce')}</p>
        <p className="rounded-xl border border-dashed border-accent-500 bg-ink-900 px-4 py-3 font-mono text-sm break-all select-all">{created}</p>
        <p className="text-sm text-mist-500">{t('access.keyNexdeck')}</p>
      </Dialog>
    )
  }

  return (
    <Dialog
      open
      title={t('access.createKey')}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button loading={busy} onClick={() => void create()}>
            {t('access.create')}
          </Button>
        </>
      }
    >
      <Field
        label={t('access.keyName')}
        value={name}
        placeholder="nexdeck"
        autoFocus
        error={error}
        onChange={(event) => {
          setName(event.target.value)
          setError(null)
        }}
      />
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium text-mist-300">{t('access.keyScope')}</legend>
        {(['read', 'run'] as const).map((value) => (
          <label key={value} className="flex items-start gap-2.5 text-sm">
            <input type="radio" name="scope" className="mt-0.5 accent-accent-500" checked={scope === value} onChange={() => setScope(value)} />
            <span>
              <span className="font-medium text-mist-200">{t(`access.scope.${value}`)}</span>
              <span className="block text-xs text-mist-500">{t(`access.scopeHint.${value}`)}</span>
            </span>
          </label>
        ))}
      </fieldset>
    </Dialog>
  )
}
