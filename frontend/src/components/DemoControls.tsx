import { useEffect, useState } from 'react'
import { api, USE_FIXTURES } from '../api/client'
import { useStream } from '../lib/stream'
import { getStageScale, setStageScale, STAGE_MAX, STAGE_MIN } from '../lib/stage'

/** Hidden demo panel (VITE_DEMO=1). Toggle with the small dot bottom-right or the "d" key. */
function TextSize() {
  const [scale, setScale] = useState(getStageScale)
  const step = (d: number) => setScale(setStageScale(scale + d))
  return (
    <div className="flex items-center gap-2">
      <span className="text-label text-muted">Text</span>
      <button className="btn-ghost min-h-0 px-3 py-1" disabled={scale <= STAGE_MIN} onClick={() => step(-0.05)} aria-label="Smaller text">
        A−
      </button>
      <button className="min-w-[3.5rem] text-label font-medium" onClick={() => setScale(setStageScale(1))} title="Reset to 100 %">
        {Math.round(scale * 100)}%
      </button>
      <button className="btn-ghost min-h-0 px-3 py-1" disabled={scale >= STAGE_MAX} onClick={() => step(0.05)} aria-label="Bigger text">
        A+
      </button>
    </div>
  )
}

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
    return <button aria-label="Demo controls" onClick={() => setOpen(true)} className="fixed bottom-3 right-3 z-50 h-4 w-4 rounded-full bg-beige-d opacity-50 hover:bg-wine hover:opacity-100" />

  return (
    <div className="fixed bottom-3 right-3 z-50 w-80 max-w-[calc(100vw-24px)] rounded-panel bg-surface p-4 shadow-pop ring-1 ring-line">
      <div className="mb-3 flex items-center justify-between">
        <span className="flex items-center gap-2 text-panel font-medium"><img src="/brand/debye-logo.png" alt="" className="h-5 w-5" />Demo controls</span>
        <button className="text-muted" onClick={() => setOpen(false)}>✕</button>
      </div>
      <div className="flex flex-col gap-2">
        {USE_FIXTURES && (
          <button className="btn-primary" disabled={busy || !next} onClick={() => run(next ?? '', () => import('../api/mock').then((m) => m.mockAdvance()))}>
            ▶ {next ?? 'Waiting for a click on a page'}
          </button>
        )}
        <button className="btn-secondary" disabled={busy} onClick={() => run('Skipped to tomorrow', api.demoSkip)}>Skip to tomorrow</button>
        <TextSize />
        <button className="btn-secondary" disabled={busy} onClick={() => run('Demo cases loaded', async () => { await api.demoScenarios(); location.reload() })}>Load demo cases</button>
        <button className="btn-ghost" disabled={busy} onClick={() => confirm('Delete all cases and start empty?') && run('Reset', async () => { await api.demoReset(); location.reload() })}>Reset (empty)</button>
      </div>
      {msg && <div className="mt-3 text-label text-muted">{msg}</div>}
    </div>
  )
}
