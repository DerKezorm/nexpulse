/**
 * Verlauf ueber die Zeit, als eigenes SVG ohne Bibliothek.
 *
 * Download und Upload stehen in zwei Streifen mit eigener Skala: Auf einer
 * gemeinsamen Achse waere ein 50er-Upload neben einem 1000er-Download eine
 * flache Linie am Boden.
 */

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { Result } from '../api/types'
import { dateTime, shortDate, time } from '../lib/format'

export type Metric = 'speed' | 'ping' | 'loss'

type Series = { key: keyof Result; label: string; color: string; unit: string }
type Panel = { series: Series[]; max: number; plan?: number | null; share: number }

const LEFT = 44
const RIGHT = 12
const TOP = 10
const BOTTOM = 26

function niceMax(value: number): number {
  if (value <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(value))
  for (const factor of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
    if (value <= factor * magnitude) return factor * magnitude
  }
  return 10 * magnitude
}

function values(results: Result[], key: keyof Result): number[] {
  return results.map((result) => result[key]).filter((value): value is number => typeof value === 'number')
}

export function HistoryChart({
  results,
  metric,
  planDown,
  planUp,
  shortRange,
}: {
  results: Result[]
  metric: Metric
  planDown: number | null
  planUp: number | null
  shortRange: boolean
}) {
  const { t } = useTranslation()
  const box = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [hover, setHover] = useState<number | null>(null)
  const height = 320

  useEffect(() => {
    const element = box.current
    if (!element) return
    const observer = new ResizeObserver(() => setWidth(element.clientWidth))
    observer.observe(element)
    setWidth(element.clientWidth)
    return () => observer.disconnect()
  }, [])

  const ok = results.filter((result) => result.status === 'ok')
  const down: Series = { key: 'download_mbps', label: t('metrics.download'), color: 'var(--color-accent-500)', unit: 'Mbit/s' }
  const up: Series = { key: 'upload_mbps', label: t('metrics.upload'), color: 'var(--color-up-400)', unit: 'Mbit/s' }
  const panels: Panel[] =
    metric === 'speed'
      ? [
          { series: [down], max: niceMax(Math.max(planDown ?? 0, ...values(ok, 'download_mbps')) * 1.05), plan: planDown, share: 0.58 },
          { series: [up], max: niceMax(Math.max(planUp ?? 0, ...values(ok, 'upload_mbps')) * 1.1), plan: planUp, share: 0.42 },
        ]
      : metric === 'ping'
        ? [
            {
              series: [
                { key: 'ping_ms', label: t('metrics.ping'), color: 'var(--color-accent-500)', unit: 'ms' },
                { key: 'jitter_ms', label: t('metrics.jitter'), color: 'var(--color-up-400)', unit: 'ms' },
                { key: 'loaded_down_ms', label: t('metrics.loadedDown'), color: 'var(--color-warn-500)', unit: 'ms' },
              ],
              max: niceMax(Math.max(10, ...values(ok, 'ping_ms'), ...values(ok, 'loaded_down_ms')) * 1.1),
              share: 1,
            },
          ]
        : [
            {
              series: [{ key: 'packet_loss', label: t('metrics.packetLoss'), color: 'var(--color-bad-500)', unit: '%' }],
              max: niceMax(Math.max(1, ...values(ok, 'packet_loss')) * 1.2),
              share: 1,
            },
          ]

  const innerWidth = Math.max(10, width - LEFT - RIGHT)
  const innerHeight = height - TOP - BOTTOM
  const gap = panels.length > 1 ? 22 : 0
  const available = innerHeight - gap * (panels.length - 1)
  let cursor = TOP
  const placed = panels.map((panel) => {
    const top = cursor
    const panelHeight = available * panel.share
    cursor += panelHeight + gap
    return { ...panel, top, panelHeight }
  })

  const first = ok.length ? new Date(ok[0].started_at).getTime() : 0
  const last = ok.length ? new Date(ok[ok.length - 1].started_at).getTime() : 1
  const span = Math.max(1, last - first)
  const x = (result: Result) => LEFT + ((new Date(result.started_at).getTime() - first) / span) * innerWidth

  const hovered = hover != null ? ok[hover] : null
  const ticks = width < 500 ? 4 : 6

  function onMove(event: React.MouseEvent<SVGRectElement>) {
    if (!ok.length) return
    const rect = event.currentTarget.getBoundingClientRect()
    const mouse = LEFT + ((event.clientX - rect.left) / rect.width) * innerWidth
    let best = 0
    let distance = Infinity
    ok.forEach((result, index) => {
      const d = Math.abs(x(result) - mouse)
      if (d < distance) {
        distance = d
        best = index
      }
    })
    setHover(best)
  }

  return (
    <div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-mist-500">
        {panels.flatMap((panel) => panel.series).map((series) => (
          <span key={String(series.key)} className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: series.color }} />
            {series.label}
          </span>
        ))}
      </div>
      <div ref={box} className="relative mt-3" style={{ height }}>
        {width > 0 && (
          <svg viewBox={`0 0 ${width} ${height}`} className="block h-full w-full overflow-visible" role="img" aria-label={t('history.chartLabel')}>
            {placed.map((panel, panelIndex) => {
              const y = (value: number) => panel.top + panel.panelHeight - (value / panel.max) * panel.panelHeight
              const steps = panel.panelHeight < 120 ? 2 : 4
              return (
                <g key={panelIndex}>
                  {Array.from({ length: steps + 1 }, (_, step) => {
                    const yy = panel.top + (panel.panelHeight * step) / steps
                    return (
                      <g key={step}>
                        <line x1={LEFT} x2={width - RIGHT} y1={yy} y2={yy} style={{ stroke: 'var(--color-ink-700)' }} />
                        <text x={LEFT - 8} y={yy + 4} textAnchor="end" fontSize={11} style={{ fill: 'var(--color-mist-600)' }}>
                          {Math.round(panel.max * (1 - step / steps))}
                        </text>
                      </g>
                    )
                  })}
                  {panel.plan ? (
                    <>
                      <line
                        x1={LEFT}
                        x2={width - RIGHT}
                        y1={y(panel.plan)}
                        y2={y(panel.plan)}
                        strokeDasharray="4 4"
                        opacity={0.6}
                        style={{ stroke: panel.series[0].color }}
                      />
                      <text x={LEFT + 6} y={panel.top + panel.panelHeight - 6} fontSize={11} style={{ fill: 'var(--color-mist-600)' }}>
                        {t('history.planLine', { name: panel.series[0].label, value: panel.plan })}
                      </text>
                    </>
                  ) : null}
                  {panel.series.map((series, seriesIndex) => {
                    const points = ok
                      .map((result) => ({ result, value: result[series.key] }))
                      .filter((point): point is { result: Result; value: number } => typeof point.value === 'number')
                    if (!points.length) return null
                    const line = points.map((point, index) => `${index ? 'L' : 'M'}${x(point.result).toFixed(1)} ${y(point.value).toFixed(1)}`).join('')
                    const base = panel.top + panel.panelHeight
                    return (
                      <g key={String(series.key)}>
                        {seriesIndex === 0 && points.length > 1 && (
                          <path d={`${line}L${x(points[points.length - 1].result)} ${base}L${x(points[0].result)} ${base}Z`} opacity={0.08} style={{ fill: series.color }} />
                        )}
                        <path d={line} fill="none" strokeWidth={2} strokeLinejoin="round" style={{ stroke: series.color }} />
                        {(shortRange || points.length === 1) &&
                          points.map((point) => <circle key={point.result.id} cx={x(point.result)} cy={y(point.value)} r={3} style={{ fill: series.color }} />)}
                      </g>
                    )
                  })}
                </g>
              )
            })}
            {ok.length > 0 &&
              Array.from({ length: ticks }, (_, index) => {
                const at = first + (span * index) / (ticks - 1)
                const iso = new Date(at).toISOString()
                const anchor = index === 0 ? 'start' : index === ticks - 1 ? 'end' : 'middle'
                return (
                  <text key={index} x={LEFT + (innerWidth * index) / (ticks - 1)} y={height - 6} textAnchor={anchor} fontSize={11} style={{ fill: 'var(--color-mist-600)' }}>
                    {shortRange ? time(iso) : shortDate(iso)}
                  </text>
                )
              })}
            {hovered && <line x1={x(hovered)} x2={x(hovered)} y1={TOP} y2={TOP + innerHeight} style={{ stroke: 'var(--color-ink-600)' }} />}
            <rect x={LEFT} y={TOP} width={innerWidth} height={innerHeight} fill="transparent" onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
          </svg>
        )}
        {hovered && (
          <div
            className="pointer-events-none absolute top-3 z-10 rounded-xl border border-ink-600 bg-ink-850 px-3 py-2 text-xs whitespace-nowrap shadow-xl"
            style={x(hovered) + 220 > width ? { right: width - x(hovered) + 12 } : { left: x(hovered) + 12 }}
          >
            <p className="font-semibold">
              {dateTime(hovered.started_at)} <span className="font-normal text-mist-500">· {t(`sources.${hovered.source}.name`)}</span>
            </p>
            {panels.flatMap((panel) => panel.series).map((series) => {
              const value = hovered[series.key]
              return (
                <p key={String(series.key)}>
                  <span style={{ color: series.color }}>●</span> {series.label}{' '}
                  {typeof value === 'number' ? (series.key === 'download_mbps' ? Math.round(value) : value.toFixed(1)) : '–'} {series.unit}
                </p>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
