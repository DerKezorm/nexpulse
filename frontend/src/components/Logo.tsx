/**
 * nexpulse-Zeichen: ein Tacho mit Zeiger im Voltgruen. Hell auf weisser Kachel, dunkel auf dunkler; die Farben sind
 * `--np-logo-*` in styles/index.css (Quelle nexapps/icons-vergleich/neu.py, wie public/logo.svg).
 */
export function Logo({ className = 'h-8 w-8', withWordmark = false }: { className?: string; withWordmark?: boolean }) {
  // userSpaceOnUse, damit der Verlauf ueber das ganze Zeichen laeuft und nicht je Bogen neu anfaengt.
  const mark = (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="nexpulse-mark" gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
          <stop offset="0" style={{ stopColor: 'var(--np-logo-verlauf-1)' }} />
          <stop offset=".5" style={{ stopColor: 'var(--np-logo-verlauf-2)' }} />
          <stop offset="1" style={{ stopColor: 'var(--np-logo-verlauf-3)' }} />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" style={{ fill: 'var(--np-logo-grund)' }} />
      <rect
        x="2.75"
        y="2.75"
        width="58.5"
        height="58.5"
        rx="15.3"
        fill="none"
        strokeWidth="1.5"
        style={{ stroke: 'var(--np-logo-rand)', strokeOpacity: 'var(--np-logo-rand-deckung)' }}
      />
      <g transform="translate(0 -3)">
        <path
          d="M14.4 47.5A19 19 0 1 1 49.6 47.5"
          fill="none"
          stroke="url(#nexpulse-mark)"
          strokeOpacity=".3"
          strokeWidth="4.6"
          strokeLinecap="round"
        />
        <path d="M14.4 47.5A19 19 0 0 1 45.4 26.6" fill="none" stroke="url(#nexpulse-mark)" strokeWidth="4.6" strokeLinecap="round" />
        <path d="M32 40 42 28.5" strokeWidth="3.8" strokeLinecap="round" style={{ stroke: 'var(--np-logo-zeiger)' }} />
        <circle cx="32" cy="40" r="4.6" strokeWidth="2" style={{ fill: 'var(--np-logo-zeiger)', stroke: 'var(--np-logo-grund)' }} />
      </g>
    </svg>
  )
  if (!withWordmark) return mark
  return (
    <span className="flex items-center gap-2.5">
      {mark}
      <span className="hidden text-lg font-bold tracking-tight sm:inline">
        NEX<span className="text-accent-500">PULSE</span>
      </span>
    </span>
  )
}
