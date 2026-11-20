import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { JobSummary } from '../api/types'
import { PartnerLayout } from '../components/Layout'
import { Empty, ErrorBox, Loading, StatusPill } from '../components/ui'
import { floorLabel, fmtSlot } from '../lib/format'
import { useStream } from '../lib/stream'
import { useNewKeys } from '../lib/useNewKeys'
import { useDebounced, useResource } from '../lib/useResource'
import { JobPanel } from './PartnerJob'

type Tab = 'new' | 'active' | 'done'
const TAB_OF = (s: string): Tab => (s === 'requested' ? 'new' : ['completed', 'invoiced', 'closed', 'declined', 'partner_declined'].includes(s) ? 'done' : 'active')
const TABS: { key: Tab; label: string }[] = [
  { key: 'new', label: 'New' },
  { key: 'active', label: 'Active' },
  { key: 'done', label: 'Done' },
]

function useIsDesktop() {
  const q = '(min-width: 1024px)'
  const [m, setM] = useState(() => window.matchMedia(q).matches)
  useEffect(() => {
    const mq = window.matchMedia(q)
    const on = () => setM(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return m
}

function JobCard({ j, partnerId, selected, fresh }: { j: JobSummary; partnerId: string; selected: boolean; fresh: boolean }) {
  return (
    <Link
      to={`/partner/${partnerId}/jobs/${j.case_id}`}
      className={`block rounded-card bg-surface p-5 shadow-card transition-colors ${selected ? 'border-2 border-plum' : 'border border-line hover:border-plum'} ${fresh ? 'animate-enter' : ''}`}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1 text-lg font-semibold leading-snug">
          {j.title.split(' – ')[0]}
          {j.error_code ? ` · ${j.error_code}` : ''}
        </div>
        {j.status === 'requested' && <span className="mt-2 h-3 w-3 shrink-0 rounded-full bg-violet" title="New" />}
      </div>
      <div className="mt-1 text-body-sm text-muted">
        {[j.address ?? j.postcode, j.floor != null ? floorLabel(j.floor) : null].filter(Boolean).join(' · ')}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <StatusPill status={j.status} />
        {j.priority === 'urgent' && <span className="text-sm font-semibold text-danger">Urgent</span>}
        {j.slot && <span className="text-sm text-muted">{fmtSlot(j.slot)}</span>}
      </div>
    </Link>
  )
}

/** /partner/:partnerId and /partner/:partnerId/jobs/:caseId. Desktop: list + detail side by side. Phone: one at a time. */
export default function PartnerPage() {
  const { partnerId = '', caseId } = useParams()
  const navigate = useNavigate()
  const desktop = useIsDesktop()
  const partner = useResource(() => api.partner(partnerId), [partnerId]).data
  const { data: jobs, error, reload } = useResource(() => api.jobs(partnerId), [partnerId])
  const refetch = useDebounced(reload, 250)
  useStream(() => refetch())
  const isNew = useNewKeys(jobs ? jobs.map((j) => j.case_id + j.status) : null)

  const selectedJob = jobs?.find((j) => j.case_id === caseId)
  const [tab, setTab] = useState<Tab | null>(null)
  const effectiveTab: Tab = tab ?? (selectedJob ? TAB_OF(selectedJob.status) : jobs?.some((j) => j.status === 'requested') ? 'new' : 'active')

  // Desktop: open the first job of the tab automatically so the detail panel is never empty.
  useEffect(() => {
    if (!desktop || caseId || !jobs?.length) return
    const first = jobs.find((j) => TAB_OF(j.status) === effectiveTab) ?? jobs[0]
    navigate(`/partner/${partnerId}/jobs/${first.case_id}`, { replace: true })
  }, [desktop, caseId, jobs, effectiveTab, navigate, partnerId])

  // When the selected job moves to another tab (e.g. accepted), follow it.
  useEffect(() => {
    if (selectedJob) setTab(TAB_OF(selectedJob.status))
  }, [selectedJob?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  const staffName = (partner?.staff as { name: string }[] | undefined)?.[0]?.name
  const list = (
    <div className="flex flex-col gap-4">
      <h1 className="text-3xl">Jobs</h1>
      <div className="flex gap-2">
        {TABS.map((t) => {
          const n = jobs?.filter((j) => TAB_OF(j.status) === t.key).length ?? 0
          const on = effectiveTab === t.key
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`rounded-pill border px-4 py-1.5 text-body-sm font-medium ${on ? 'border-plum bg-plum text-on-plum' : 'border-line bg-surface hover:border-plum'}`}
            >
              {t.label}
              {t.key !== 'done' ? ` ${n}` : ''}
            </button>
          )
        })}
      </div>
      {error && !jobs && <ErrorBox error={error} onRetry={reload} />}
      {!jobs && !error && <Loading what="Loading jobs" />}
      {jobs && jobs.filter((j) => TAB_OF(j.status) === effectiveTab).length === 0 && <Empty>Nothing here. New jobs from Debye show up instantly.</Empty>}
      {jobs
        ?.filter((j) => TAB_OF(j.status) === effectiveTab)
        .map((j) => (
          <JobCard key={j.case_id} j={j} partnerId={partnerId} selected={j.case_id === caseId} fresh={isNew(j.case_id + j.status)} />
        ))}
    </div>
  )

  return (
    <PartnerLayout partnerId={partnerId} partnerName={partner?.name} staffName={staffName}>
      {desktop ? (
        <div className="grid grid-cols-[400px_minmax(0,1fr)] items-start gap-gap">
          {list}
          {caseId ? <JobPanel key={caseId} partnerId={partnerId} caseId={caseId} staffName={staffName} /> : <Empty>Select a job</Empty>}
        </div>
      ) : caseId ? (
        <div>
          <Link to={`/partner/${partnerId}`} className="mb-3 inline-block font-semibold text-plum">
            ← All jobs
          </Link>
          <JobPanel key={caseId} partnerId={partnerId} caseId={caseId} staffName={staffName} />
        </div>
      ) : (
        list
      )}
    </PartnerLayout>
  )
}
