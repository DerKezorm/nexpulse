import de from './de.json'
import en from './en.json'
import zhHans from './zh-Hans.json'
import zhHant from './zh-Hant.json'

function flatten(tree: Record<string, unknown>, prefix = ''): Map<string, unknown> {
  const result = new Map<string, unknown>()
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      for (const [inner, innerValue] of flatten(value as Record<string, unknown>, path)) result.set(inner, innerValue)
    } else {
      result.set(path, value)
    }
  }
  return result
}

/**
 * Es gibt keine Rueckfallsprache. Fehlt ein Text in einer Sprache, stuende dort
 * der rohe Schluessel. Deshalb muessen alle Sprachdateien exakt dieselben haben.
 */
describe('translations', () => {
  const languages = [de, en, zhHans, zhHant].map((language) => flatten(language))
  const reference = languages[0]

  it('have the same keys in every language', () => {
    for (const language of languages.slice(1)) {
      expect([...reference.keys()].filter((key) => !language.has(key))).toEqual([])
      expect([...language.keys()].filter((key) => !reference.has(key))).toEqual([])
    }
    // Bodenschwelle: Eine leere oder abgeschnittene Datei soll nicht still bestehen.
    expect(reference.size).toBeGreaterThan(300)
  })

  it('have no empty texts', () => {
    const empty = languages.flatMap((language) => [...language]).filter(([, value]) => typeof value !== 'string' || value.trim() === '')
    expect(empty).toEqual([])
  })

  it('use no dashes as punctuation', () => {
    // Hausregel: keine Gedankenstriche in dem, was nexpulse zeigt.
    const dashed = languages.flatMap((language) => [...language]).filter(([, value]) => /\s[–—]\s|—/.test(String(value)))
    expect(dashed).toEqual([])
  })
})
