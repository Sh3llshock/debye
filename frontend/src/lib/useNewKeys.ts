import { useRef } from 'react'

/**
 * Tracks which keys appeared after the first render, so new items can animate in.
 * Returns isNew(key): true for ~2.5 s after the key first showed up (not on initial load).
 */
export function useNewKeys(keys: string[] | null, windowMs = 2500) {
  const firstSeen = useRef<Map<string, number> | null>(null)
  if (keys) {
    const now = Date.now()
    if (!firstSeen.current) {
      firstSeen.current = new Map(keys.map((k) => [k, 0]))
    } else {
      for (const k of keys) if (!firstSeen.current.has(k)) firstSeen.current.set(k, now)
    }
  }
  return (key: string) => {
    const t = firstSeen.current?.get(key)
    return !!t && Date.now() - t < windowMs
  }
}
