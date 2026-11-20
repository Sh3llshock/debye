import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { CaseSummary } from '../api/types'
import { PriorityBadge } from '../components/case/CasePanels'
import { Icon } from '../components/icons'
import { DebyeMark, Empty, ErrorBox, Loading, StatusPill } from '../components/ui'
import { LiveDot } from '../components/Layout'
import { fmtEur, fmtRelative } from '../lib/format'
import { useStream } from '../lib/stream'
import { useNewKeys } from '../lib/useNewKeys'
import { useDebounced, useResource } from '../lib/useResource'

type Filter = 'all' | 'open' | 'approval' | 'closed'
const FILTERS: { key: Filter; label: string; test: (c: CaseSummary) => boolean }[] = [
  { key: 'all', label: 'All', test: () => true },
  { key: 'open', label: 'Open', test: (c) => c.status !== 'closed' && c.status !== 'awaiting_approval' },
  { key: 'approval', label: 'Waiting for approval', test: (c) => c.status === 'awaiting_approval' },
  { key: 'closed', label: 'Closed', test: (c) => c.status === 'closed' },
]

function ApprovalBanner({ caseId, onDone }: { caseId: string; onDone: () => void }) {
  const { data: c } = useResource(() => api.staffCase(caseId), [caseId])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  if (!c) return null
  const amount = c.approval?.amount_eur ?? c.estimated_cost_eur
  return (
    <section className="animate-rise flex flex-wrap items-center gap-6 rounded-card bg-plum p-card text-on-plum shadow-pop">
      <div className="min-w-0 flex-1">
        <div className="text-eyebrow font-semibold uppercase text-lilac">Needs your approval</div>
        <h2 className="mt-2 text-2xl !text-on-plum">Approve {fmtEur(amount)} repair?</h2>
        <p className="mt-2 text-body-sm text-on-plum-muted">
          <span className="font-mono">{c.case_id}</span> · {c.title} · {(c.address ?? '').split(',')[0]}, unit {c.unit_id.replace('unit_', '')}
          {c.partner ? ` · ${c.partner.name}` : ''}.
          <br />
          {c.approval?.rule ?? 'Estimate is above the auto-approval limit'}, so Debye paused and asked you.
        </p>
        {err && <div className="mt-2 rounded bg-danger-soft p-2 text-danger">{err}</div>}
      </div>
      <div className="flex flex-wrap gap-3">
        <button
          className="btn-inverse"
          disabled={busy}
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
          {busy ? 'Approving…' : <>Approve {fmtEur(amount)} <Icon name="arrow" className="h-5 w-5" /></>}
        </button>
        <Link to={`/staff/cases/${c.case_id}`} className="btn border-[1.5px] border-line-on-plum text-on-plum hover:bg-plum-dark">
          Open case
        </Link>
      </div>
    </section>
  )
}

function Stat({ value, label }: { value: string | number; label: string }) {
  return (
    <div className="rounded-card border border-line bg-surface p-card-sm shadow-card">
      <div className="text-stat font-medium text-plum">{value}</div>
      <div className="mt-1 text-body-sm text-muted">{label}</div>
    </div>
  )
}

export default function StaffCases() {
  const { data, error, reload } = useResource(() => api.staffCases(), [])
  const refetch = useDebounced(reload, 250)
  useStream(() => refetch())
  const [filter, setFilter] = useState<Filter>('all')
  const nav = useNavigate()
  const isNew = useNewKeys(data ? data.map((c) => c.case_id + c.status) : null)

  const waiting = data?.filter((c) => c.status === 'awaiting_approval') ?? []
  const shown = data?.filter(FILTERS.find((f) => f.key === filter)!.test) ?? []
  const buildings = new Set(data?.map((c) => (c.address ?? '').split(',')[0]).filter(Boolean))

  return (
    <div className="flex flex-col gap-gap">
      <div>
        <h1 className="text-3xl">Cases</h1>
        <p className="mt-1 text-lg text-muted">
          {[...buildings][0] ?? 'Your buildings'}
          {buildings.size > 1 ? ` and ${buildings.size - 1} more buildings` : ''} · every case opened by Debye from WhatsApp
        </p>
      </div>

      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {!data && !error && <Loading what="Loading cases" />}

      {waiting[0] && <ApprovalBanner key={waiting[0].case_id} caseId={waiting[0].case_id} onDone={reload} />}

      {data && (
        <div className="flex flex-wrap gap-3">
          {FILTERS.map((f) => {
            const n = data.filter(f.test).length
            const on = filter === f.key
            return (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                className={`rounded-pill border px-5 py-2 text-body-sm font-medium transition-colors ${on ? 'border-plum bg-plum text-on-plum' : 'border-line bg-surface text-ink hover:border-plum'}`}
              >
                {f.label} {n}
              </button>
            )
          })}
        </div>
      )}

      {data && data.length === 0 && (
        <section className="flex flex-col items-center gap-4 rounded-card border border-dashed border-line bg-surface px-card py-16 text-center">
          <DebyeMark size={72} />
          <h2 className="text-2xl">No open cases. Debye is listening on WhatsApp.</h2>
          <p className="max-w-xl text-body-sm text-muted">When a resident sends a message, a voice note or a photo, the case opens here live, with the unit already filled in.</p>
          <LiveDot />
        </section>
      )}
      {data && data.length > 0 && shown.length === 0 && <Empty>No cases in this filter.</Empty>}

      {shown.length > 0 && (
        <div className="overflow-hidden rounded-card border border-line bg-surface shadow-card">
          <table className="w-full text-left">
            <thead className="bg-surface-alt">
              <tr className="label">
                <th className="px-card-sm py-4">Case</th>
                <th className="hidden px-4 py-4 md:table-cell">Unit</th>
                <th className="px-4 py-4">Status</th>
                <th className="hidden px-4 py-4 md:table-cell">Priority</th>
                <th className="hidden px-4 py-4 lg:table-cell">Partner</th>
                <th className="hidden px-4 py-4 lg:table-cell">Updated</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => (
                <tr
                  key={c.case_id}
                  onClick={() => nav(`/staff/cases/${c.case_id}`)}
                  className={`cursor-pointer border-t border-line transition-colors hover:bg-plum-faint ${isNew(c.case_id + c.status) ? 'animate-enter' : ''}`}
                >
                  <td className="px-card-sm py-5">
                    <Link to={`/staff/cases/${c.case_id}`} className="text-lg font-semibold text-ink" onClick={(e) => e.stopPropagation()}>
                      {c.title}
                    </Link>
                    <div className="mt-1 flex items-center gap-2">
                      <span className="font-mono text-sm text-muted">{c.case_id}</span>
                      {c.status === 'awaiting_approval' && <span className="rounded-pill bg-plum px-2 py-0.5 text-xs font-semibold text-on-plum">approval needed</span>}
                    </div>
                  </td>
                  <td className="hidden px-4 py-5 md:table-cell">
                    {(c.address ?? '').split(',')[0]} · {c.unit_id.replace('unit_', '')}
                  </td>
                  <td className="px-4 py-5">
                    <StatusPill status={c.status} />
                  </td>
                  <td className="hidden px-4 py-5 md:table-cell">
                    <PriorityBadge priority={c.priority} />
                  </td>
                  <td className="hidden px-4 py-5 lg:table-cell">{c.partner?.name ?? <span className="text-muted">—</span>}</td>
                  <td className="hidden px-4 py-5 text-muted lg:table-cell">
                    <span className="flex items-center justify-between gap-2">
                      {fmtRelative(c.updated_at)} <Icon name="chevron" className="h-5 w-5" />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.length > 0 && (
        <div className="grid grid-cols-2 gap-gap lg:grid-cols-4">
          <Stat value={data.length} label={data.length === 1 ? 'case' : 'cases'} />
          <Stat value={0} label="forms filled by tenants" />
          <Stat value={data.filter((c) => c.status !== 'closed').length} label="open right now" />
          <Stat value={waiting.length} label="approval needed from you" />
        </div>
      )}
    </div>
  )
}
