import { useCallback, useEffect, useRef, useState } from 'react'

import { errorMessage } from '../api/client'

/**
 * Laedt etwas vom Server und haelt Ergebnis, Fehler und Ladezustand.
 * Aendert sich ein Wert in `deps`, wird neu geladen. `reload` holt von Hand
 * neu, `set` ersetzt den Stand ohne Anfrage (etwa mit der Antwort nach dem Speichern).
 */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const loadRef = useRef(load)
  loadRef.current = load
  const key = JSON.stringify(deps)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setData(await loadRef.current())
      setError(null)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload, key])

  return { data, error, loading, reload, set: setData }
}
