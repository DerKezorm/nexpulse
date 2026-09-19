/**
 * Die Symbole an einer Stelle, wie in Nexview und nexcrate: 24x24, Strich statt
 * Flaeche, `currentColor`.
 */

type Path = { d: string; fill?: boolean }

const SYMBOLS = {
  live: [{ d: 'M4 17a8 8 0 1 1 16 0' }, { d: 'M12 17l4-5' }],
  history: [{ d: 'M3.5 20h17' }, { d: 'M5 16l4-5 4 3 6-8' }],
  schedule: [{ d: 'M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17Z' }, { d: 'M12 7.5V12l3 2' }],
  // Schieberegler wie in nexcrate. Das Zahnrad davor sah aus wie eine Sonne und verwechselte sich mit dem Hell-Umschalter.
  settings: [{ d: 'M4 7h9M17 7h3M4 17h3M11 17h9' }, { d: 'M15 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM9 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z' }],
  globe: [
    { d: 'M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17Z' },
    { d: 'M3.5 12h17' },
    { d: 'M12 3.5c2.2 2.3 3.4 5.3 3.4 8.5s-1.2 6.2-3.4 8.5c-2.2-2.3-3.4-5.3-3.4-8.5S9.8 5.8 12 3.5Z' },
  ],
  bell: [{ d: 'M6 16.5V11a6 6 0 1 1 12 0v5.5l1.5 2h-15l1.5-2Z' }, { d: 'M10 20.5a2 2 0 0 0 4 0' }],
  key: [{ d: 'M8 15a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z' }, { d: 'M12 11h8.5M17.5 11v3M20.5 11v2' }],
  plan: [{ d: 'M4 18a8 8 0 1 1 16 0' }, { d: 'M12 18l4.2-4.6' }],
  data: [
    { d: 'M5 6c0-1.4 3.1-2.5 7-2.5s7 1.1 7 2.5-3.1 2.5-7 2.5S5 7.4 5 6Z' },
    { d: 'M5 6v12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5' },
  ],
  down: [{ d: 'M12 4v16M5.5 13.5 12 20l6.5-6.5' }],
  up: [{ d: 'M12 20V4M5.5 10.5 12 4l6.5 6.5' }],
  close: [{ d: 'M6 6l12 12M18 6 6 18' }],
  check: [{ d: 'M5 12.5l4.5 4.5L19 7.5' }],
  info: [{ d: 'M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17Z' }, { d: 'M12 11v5.5M12 7.8v.2' }],
  warn: [{ d: 'M12 4 2.8 19.5h18.4L12 4Z' }, { d: 'M12 10v4.5M12 17v.2' }],
  plus: [{ d: 'M12 5v14M5 12h14' }],
  trash: [{ d: 'M5 7h14' }, { d: 'M9.5 7V5h5v2' }, { d: 'M6.5 7l.8 12.1a1 1 0 0 0 1 .9h7.4a1 1 0 0 0 1-.9L17.5 7' }],
  external: [{ d: 'M14 4.5h5.5V10M19.5 4.5 11 13M17 14v5.5H4.5V7H10' }],
  copy: [{ d: 'M8.5 8.5h11v11h-11z' }, { d: 'M15.5 8.5V4.5h-11v11h4' }],
  logout: [{ d: 'M14 4.5h5.5v15H14' }, { d: 'M10 8l-4 4 4 4M6 12h9' }],
  play: [{ d: 'M8 5.5v13l10.5-6.5L8 5.5Z', fill: true }],
  refresh: [{ d: 'M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4' }],
} satisfies Record<string, Path[]>

export type SymbolName = keyof typeof SYMBOLS

export function Symbol({ name, className = 'h-4 w-4' }: { name: SymbolName; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" focusable="false">
      {(SYMBOLS[name] as Path[]).map((path, index) => (
        <path
          key={index}
          d={path.d}
          fill={path.fill ? 'currentColor' : 'none'}
          stroke={path.fill ? 'none' : 'currentColor'}
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
    </svg>
  )
}
