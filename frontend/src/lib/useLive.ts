/**
 * Die laufende Messung, live vom Server (server-sent events).
 *
 * Der Strom beginnt immer mit einem Schnappschuss. So sieht auch, wer mitten
 * in einer geplanten Messung die Seite oeffnet, den Stand, und nicht erst den
 * naechsten Wert.
 */

import { useEffect, useRef, useState } from 'react'

import type { LiveEvent, LiveSnapshot, Phase, Result } from '../api/types'

export type LiveState = {
  running: boolean
  resultId: number | null
  source: string
  phase: Phase | 'done' | 'idle'
  server: string
  location: string
  ping: number | null
  download: number | null
  upload: number | null
  current: number
  samples: { phase: string; mbps: number }[]
}

const IDLE: LiveState = {
  running: false,
  resultId: null,
  source: '',
  phase: 'idle',
  server: '',
  location: '',
  ping: null,
  download: null,
  upload: null,
  current: 0,
  samples: [],
}

function fromSnapshot(snapshot: LiveSnapshot): LiveState {
  if (!snapshot.running) return IDLE
  return {
    running: true,
    resultId: snapshot.result_id ?? null,
    source: snapshot.source ?? '',
    phase: snapshot.phase ?? 'starting',
    server: snapshot.server ?? '',
    location: snapshot.location ?? '',
    ping: snapshot.ping_ms ?? null,
    download: snapshot.download_mbps ?? null,
    upload: snapshot.upload_mbps ?? null,
    current: snapshot.current_mbps ?? 0,
    samples: snapshot.samples ?? [],
  }
}

export function reduce(state: LiveState, event: LiveEvent): LiveState {
  switch (event.type) {
    case 'snapshot':
      return fromSnapshot(event)
    case 'phase':
      return { ...state, running: true, phase: event.phase, current: 0 }
    case 'server':
      return { ...state, server: event.name, location: event.location }
    case 'ping':
      return { ...state, ping: event.ms }
    case 'value': {
      const samples = [...state.samples, { phase: event.phase, mbps: event.mbps }].slice(-240)
      return {
        ...state,
        current: event.mbps,
        samples,
        download: event.phase === 'download' ? event.mbps : state.download,
        upload: event.phase === 'upload' ? event.mbps : state.upload,
      }
    }
    case 'done':
      return { ...state, running: false, phase: 'done' }
  }
}

export function useLive(onDone: (result: Result | null) => void) {
  const [state, setState] = useState<LiveState>(IDLE)
  const [connected, setConnected] = useState(true)
  const doneRef = useRef(onDone)
  doneRef.current = onDone

  useEffect(() => {
    const source = new EventSource('/api/tests/stream')
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)
    source.onmessage = (message) => {
      let event: LiveEvent
      try {
        event = JSON.parse(message.data) as LiveEvent
      } catch {
        return
      }
      setState((current) => reduce(current, event))
      if (event.type === 'done') doneRef.current(event.result)
    }
    return () => source.close()
  }, [])

  return { state, setState, connected }
}
