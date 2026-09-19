/** Zahlen und Zeiten fuer die Anzeige, in der Sprache der Oberflaeche. */

import i18n from '../i18n'

function locale(): string {
  return i18n.language === 'de' ? 'de-DE' : 'en-GB'
}

/** Mbit/s: ab 100 ohne Nachkomma, darunter eine Stelle. */
export function speed(value: number | null | undefined): string {
  if (value == null) return '–'
  const digits = value >= 100 ? 0 : 1
  return value.toLocaleString(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function ms(value: number | null | undefined, digits = 0): string {
  if (value == null) return '–'
  return value.toLocaleString(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function percent(value: number | null | undefined): string {
  if (value == null) return '–'
  return value.toLocaleString(locale(), { maximumFractionDigits: 1 })
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '–'
  return new Date(iso).toLocaleString(locale(), {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function time(iso: string): string {
  return new Date(iso).toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit' })
}

export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(locale(), { day: '2-digit', month: 'short' })
}

/** "vor 3 Minuten", "in 2 Stunden". */
export function relative(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return '–'
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  const format = new Intl.RelativeTimeFormat(locale(), { numeric: 'auto' })
  const abs = Math.abs(seconds)
  if (abs < 60) return format.format(seconds, 'second')
  if (abs < 3600) return format.format(Math.round(seconds / 60), 'minute')
  if (abs < 86400) return format.format(Math.round(seconds / 3600), 'hour')
  return format.format(Math.round(seconds / 86400), 'day')
}

export function bytes(value: number | null | undefined): string {
  if (value == null) return '–'
  const units = ['B', 'kB', 'MB', 'GB']
  let size = value
  let unit = 0
  while (size >= 1000 && unit < units.length - 1) {
    size /= 1000
    unit += 1
  }
  return `${size.toLocaleString(locale(), { maximumFractionDigits: 1 })} ${units[unit]}`
}
