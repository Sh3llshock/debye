import { useEffect, useRef } from 'react'
import { USE_FIXTURES } from '../api/client'
import type { StreamMessage } from '../api/types'
import { onAuthChange, tokenForPage } from './auth'

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
  // The stream needs the page's portal token (?token=, EventSource cannot send headers); the server
  // only sends what this account may see. Reconnect when the login or the page's portal changes.
  let es: EventSource | null = null
  let current: string | null = null
  let retry: number | undefined
  const open = () => {
    window.clearTimeout(retry)
    const tok = tokenForPage()
    if (es && tok === current && es.readyState !== EventSource.CLOSED) return
    es?.close()
    es = null
    current = tok
    if (!tok) {
      setConnected(false)
      return
    }
    const src = new EventSource(`/api/stream?token=${encodeURIComponent(tok)}`)
    es = src
    src.onopen = () => setConnected(true)
    src.onmessage = (e) => {
      try {
        dispatch(JSON.parse(e.data) as StreamMessage)
      } catch {
        /* ignore keep-alives / malformed lines */
      }
    }
    src.onerror = () => {
      setConnected(false)
      // EventSource retries by itself while CONNECTING; reopen if it gave up.
      if (src.readyState === EventSource.CLOSED) retry = window.setTimeout(open, 2000)
    }
  }
  onAuthChange(open)
  window.addEventListener('popstate', open)
  // SPA navigation (pushState) between portals: check the token now and then
  window.setInterval(() => {
    if (tokenForPage() !== current) open()
  }, 1500)
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
