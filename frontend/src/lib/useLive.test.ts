import type { LiveEvent } from '../api/types'
import { reduce, type LiveState } from './useLive'

const idle: LiveState = reduce({} as LiveState, { type: 'snapshot', running: false })

function run(events: LiveEvent[]): LiveState {
  return events.reduce(reduce, idle)
}

describe('live state', () => {
  it('follows a test from start to finish', () => {
    const state = run([
      { type: 'snapshot', running: true, result_id: 7, source: 'cloudflare', phase: 'starting' },
      { type: 'server', name: 'Cloudflare', location: 'FRA · DE' },
      { type: 'phase', phase: 'ping' },
      { type: 'ping', ms: 11.5 },
      { type: 'phase', phase: 'download' },
      { type: 'value', phase: 'download', mbps: 400 },
      { type: 'value', phase: 'download', mbps: 900 },
      { type: 'phase', phase: 'upload' },
      { type: 'value', phase: 'upload', mbps: 45 },
    ])
    expect(state.running).toBe(true)
    expect(state.resultId).toBe(7)
    expect(state.location).toBe('FRA · DE')
    expect(state.ping).toBe(11.5)
    expect(state.download).toBe(900)
    expect(state.upload).toBe(45)
    expect(state.current).toBe(45)
    expect(state.samples.map((sample) => sample.phase)).toEqual(['download', 'download', 'upload'])

    const done = reduce(state, { type: 'done', result: null })
    expect(done.running).toBe(false)
    expect(done.phase).toBe('done')
    expect(done.download).toBe(900)
  })

  it('resets the needle on a new phase', () => {
    const state = run([
      { type: 'snapshot', running: true, phase: 'download' },
      { type: 'value', phase: 'download', mbps: 900 },
      { type: 'phase', phase: 'upload' },
    ])
    expect(state.current).toBe(0)
  })

  it('takes over a test that is already running', () => {
    const state = run([{ type: 'snapshot', running: true, phase: 'upload', download_mbps: 870, samples: [{ phase: 'download', mbps: 870 }] }])
    expect(state.phase).toBe('upload')
    expect(state.download).toBe(870)
    expect(state.samples).toHaveLength(1)
  })
})
