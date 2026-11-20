import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { CaseSummary } from '../api/types'
import { approvalProposal, MiniLine } from '../components/case/CasePanels'
import { LiveDot, useCrumbs } from '../components/Layout'
import { ErrorBox, Loading, Mascot, PriorityChip } from '../components/ui'
import { errorText } from '../lib/errors'
import { fmtEur, fmtRelative } from '../lib/format'
import { lineState, needsApproval, NO_TECH_STATIONS, STAFF_STATIONS } from '../lib/lifecycle'
import { isNoTechnicianSummary } from '../components/case/Diagnosis'
import { useStream } from '../lib/stream'
import { useNewKeys } from '../lib/useNewKeys'
import { useDebounced, useResource } from '../lib/useResource'
import { t } from '../lib/i18n'

type Filter = 'all' | 'open' | 'decision' | 'closed'
const FILTERS: { key: Filter; label: string; test: (c: CaseSummary) => boolean }[] = [
  { key: 'all', label: 'All', test: () => true },
  { key: 'open', label: 'Open', test: (c) => c.status !== 'closed' && c.status !== 'rejected' },
  { key: 'decision', label: 'Needs approval', test: (c) => needsApproval(c.status) },
  { key: 'closed', label: 'Closed', test: (c) => c.status === 'closed' || c.status === 'rejected' },
]

/** Every job needs staff approval: an amber "Needs your approval" row at the top of the table. */
function DecisionRow({ c, onDone }: { c: CaseSummary; onDone: () => void }) {
  const { data: d } = useResource(() => api.staffCase(c.case_id), [c.case_id])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const prop = d ? approvalProposal(d) : null
  return (
    <tr className="border-b border-line bg-warning-soft">
      <td colSpan={6} className="px-5 py-4">
        <div className="flex flex-wrap items-center gap-4">
          <div className="min-w-0 flex-1">
            <div className="text-label font-semibold text-warning">{t('Needs your approval')}</div>
            <div className="font-semibold">
              {prop ? t('Approve & send to {partner}', { partner: prop.partner }) : c.title}
              {prop?.meta ? ` · ${prop.meta}` : ''}
            </div>
            <div className="text-body-sm text-secondary">
              {c.title} · {(c.address ?? '').split(',')[0]}, {c.unit_id.replace('unit_', '')} · {c.case_id}
            </div>
            {err && <div className="mt-1 text-negative">{err}</div>}
          </div>
          <Link to={`/staff/cases/${c.case_id}`} className="btn-secondary">
            {t('Open case')}
          </Link>
          <Link to={`/staff/cases/${c.case_id}`} className="btn-ghost">
            {t('Reject…')}
          </Link>
          <button
            className="btn-primary"
            disabled={busy || !d}
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
            {busy ? t('Approving…') : t('Approve')}
          </button>
        </div>
      </td>
    </tr>
  )
}

export default function StaffCases() {
  useCrumbs([{ label: t('Cases') }])
  const { data, error, reload } = useResource(() => api.staffCases(), [])
  const refetch = useDebounced(reload, 250)
  useStream(() => refetch())
  const [filter, setFilter] = useState<Filter>('all')
  const nav = useNavigate()
  const isNew = useNewKeys(data ? data.map((c) => c.case_id + c.status) : null)

  const shown = data?.filter(FILTERS.find((f) => f.key === filter)!.test) ?? []
  const decisions = shown.filter((c) => needsApproval(c.status))
  // Needs-approval rows first (above), then everything else by last update.
  const rows = shown.filter((c) => !needsApproval(c.status)).sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  const open = data?.filter((c) => c.status !== 'closed' && c.status !== 'rejected').length ?? 0
  const need = data?.filter((c) => needsApproval(c.status)).length ?? 0

  return (
    <div className="flex flex-col gap-work">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-page">{t('Cases')}</h1>
          {data && (
            <p className="mt-1 text-body text-secondary">
              {t(data.length === 1 ? '{n} case' : '{n} cases', { n: data.length })} · {t('{n} open', { n: open })} · {t(need === 1 ? '{n} needs your approval' : '{n} need your approval', { n: need })}
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
              {t(f.label)}
              {data && <span className={`ml-1.5 ${filter === f.key ? 'text-on-action/70' : 'text-muted'}`}>{data.filter(f.test).length}</span>}
            </button>
          ))}
        </div>
      </div>

      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {!data && !error && <Loading what={t('Loading cases')} />}

      {data && data.length === 0 && (
        <section className="panel flex flex-col items-center gap-3 px-6 py-12 text-center">
          <Mascot pose="waving" alt={t('Debye waving')} className="h-40 w-40" />
          <h2 className="text-page">{t('No open cases. Debye is listening on WhatsApp.')}</h2>
          <p className="max-w-xl text-body text-secondary">{t('When a resident sends a message, a voice note or a photo, the case opens here live, with the unit already filled in.')}</p>
          <LiveDot />
        </section>
      )}

      {data && data.length > 0 && (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[900px] text-left">
            <thead className="bg-sub">
              <tr className="border-b border-line text-label text-muted">
                <th className="px-5 py-3 font-medium">{t('Case')}</th>
                <th className="px-4 py-3 font-medium">{t('Unit')}</th>
                <th className="px-4 py-3 font-medium">{t('Progress')}</th>
                <th className="px-4 py-3 font-medium">{t('Priority')}</th>
                <th className="px-4 py-3 font-medium">{t('Partner')}</th>
                <th className="px-4 py-3 font-medium">{t('Updated')}</th>
              </tr>
            </thead>
            <tbody>
              {decisions.map((c) => (
                <DecisionRow key={c.case_id} c={c} onDone={reload} />
              ))}
              {rows.map((c) => {
                const noTech = isNoTechnicianSummary(c)
                const line = lineState(noTech ? NO_TECH_STATIONS : STAFF_STATIONS, c.status)
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
                      <MiniLine total={line.stations.length} reached={line.reached} status={c.status} />
                    </td>
                    <td className="px-4 py-3">
                      <PriorityChip priority={c.priority} />
                    </td>
                    <td className="px-4 py-3 text-body-sm">
                      {c.partner?.name ??
                        (noTech ? (
                          <span className="text-positive">
                            {t('No technician')}
                            {c.saving_eur ? ` · ${t('saved ~{eur}', { eur: fmtEur(c.saving_eur) })}` : ''}
                          </span>
                        ) : (
                          <span className="text-muted">—</span>
                        ))}
                      {c.technician && <div className="text-meta text-muted">{c.technician.name}</div>}
                    </td>
                    <td className="px-4 py-3 text-body-sm text-secondary">{fmtRelative(c.updated_at)}</td>
                  </tr>
                )
              })}
              {shown.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-8 text-center text-muted">
                    {t('No cases in this filter.')}
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
