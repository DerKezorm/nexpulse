/**
 * Der Tacho. Die Skala ist nicht linear (0, 10, 50, 100, 250 ...), wie bei Ookla:
 * Sonst zeigte eine 50er-Leitung kaum Ausschlag auf einer 1000er-Skala.
 * Ueber 1 Gbit/s waechst die Skala mit dem Tarif oder dem Messwert.
 */

import { position, scaleStops } from '../lib/gauge'

const A0 = 150
const SWEEP = 240

function point(angle: number, radius: number): [number, number] {
  const rad = (angle * Math.PI) / 180
  return [200 + radius * Math.cos(rad), 175 + radius * Math.sin(rad)]
}

function arc(radius: number, from: number, to: number): string {
  const [x1, y1] = point(from, radius)
  const [x2, y2] = point(to, radius)
  return `M${x1.toFixed(1)} ${y1.toFixed(1)}A${radius} ${radius} 0 ${to - from > 180 ? 1 : 0} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`
}

function label(value: number): string {
  return value >= 1000 && value % 1000 === 0 ? `${value / 1000}k` : String(value)
}

export function Gauge({ value, upload, max }: { value: number; upload: boolean; max: number }) {
  const stops = scaleStops(Math.max(max, value))
  const share = position(value, stops)
  const end = A0 + SWEEP * share
  const tone = upload ? 'up' : 'accent'
  const [hx, hy] = point(end, 150)
  return (
    <svg viewBox="0 0 400 300" className="block w-full" aria-hidden="true">
      <defs>
        <linearGradient id="np-gauge" gradientUnits="userSpaceOnUse" x1="50" y1="0" x2="350" y2="0">
          <stop offset="0" style={{ stopColor: upload ? 'var(--color-up-600)' : 'var(--color-accent-700)' }} />
          <stop offset=".55" style={{ stopColor: upload ? 'var(--color-up-400)' : 'var(--color-accent-500)' }} />
          <stop offset="1" style={{ stopColor: upload ? '#cffafe' : '#ecfccb' }} />
        </linearGradient>
      </defs>
      <path d={arc(150, A0, A0 + SWEEP)} fill="none" style={{ stroke: `var(--color-${tone === 'up' ? 'up-400' : 'accent-500'})` }} strokeOpacity={0.14} strokeWidth={22} strokeLinecap="round" />
      {share > 0.002 && <path d={arc(150, A0, end)} fill="none" stroke="url(#np-gauge)" strokeWidth={22} strokeLinecap="round" />}
      {stops.map((stop, index) => {
        const angle = A0 + (SWEEP * index) / (stops.length - 1)
        const [x1, y1] = point(angle, 128)
        const [x2, y2] = point(angle, 120)
        const [tx, ty] = point(angle, 104)
        return (
          <g key={index}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} strokeWidth={2} style={{ stroke: 'var(--color-mist-600)' }} />
            <text x={tx} y={ty + 4} textAnchor="middle" fontSize={12} style={{ fill: 'var(--color-mist-600)' }}>
              {label(stop)}
            </text>
          </g>
        )
      })}
      {share > 0.002 && (
        <circle cx={hx} cy={hy} r={9} strokeWidth={3} style={{ fill: upload ? '#cffafe' : '#ecfccb', stroke: upload ? 'var(--color-up-400)' : 'var(--color-accent-500)' }} />
      )}
    </svg>
  )
}

/** Die kleine Kurve unter dem Tacho: Download gruen, Upload blau. */
export function Sparkline({ samples }: { samples: { phase: string; mbps: number }[] }) {
  if (samples.length < 2) return <div className="h-12" />
  const width = 400
  const height = 46
  const max = Math.max(50, ...samples.map((sample) => sample.mbps))
  const points = samples.map((sample, index) => ({
    phase: sample.phase,
    x: (index / (samples.length - 1)) * width,
    y: height - 3 - (sample.mbps / max) * (height - 8),
  }))
  const line = (phase: string) =>
    points
      .filter((p) => p.phase === phase)
      .map((p, index) => `${index ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
      .join('')
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="block h-12 w-full" aria-hidden="true">
      <path d={line('download')} fill="none" strokeWidth={2} vectorEffect="non-scaling-stroke" style={{ stroke: 'var(--color-accent-500)' }} />
      <path d={line('upload')} fill="none" strokeWidth={2} vectorEffect="non-scaling-stroke" style={{ stroke: 'var(--color-up-400)' }} />
    </svg>
  )
}
