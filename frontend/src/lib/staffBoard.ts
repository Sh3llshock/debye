// Staff inbox + cases table: the case list plus each case's detail (tenant name, messages, diagnosis).
// Demo scale (a dozen cases), so details are simply fetched in parallel and refreshed on every SSE event.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { CaseDetail, CaseSummary } from '../api/types'
import { useStream } from './stream'
import { useDebounced } from './useResource'

export interface Board {
  cases: CaseSummary[] | null
  details: Record<string, CaseDetail>
  error: string | null
  reload: () => void
}

export function useStaffBoard(): Board {
  const [cases, setCases] = useState<CaseSummary[] | null>(null)
  const [details, setDetails] = useState<Record<string, CaseDetail>>({})
  const [error, setError] = useState<string | null>(null)
  const seen = useRef<Record<string, string>>({}) // case_id → updated_at+status of the detail we hold
  const load = useCallback(async () => {
    try {
      const list = await api.staffCases()
      setCases(list)
      setError(null)
      const stale = list.filter((c) => seen.current[c.case_id] !== c.updated_at + c.status)
      const got = await Promise.all(stale.map((c) => api.staffCase(c.case_id).catch(() => null)))
      const next: Record<string, CaseDetail> = {}
      got.forEach((d) => {
        if (!d) return
        next[d.case_id] = d
        seen.current[d.case_id] = d.updated_at + d.status
      })
      if (Object.keys(next).length) setDetails((prev) => ({ ...prev, ...next }))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])
  useEffect(() => {
    load()
  }, [load])
  const refetch = useDebounced(() => {
    load()
  }, 300)
  useStream((m) => {
    if (m.type === 'demo.reset') seen.current = {}
    if (m.case_id) delete seen.current[m.case_id] // messages do not always bump updated_at
    refetch()
  })
  return { cases, details, error, reload: load }
}
