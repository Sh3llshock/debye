import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { JobSummary } from '../api/types'
import { PartnerLayout } from '../components/Layout'
import { Chip, ErrorBox, Loading } from '../components/ui'
import { jobTitle } from '../lib/errors'
import { floorLabel, fmtSlot } from '../lib/format'
import { useStream } from '../lib/stream'
import { useNewKeys } from '../lib/useNewKeys'
import { useDebounced, useResource } from '../lib/useResource'
import { JobPanel } from './PartnerJob'
import { t } from '../lib/i18n'

const DONE = new Set(['completed', 'invoiced', 'closed', 'declined', 'partner_declined'])

/** What the partner has to do next, in words (blue when it is their move). */
function nextStep(j: JobSummary): { text: string; mine: boolean } {
  switch (j.status) {
    case 'requested':
      return { text: t('New, needs your answer'), mine: true }
    case 'accepted':
    case 'reopened':
      return { text: t('Pick a technician and times'), mine: true }
    case 'slots_proposed':
      return { text: t('Times sent, waiting for resident'), mine: false }
    case 'scheduled':
    case 'in_progress':
      return { text: j.slot ? `${t('Booked')} ${fmtSlot(j.slot)}${j.technician ? ` · ${j.technician.name}` : ''}` : t('Booked'), mine: false }
    case 'awaiting_technician':
      return { text: t('Resident picked, {tech} to confirm', { tech: j.technician?.name.split(' ')[0] ?? t('technician') }), mine: false }
    case 'completed':
    case 'invoiced':
      return { text: t('Done, invoice sent'), mine: false }
    case 'closed':
      return { text: t('Closed'), mine: false }
    default:
      return { text: t('Declined'), mine: false }
  }
}

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

/** /partner/:partnerId and /partner/:partnerId/jobs/:caseId. Desktop: jobs list + job side by side. Phone: one at a time. */
export default function PartnerPage() {
  const { partnerId = '', caseId } = useParams()
  const navigate = useNavigate()
  const desktop = useIsDesktop()
  const partner = useResource(() => api.partner(partnerId), [partnerId]).data
  const { data: jobs, error, reload } = useResource(() => api.jobs(partnerId), [partnerId])
  const refetch = useDebounced(reload, 250)
  useStream(() => refetch())
  const isNew = useNewKeys(jobs ? jobs.map((j) => j.case_id + j.status) : null)

  // Desktop: open the most urgent job automatically so the work area is never empty.
  useEffect(() => {
    if (!desktop || caseId || !jobs?.length) return
    const first = jobs.find((j) => nextStep(j).mine) ?? jobs.find((j) => !DONE.has(j.status)) ?? jobs[0]
    navigate(`/partner/${partnerId}/jobs/${first.case_id}`, { replace: true })
  }, [desktop, caseId, jobs, navigate, partnerId])

  const staffName = (partner?.staff as { name: string }[] | undefined)?.[0]?.name
  const openCount = jobs?.filter((j) => !DONE.has(j.status)).length ?? 0

  const list = (
    <section className="panel overflow-hidden">
      <header className="panel-head">
        <h2 className="text-panel">{t('Jobs')}</h2>
        <span className="text-label text-muted">{t('{n} open', { n: openCount })}</span>
      </header>
      {error && !jobs && (
        <div className="p-4">
          <ErrorBox error={error} onRetry={reload} />
        </div>
      )}
      {!jobs && !error && <Loading what={t('Loading jobs')} />}
      {jobs && jobs.length === 0 && <div className="px-5 py-8 text-center text-muted">{t('No jobs yet. New jobs from Debye show up here instantly.')}</div>}
      <ul>
        {jobs?.map((j) => {
          const step = nextStep(j)
          const sel = j.case_id === caseId
          return (
            <li key={j.case_id} className="border-b border-line last:border-b-0">
              <Link to={`/partner/${partnerId}/jobs/${j.case_id}`} className={`block px-5 py-4 transition-colors ${sel ? 'bg-action-soft' : 'hover:bg-sub'} ${isNew(j.case_id + j.status) ? 'animate-enter' : ''}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{jobTitle(j.title, j.error_code, j.error_label)}</span>
                  {j.priority === 'urgent' && <Chip tone="negative">{t('Urgent')}</Chip>}
                </div>
                <div className="text-body-sm text-secondary">{[(j.address ?? j.postcode ?? '').split(',')[0], j.floor != null ? floorLabel(j.floor) : null].filter(Boolean).join(' · ')}</div>
                <div className={`mt-1 text-label ${step.mine ? 'font-semibold text-action' : 'text-muted'}`}>{step.text}</div>
              </Link>
            </li>
          )
        })}
      </ul>
    </section>
  )

  return (
    <PartnerLayout partnerId={partnerId} partnerName={partner?.name} staffName={staffName}>
      {desktop ? (
        <div className="grid grid-cols-[340px_minmax(0,1fr)] items-start gap-work">
          {list}
          {caseId ? <JobPanel key={caseId} partnerId={partnerId} caseId={caseId} staffName={staffName} jobs={jobs ?? []} /> : <div className="panel px-5 py-8 text-center text-muted">{t('Select a job')}</div>}
        </div>
      ) : caseId ? (
        <div>
          <Link to={`/partner/${partnerId}`} className="mb-3 inline-block font-semibold text-action">
            ← {t('All jobs')}
          </Link>
          <JobPanel key={caseId} partnerId={partnerId} caseId={caseId} staffName={staffName} jobs={jobs ?? []} />
        </div>
      ) : (
        list
      )}
    </PartnerLayout>
  )
}
