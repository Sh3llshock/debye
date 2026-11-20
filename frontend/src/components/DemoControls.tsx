import { useEffect, useState } from 'react'
import { api, USE_FIXTURES } from '../api/client'
import { useStream } from '../lib/stream'

/** Hidden demo panel (VITE_DEMO=1). Toggle with the small dot bottom-right or the "d" key. */
export function DemoControls() {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [next, setNext] = useState<string | null>(null)

  const refreshNext = () => {
    if (USE_FIXTURES) import('../api/mock').then((m) => setNext(m.mockNextLabel()))
  }
  useEffect(refreshNext, [open])
  useStream(refreshNext)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA') return
      if (e.key === 'd' && !e.metaKey && !e.ctrlKey) setOpen((o) => !o)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true)
    setMsg(null)
    try {
      await fn()
      setMsg(`✓ ${label}`)
    } catch (e) {
      setMsg(`✗ ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(false)
      refreshNext()
    }
  }

  if (!open)
    return <button aria-label="Demo controls" onClick={() => setOpen(true)} className="fixed bottom-3 right-3 z-50 h-4 w-4 rounded-full bg-line opacity-40 hover:opacity-100" />

  return (
    <div className="fixed bottom-3 right-3 z-50 w-80 rounded-card border border-line bg-surface p-4 shadow-pop">
      <div className="mb-3 flex items-center justify-between">
        <span className="label">Demo controls</span>
        <button className="text-muted" onClick={() => setOpen(false)}>✕</button>
      </div>
      <div className="flex flex-col gap-2">
        {USE_FIXTURES && (
          <button className="btn-primary" disabled={busy || !next} onClick={() => run(next ?? '', () => import('../api/mock').then((m) => m.mockAdvance()))}>
            ▶ {next ?? 'Waiting for partner page'}
          </button>
        )}
        <button className="btn-secondary" disabled={busy} onClick={() => run('Skipped to tomorrow', api.demoSkip)}>Skip to tomorrow</button>
        <button className="btn-ghost" disabled={busy} onClick={() => confirm('Reset all demo data?') && run('Reset', async () => { await api.demoReset(); location.reload() })}>Reset</button>
      </div>
      {msg && <div className="mt-3 text-sm text-muted">{msg}</div>}
    </div>
  )
}
