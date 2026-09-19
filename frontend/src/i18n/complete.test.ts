import de from './de.json'
import en from './en.json'

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
 * der rohe Schluessel. Deshalb muessen beide Dateien exakt dieselben haben.
 */
describe('translations', () => {
  const german = flatten(de)
  const english = flatten(en)

  it('have the same keys in both languages', () => {
    expect([...german.keys()].filter((key) => !english.has(key))).toEqual([])
    expect([...english.keys()].filter((key) => !german.has(key))).toEqual([])
    // Bodenschwelle: Eine leere oder abgeschnittene Datei soll nicht still bestehen.
    expect(german.size).toBeGreaterThan(300)
  })

  it('have no empty texts', () => {
    const empty = [...german, ...english].filter(([, value]) => typeof value !== 'string' || value.trim() === '')
    expect(empty).toEqual([])
  })

  it('use no dashes as punctuation', () => {
    // Hausregel: keine Gedankenstriche in dem, was nexpulse zeigt.
    const dashed = [...german, ...english].filter(([, value]) => /\s[–—]\s|—/.test(String(value)))
    expect(dashed).toEqual([])
  })
})
