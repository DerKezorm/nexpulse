/**
 * Die Sprachen, und nur die, die gerade gebraucht wird. Die andere kommt erst
 * beim Umschalten nach. Deshalb gibt es keine Rueckfallsprache: Fehlt ein Text,
 * erscheint sein Schluessel. `complete.test.ts` sorgt dafuer, dass alle
 * Dateien dieselben Eintraege haben.
 */

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

export const SUPPORTED_LANGUAGES = ['de', 'en', 'zh-Hans', 'zh-Hant'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]

const STORAGE_KEY = 'nexpulse.language'

const TEXTS: Record<Language, () => Promise<{ default: Record<string, unknown> }>> = {
  de: () => import('./de.json'),
  en: () => import('./en.json'),
  'zh-Hans': () => import('./zh-Hans.json'),
  'zh-Hant': () => import('./zh-Hant.json'),
}

export function isLanguage(value: unknown): value is Language {
  return SUPPORTED_LANGUAGES.some((language) => language === value)
}

function initialLanguage(): Language {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (isLanguage(stored)) return stored
  } catch {
    // Privater Modus ohne localStorage.
  }
  const browserLanguage = navigator.language.toLowerCase()
  if (browserLanguage.startsWith('zh')) {
    return /(^|[-_])(hant|tw|hk|mo)([-_]|$)/.test(browserLanguage) ? 'zh-Hant' : 'zh-Hans'
  }
  return browserLanguage.startsWith('de') ? 'de' : 'en'
}

async function load(language: Language): Promise<void> {
  if (i18n.hasResourceBundle(language, 'translation')) return
  const { default: texts } = await TEXTS[language]()
  i18n.addResourceBundle(language, 'translation', texts)
}

export async function startI18n(language: Language = initialLanguage()): Promise<void> {
  const { default: texts } = await TEXTS[language]()
  await i18n.use(initReactI18next).init({
    resources: { [language]: { translation: texts } },
    lng: language,
    fallbackLng: false,
    interpolation: { escapeValue: false },
  })
  document.documentElement.lang = language
}

export async function changeLanguage(language: Language): Promise<void> {
  try {
    localStorage.setItem(STORAGE_KEY, language)
  } catch {
    // Dann gilt die Wahl nur bis zum Neuladen.
  }
  if (i18n.language === language) return
  await load(language)
  document.documentElement.lang = language
  await i18n.changeLanguage(language)
}

export default i18n
