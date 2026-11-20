import { useCallback, useEffect, useRef, useState } from 'react'

/** Fetch data, expose reload + setData. Keeps previous data visible while reloading. */
export function useResource<T>(fetcher: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const seq = useRef(0)
  const fetchRef = useRef(fetcher)
  fetchRef.current = fetcher

  const reload = useCallback(async () => {
    const my = ++seq.current
    setLoading(true)
    try {
      const d = await fetchRef.current()
      if (my === seq.current) {
        setData(d)
        setError(null)
      }
    } catch (e) {
      if (my === seq.current) setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (my === seq.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    setData(null)
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, setData, error, loading, reload }
}

/** Returns a debounced version of fn (trailing). */
export function useDebounced(fn: () => void, ms: number) {
  const t = useRef<ReturnType<typeof setTimeout>>()
  const f = useRef(fn)
  f.current = fn
  useEffect(() => () => clearTimeout(t.current), [])
  return useCallback(() => {
    clearTimeout(t.current)
    t.current = setTimeout(() => f.current(), ms)
  }, [ms])
}
