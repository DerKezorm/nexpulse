/**
 * Angemeldet oder nicht. Ohne Passwort ist jeder angemeldet, mit Passwort
 * entscheidet das Sitzungs-Cookie, das dieses Skript nicht lesen kann.
 * Deshalb fragt es beim Start `/api/config`.
 */

import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { api, setSignedOutHandler } from './api/client'
import type { PublicConfig } from './api/types'

type Auth = {
  config: PublicConfig | null
  failed: boolean
  refresh: () => Promise<void>
  signIn: (password: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<Auth | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<PublicConfig | null>(null)
  const [failed, setFailed] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setConfig(await api.get<PublicConfig>('/api/config'))
      setFailed(false)
    } catch {
      setFailed(true)
    }
  }, [])

  useEffect(() => {
    void refresh()
    setSignedOutHandler(() => setConfig((current) => (current ? { ...current, signed_in: false } : current)))
    return () => setSignedOutHandler(null)
  }, [refresh])

  const signIn = useCallback(
    async (password: string) => {
      await api.post('/api/auth/login', { password })
      await refresh()
    },
    [refresh],
  )

  const signOut = useCallback(async () => {
    await api.post('/api/auth/logout')
    await refresh()
  }, [refresh])

  return <AuthContext.Provider value={{ config, failed, refresh, signIn, signOut }}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): Auth {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth outside AuthProvider')
  return value
}
