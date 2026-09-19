/**
 * Die Skala des Tachos. Nicht linear (0, 10, 50, 100, 250 ...), wie bei Ookla:
 * Sonst zeigte eine 50er-Leitung kaum Ausschlag auf einer 1000er-Skala.
 * Ueber 1 Gbit/s waechst die Skala mit dem Tarif oder dem Messwert.
 */

export function scaleStops(max: number): number[] {
  if (max <= 1000) return [0, 10, 50, 100, 250, 500, 750, 1000]
  const top = niceCeil(max)
  return [0, top / 100, top / 20, top / 10, top / 4, top / 2, (top * 3) / 4, top].map((value) => Math.round(value))
}

function niceCeil(value: number): number {
  for (const step of [1000, 1500, 2000, 2500, 5000, 10000, 25000, 50000, 100000]) {
    if (value <= step) return step
  }
  return value
}

export function position(value: number, stops: number[]): number {
  const clamped = Math.max(0, Math.min(stops[stops.length - 1], value))
  for (let index = 1; index < stops.length; index++) {
    if (clamped <= stops[index]) {
      const part = (clamped - stops[index - 1]) / (stops[index] - stops[index - 1])
      return (index - 1 + part) / (stops.length - 1)
    }
  }
  return 1
}
