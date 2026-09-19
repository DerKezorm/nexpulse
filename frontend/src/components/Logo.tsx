/** nexpulse-Zeichen: ein zu zwei Dritteln gefuellter Tacho im Voltgruen, im Rahmen der nexapps-Zeichen. */
export function Logo({ className = 'h-8 w-8', withWordmark = false }: { className?: string; withWordmark?: boolean }) {
  // userSpaceOnUse, damit der Verlauf ueber das ganze Zeichen laeuft und nicht je Bogen neu anfaengt.
  const mark = (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="nexpulse-mark" gradientUnits="userSpaceOnUse" x1="8" y1="8" x2="56" y2="56">
          <stop offset="0" stopColor="#ecfccb" />
          <stop offset=".5" stopColor="#a3e635" />
          <stop offset="1" stopColor="#4d7c0f" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" fill="#0d110a" />
      <rect x="2" y="2" width="60" height="60" rx="16" fill="none" stroke="url(#nexpulse-mark)" strokeWidth="2.5" strokeOpacity=".55" />
      <path d="M16.4 47A18 18 0 1 1 47.6 47" fill="none" stroke="#a3e635" strokeOpacity=".2" strokeWidth="5" strokeLinecap="round" />
      <path d="M16.4 47A18 18 0 0 1 44.7 25.3" fill="none" stroke="url(#nexpulse-mark)" strokeWidth="5" strokeLinecap="round" />
      <circle cx="44.7" cy="25.3" r="4" fill="#ecfccb" />
      <circle cx="32" cy="40" r="2.6" fill="#a3e635" />
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
