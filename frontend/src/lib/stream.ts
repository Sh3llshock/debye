import { useEffect, useRef } from 'react'
import { USE_FIXTURES } from '../api/client'
import type { StreamMessage } from '../api/types'

type Listener = (m: StreamMessage) => void
const listeners = new Set<Listener>()
let started = false
let connected = false
const statusListeners = new Set<(c: boolean) => void>()

function dispatch(m: StreamMessage) {
  listeners.forEach((l) => l(m))
}
function setConnected(c: boolean) {
  connected = c
  statusListeners.forEach((l) => l(c))
}

/** Opens exactly one connection to /api/stream for the whole app (or the fixture bus). */
function start() {
  if (started) return
  started = true
  if (USE_FIXTURES) {
    import('../api/mock').then((m) => {
      m.mockSubscribe(dispatch)
      setConnected(true)
    })
    return
  }
  const open = () => {
    const es = new EventSource('/api/stream')
    es.onopen = () => setConnected(true)
    es.onmessage = (e) => {
      try {
        dispatch(JSON.parse(e.data) as StreamMessage)
      } catch {
        /* ignore keep-alives / malformed lines */
      }
    }
    es.onerror = () => {
      setConnected(false)
      // EventSource retries by itself while CONNECTING; reopen if it gave up.
      if (es.readyState === EventSource.CLOSED) setTimeout(open, 2000)
    }
  }
  open()
}

/** Subscribe to stream messages. The handler can change between renders. */
export function useStream(handler: Listener) {
  const ref = useRef(handler)
  ref.current = handler
  useEffect(() => {
    start()
    const l: Listener = (m) => ref.current(m)
    listeners.add(l)
    return () => {
      listeners.delete(l)
    }
  }, [])
}

export function onStreamStatus(fn: (c: boolean) => void): () => void {
  start()
  statusListeners.add(fn)
  fn(connected)
  return () => statusListeners.delete(fn)
}
