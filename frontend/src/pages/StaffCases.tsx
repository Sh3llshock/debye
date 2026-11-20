import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { CaseSummary } from '../api/types'
import { MiniLine } from '../components/case/CasePanels'
import { LiveDot, useCrumbs } from '../components/Layout'
import { ErrorBox, Loading, Mascot, PriorityChip } from '../components/ui'
import { errorText } from '../lib/errors'
import { fmtEur, fmtRelative } from '../lib/format'
import { lineState, STAFF_STATIONS } from '../lib/lifecycle'
import { useStream } from '../lib/stream'
import { useNewKeys } from '../lib/useNewKeys'
import { useDebounced, useResource } from '../lib/useResource'

type Filter = 'all' | 'open' | 'decision' | 'closed'
const FILTERS: { key: Filter; label: string; test: (c: CaseSummary) => boolean }[] = [
  { key: 'all', label: 'All', test: () => true },
  { key: 'open', label: 'Open', test: (c) => c.status !== 'closed' },
  { key: 'decision', label: 'Needs decision', test: (c) => c.status === 'awaiting_approval' },
  { key: 'closed', label: 'Closed', test: (c) => c.status === 'closed' },
]

/** The approval sits inside the table as an amber "needs decision" row. */
function DecisionRow({ c, onDone }: { c: CaseSummary; onDone: () => void }) {
  const { data: d } = useResource(() => api.staffCase(c.case_id), [c.case_id])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const amount = d?.approval?.amount_eur ?? d?.estimated_cost_eur
  return (
    <tr className="border-b border-line bg-warning-soft">
      <td colSpan={6} className="px-5 py-4">
        <div className="flex flex-wrap items-center gap-4">
          <div className="min-w-0 flex-1">
            <div className="font-semibold">
              {c.title} · {(c.address ?? '').split(',')[0]}, {c.unit_id.replace('unit_', '')} · {c.case_id}
            </div>
            <div className="text-body-sm text-secondary">
              {c.partner?.name ?? 'The partner'} estimates {fmtEur(amount)}. That is over your auto-approval limit, so the job waits for you.
            </div>
            {err && <div className="mt-1 text-negative">{err}</div>}
          </div>
          <Link to={`/staff/cases/${c.case_id}`} className="btn-secondary">
            Open case
          </Link>
          <button
            className="btn-primary"
            disabled={busy || amount == null}
            onClick={async () => {
              setBusy(true)
              setErr(null)
              try {
                await api.approve(c.case_id)
                onDone()
              } catch (e) {
                setErr(e instanceof Error ? e.message : String(e))
              } finally {
                setBusy(false)
              }
            }}
          >
            {busy ? 'Approving…' : `Approve ${fmtEur(amount)}`}
          </button>
        </div>
      </td>
    </tr>
  )
}

export default function StaffCases() {
  useCrumbs([{ label: 'Cases' }])
  const { data, error, reload } = useResource(() => api.staffCases(), [])
  const refetch = useDebounced(reload, 250)
  useStream(() => refetch())
  const [filter, setFilter] = useState<Filter>('all')
  const nav = useNavigate()
  const isNew = useNewKeys(data ? data.map((c) => c.case_id + c.status) : null)

  const shown = data?.filter(FILTERS.find((f) => f.key === filter)!.test) ?? []
  const decisions = shown.filter((c) => c.status === 'awaiting_approval')
  const rows = shown.filter((c) => c.status !== 'awaiting_approval')
  const open = data?.filter((c) => c.status !== 'closed').length ?? 0
  const need = data?.filter((c) => c.status === 'awaiting_approval').length ?? 0

  return (
    <div className="flex flex-col gap-work">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-page">Cases</h1>
          {data && (
            <p className="mt-1 text-body text-secondary">
              {data.length} case{data.length === 1 ? '' : 's'} · {open} open · {need} need{need === 1 ? 's' : ''} your decision
            </p>
          )}
        </div>
        <div className="inline-flex rounded border border-line bg-surface p-1" role="tablist">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              role="tab"
              aria-selected={filter === f.key}
              onClick={() => setFilter(f.key)}
              className={`rounded px-4 py-2 text-body transition-colors ${filter === f.key ? 'bg-ink font-semibold text-on-action' : 'text-ink hover:bg-sub'}`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {!data && !error && <Loading what="Loading cases" />}

      {data && data.length === 0 && (
        <section className="panel flex flex-col items-center gap-3 px-6 py-12 text-center">
          <Mascot pose="waving" alt="Debye waving" className="h-40 w-40" />
          <h2 className="text-page">No open cases. Debye is listening on WhatsApp.</h2>
          <p className="max-w-xl text-body text-secondary">When a resident sends a message, a voice note or a photo, the case opens here live, with the unit already filled in.</p>
          <LiveDot />
        </section>
      )}

      {data && data.length > 0 && (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[900px] text-left">
            <thead className="bg-sub">
              <tr className="border-b border-line text-label text-muted">
                <th className="px-5 py-3 font-medium">Case</th>
                <th className="px-4 py-3 font-medium">Unit</th>
                <th className="px-4 py-3 font-medium">Progress</th>
                <th className="px-4 py-3 font-medium">Priority</th>
                <th className="px-4 py-3 font-medium">Partner</th>
                <th className="px-4 py-3 font-medium">Updated</th>
              </tr>
            </thead>
            <tbody>
              {decisions.map((c) => (
                <DecisionRow key={c.case_id} c={c} onDone={reload} />
              ))}
              {rows.map((c) => {
                const line = lineState(STAFF_STATIONS, c.status)
                return (
                  <tr
                    key={c.case_id}
                    onClick={() => nav(`/staff/cases/${c.case_id}`)}
                    className={`h-row cursor-pointer border-b border-line last:border-b-0 hover:bg-sub ${isNew(c.case_id + c.status) ? 'animate-enter' : ''}`}
                  >
                    <td className="px-5 py-3">
                      <Link to={`/staff/cases/${c.case_id}`} className="font-semibold text-ink hover:underline" onClick={(e) => e.stopPropagation()}>
                        {c.title}
                      </Link>
                      <div className="text-meta text-muted">
                        {c.error_code ? `${errorText(c.error_code, c.error_label, null, true)} · ` : ''}
                        {c.case_id}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-body-sm">
                      {(c.address ?? '').split(',')[0]}, {c.unit_id.replace('unit_', '')}
                    </td>
                    <td className="px-4 py-3">
                      <MiniLine total={STAFF_STATIONS.length} reached={line.reached} status={c.status} />
                    </td>
                    <td className="px-4 py-3">
                      <PriorityChip priority={c.priority} />
                    </td>
                    <td className="px-4 py-3 text-body-sm">{c.partner?.name ?? <span className="text-muted">—</span>}</td>
                    <td className="px-4 py-3 text-body-sm text-secondary">{fmtRelative(c.updated_at)}</td>
                  </tr>
                )
              })}
              {shown.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-8 text-center text-muted">
                    No cases in this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
