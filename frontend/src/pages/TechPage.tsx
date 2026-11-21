import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { JobDetail } from '../api/types'
import { TechLayout } from '../components/Layout'
import { Icon } from '../components/icons'
import { Chip, ErrorBox, Loading, StatusChip } from '../components/ui'
import { jobTitle } from '../lib/errors'
import { floorLabel, fmtSlot } from '../lib/format'
import { t } from '../lib/i18n'
import { useStream } from '../lib/stream'
import { useNewKeys } from '../lib/useNewKeys'
import { useDebounced, useResource } from '../lib/useResource'
import { Err, JobFacts } from './PartnerJob'

/** What the technician has to do, in words. */
function techStep(status: string): { text: string; mine: boolean } {
  switch (status) {
    case 'awaiting_technician':
      return { text: t('Confirm the visit'), mine: true }
    case 'slots_proposed':
      return { text: t('Resident is picking a time'), mine: false }
    case 'scheduled':
    case 'in_progress':
      return { text: t('Visit confirmed'), mine: false }
    case 'completed':
    case 'invoiced':
    case 'closed':
      return { text: t('Done'), mine: false }
    default:
      return { text: t('Assigned to you'), mine: false }
  }
}

/** /tech/:techId and /tech/:techId/jobs/:caseId: the technician's phone page. Mobile first, one column. */
export default function TechPage() {
  const { techId = '', caseId } = useParams()
  const me = useResource(() => api.tech(techId), [techId]).data
  const { data: jobs, error, reload } = useResource(() => api.techJobs(techId), [techId])
  const refetch = useDebounced(reload, 250)
  useStream(() => refetch())
  const isNew = useNewKeys(jobs ? jobs.map((j) => j.case_id + j.status) : null)
  const first = me?.name.split(' ')[0]

  return (
    <TechLayout techId={techId} name={me?.name} partnerName={me?.partner_name}>
      <div className="mx-auto max-w-2xl">
        {caseId ? (
          <>
            <Link to={`/tech/${techId}`} className="crumb mb-3 inline-block no-underline hover:text-wine">
              ← {t('My jobs')}
            </Link>
            <TechJob key={caseId} techId={techId} caseId={caseId} />
          </>
        ) : (
          <>
            <div className="mb-[18px] flex items-center gap-4">
              <div>
                <h1 className="text-page font-bold">{first ? t('Hi {name}', { name: first }) : t('My jobs')}</h1>
                <p className="text-body-sm text-secondary">{t('Jobs your dispatcher assigned to you. Debye keeps the resident informed.')}</p>
              </div>
            </div>
            {error && !jobs && <ErrorBox error={error} onRetry={reload} />}
            {!jobs && !error && <Loading what={t('Loading jobs')} />}
            {jobs && jobs.length === 0 && <div className="panel px-5 py-8 text-center text-muted">{t('No jobs for you right now.')}</div>}
            {jobs && jobs.length > 0 && (
              <ul className="panel overflow-hidden">
                {jobs.map((j) => {
                  const step = techStep(j.status)
                  return (
                    <li key={j.case_id} className="border-b border-line last:border-b-0">
                      <Link to={`/tech/${techId}/jobs/${j.case_id}`} className={`block px-5 py-4 hover:bg-[rgba(107,31,51,.035)] ${isNew(j.case_id + j.status) ? 'animate-enter' : ''}`}>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-semibold">{jobTitle(j.title, j.error_code, j.error_label)}</span>
                          {j.priority === 'urgent' && <Chip tone="negative">{t('Urgent')}</Chip>}
                        </div>
                        <div className="text-body-sm text-secondary">{[(j.address ?? '').split(',')[0], j.floor != null ? floorLabel(j.floor) : null].filter(Boolean).join(' · ')}</div>
                        {j.slot && (
                          <div className="mt-1 flex items-center gap-1.5 text-label">
                            <Icon name="calendar" className="h-4 w-4 text-secondary" /> {fmtSlot(j.slot)}
                          </div>
                        )}
                        <div className={`mt-1 text-label ${step.mine ? 'font-semibold text-action' : 'text-muted'}`}>{step.text}</div>
                      </Link>
                    </li>
                  )
                })}
              </ul>
            )}
          </>
        )}
      </div>
    </TechLayout>
  )
}

function TechJob({ techId, caseId }: { techId: string; caseId: string }) {
  const { data: job, setData, error, reload } = useResource(() => api.techJob(techId, caseId), [techId, caseId])
  const refetch = useDebounced(reload, 250)
  useStream((m) => {
    if (!m.case_id || m.case_id === caseId) refetch()
  })
  if (error && !job) return <ErrorBox error={error} onRetry={reload} />
  if (!job) return <Loading what={t('Loading job')} />
  return (
    <section className="panel overflow-hidden">
      <div className="border-b border-line px-5 py-5">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-panel">{jobTitle(job.title, job.error_code ?? job.asset?.error_code, job.error_label ?? job.asset?.error_label, job.asset?.error_meaning)}</h1>
          {job.priority === 'urgent' && <Chip tone="negative">{t('Urgent')}</Chip>}
          <StatusChip status={job.status} />
        </div>
        <div className="mt-1 text-meta text-muted">{job.case_id}</div>
      </div>
      <div className="border-b border-line px-5 py-5">
        <ConfirmBlock techId={techId} job={job} onChange={setData} />
      </div>
      <div className="px-5 py-5">
        <JobFacts job={job} />
      </div>
    </section>
  )
}

function ConfirmBlock({ techId, job, onChange }: { techId: string; job: JobDetail; onChange: (j: JobDetail) => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const who = job.tenant?.name?.split(' ')[0] ?? t('the resident')
  const slot = job.slot ?? job.confirmed_slot

  if (job.status === 'slots_proposed')
    return (
      <div>
        <h2 className="text-panel">{t('Waiting for {who} to pick a time', { who })}</h2>
        <ul className="mt-2 flex flex-col gap-1.5">
          {job.proposed_slots.map((p) => (
            <li key={p.start} className="flex items-center gap-2 text-body">
              <Icon name="calendar" className="h-4 w-4 text-secondary" /> {fmtSlot({ start: p.start, end: p.end })}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-body-sm text-secondary">{t('You will be asked to confirm as soon as {who} picks one.', { who })}</p>
      </div>
    )

  return (
    <div>
      <div className="text-label text-muted">{t('Visit')}</div>
      <div className="mt-1 flex items-center gap-2 text-panel font-semibold">
        <Icon name="calendar" className="h-5 w-5 text-action" /> {slot ? fmtSlot(slot) : '—'}
      </div>
      {job.status === 'awaiting_technician' ? (
        <>
          <p className="mt-2 text-body-sm text-secondary">{t('{who} picked this time on WhatsApp. Confirm, and Debye confirms the visit to {who}.', { who })}</p>
          <button
            className="btn-primary mt-4 min-h-[52px] w-full text-panel"
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              setErr(null)
              try {
                onChange(await api.techConfirm(techId, job.case_id))
              } catch (e) {
                setErr(e instanceof Error ? e.message : String(e))
              } finally {
                setBusy(false)
              }
            }}
          >
            {busy ? t('Confirming…') : t('Confirm')}
          </button>
          <Err err={err} />
        </>
      ) : ['scheduled', 'in_progress'].includes(job.status) ? (
        <p className="mt-3 flex items-center gap-2 rounded bg-ok-tint px-3 py-2 text-ok">
          <Icon name="check" className="h-5 w-5" /> {t('Confirmed. Debye told {who}.', { who })}
        </p>
      ) : ['completed', 'invoiced', 'closed'].includes(job.status) ? (
        <p className="mt-3 flex items-center gap-2 text-positive">
          <Icon name="check" className="h-5 w-5" /> {t('Job done. Thank you.')}
        </p>
      ) : null}
    </div>
  )
}
