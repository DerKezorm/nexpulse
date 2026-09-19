/**
 * Zugriff auf das nexpulse-Backend.
 *
 * Es gibt nur ein Sitzungs-Cookie (HttpOnly), und das auch nur, wenn ein
 * Passwort gesetzt ist. Jede veraendernde Anfrage traegt `X-Requested-By`,
 * sonst lehnt der Server ab (siehe backend/app/deps.py).
 */

import i18n from '../i18n'

let onSignedOut: (() => void) | null = null

export class ApiError extends Error {
  status: number
  code: string | null
  data: Record<string, unknown> | null

  constructor(status: number, message: string, code: string | null = null, data: Record<string, unknown> | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.data = data
  }
}

export function setSignedOutHandler(handler: (() => void) | null): void {
  onSignedOut = handler
}

/**
 * Fehlermeldungen des Servers in der eingestellten Sprache. Das Backend benennt
 * nur (`code`), der Satz entsteht hier aus `errors.byCode`.
 */
export function translateError(detail: Record<string, unknown>, status: number): string {
  const code = typeof detail.code === 'string' ? detail.code : null
  const fallback = String(detail.message ?? `HTTP ${status}`)
  if (!code) return fallback
  if (code === 'internal_error') return i18n.t('errors.internal', { id: String(detail.request_id ?? '?') })
  if (code === 'too_many_attempts') {
    const seconds = Math.max(1, Math.ceil(Number(detail.retry_after ?? 1)))
    return seconds >= 60
      ? i18n.t('errors.tooManyAttemptsMinutes', { count: Math.ceil(seconds / 60) })
      : i18n.t('errors.tooManyAttemptsSeconds', { count: seconds })
  }
  const key = `errors.byCode.${code}`
  return i18n.exists(key) ? i18n.t(key, { ...detail }) : fallback
}

/** Die Kennung eines gespeicherten Fehlers (etwa einer gescheiterten Messung) als Satz. */
export function errorText(code: string | null | undefined): string {
  if (!code) return ''
  const key = `errors.byCode.${code}`
  return i18n.exists(key) ? i18n.t(key) : code
}

async function parseError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      const record = detail as Record<string, unknown>
      return new ApiError(
        response.status,
        translateError(record, response.status),
        typeof record.code === 'string' ? record.code : null,
        record,
      )
    }
    if (typeof detail === 'string') return new ApiError(response.status, detail)
  } catch {
    /* Antwort war kein JSON */
  }
  return new ApiError(response.status, i18n.t('errors.http', { status: response.status }))
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  if (method !== 'GET') headers['X-Requested-By'] = 'nexpulse'
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, i18n.t('errors.network'), 'network')
  }
  if (response.status === 401 && !path.startsWith('/api/auth/')) onSignedOut?.()
  if (!response.ok) throw await parseError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string) => send<T>('GET', path),
  post: <T>(path: string, body?: unknown) => send<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => send<T>('PUT', path, body),
  delete: <T>(path: string) => send<T>('DELETE', path),
}

export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : i18n.t('errors.generic')
}
