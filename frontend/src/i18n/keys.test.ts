import de from './de.json'

const sources = import.meta.glob('../**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

function exists(path: string): boolean {
  let node: unknown = de
  for (const part of path.split('.')) {
    if (!node || typeof node !== 'object' || !(part in node)) return false
    node = (node as Record<string, unknown>)[part]
  }
  return typeof node === 'string'
}

/** Mit Mehrzahlformen: `history.ofTests` gibt es als `_one` und `_other`. */
function existsWithPlural(path: string): boolean {
  return exists(path) || (exists(`${path}_one`) && exists(`${path}_other`))
}

describe('translation keys used in the code', () => {
  it('all exist', () => {
    const used = new Set<string>()
    for (const [file, text] of Object.entries(sources)) {
      if (file.endsWith('.test.ts') || file.endsWith('.test.tsx')) continue
      for (const match of text.matchAll(/\bt\(\s*'([a-zA-Z0-9_.]+)'/g)) used.add(match[1])
    }
    // Bodenschwelle, damit ein kaputtes Muster nicht still nichts findet.
    expect(used.size).toBeGreaterThan(200)
    expect([...used].filter((key) => !existsWithPlural(key))).toEqual([])
  })

  it('cover the composed keys', () => {
    const composed = [
      ...['cloudflare', 'librespeed', 'ookla'].map((source) => `sources.${source}.name`),
      ...['manual', 'schedule', 'api'].map((trigger) => `trigger.${trigger}`),
      ...['starting', 'selecting', 'ping', 'download', 'upload', 'done', 'idle'].map((phase) => `live.phase.${phase}`),
      ...['24h', '7d', '30d', '90d'].map((range) => `history.ranges.${range}`),
      ...['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].map((day) => `days.${day}`),
      ...['read', 'run'].flatMap((scope) => [`access.scope.${scope}`, `access.scopeHint.${scope}`]),
      ...['ntfy', 'gotify', 'webhook'].flatMap((kind) => [`plan.url.${kind}`, `plan.urlPlaceholder.${kind}`, `plan.token.${kind}`]),
      ...['license', 'terms', 'privacy'].map((link) => `sources.ookla.${link}`),
      ...['cloudflare', 'librespeed', 'ookla'].map((provider) => `about.provider.${provider}`),
      ...['site', 'source', 'privacy', 'servers', 'license', 'terms'].map((link) => `about.links.${link}`),
    ]
    expect(composed.filter((key) => !exists(key))).toEqual([])
  })
})
