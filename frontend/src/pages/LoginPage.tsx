import { useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { errorMessage } from '../api/client'
import { useAuth } from '../auth'
import { Logo } from '../components/Logo'
import { LanguageSwitcher, ThemeSwitcher } from '../components/Switchers'
import { Banner, Button, Card, Field } from '../components/ui'

export default function LoginPage() {
  const { t } = useTranslation()
  const { signIn } = useAuth()
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!password) {
      setError(t('auth.passwordRequired'))
      return
    }
    setBusy(true)
    try {
      await signIn(password)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="np-glow flex min-h-dvh flex-col items-center justify-center px-4 py-10">
      <div className="relative z-10 w-full max-w-sm">
        <div className="mb-6 flex items-center justify-between">
          <Logo withWordmark className="h-10 w-10" />
          <div className="flex gap-2">
            <ThemeSwitcher />
            <LanguageSwitcher />
          </div>
        </div>
        <Card>
          <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)} noValidate>
            <h1 className="text-xl font-bold">{t('auth.title')}</h1>
            <Field
              label={t('auth.password')}
              type="password"
              autoComplete="current-password"
              autoFocus
              value={password}
              onChange={(event) => {
                setPassword(event.target.value)
                setError(null)
              }}
            />
            {error && <Banner tone="bad">{error}</Banner>}
            <Button type="submit" loading={busy}>
              {t('auth.signIn')}
            </Button>
          </form>
        </Card>
      </div>
    </div>
  )
}
