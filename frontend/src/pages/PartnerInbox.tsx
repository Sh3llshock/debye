import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { PartnerLayout } from '../components/Layout'
import { Empty, ErrorBox, Loading, PriorityPill, StatusPill } from '../components/ui'
import { fmtDateTime, fmtSlot } from '../lib/format'
import { useStream } from '../lib/stream'
import { useNewKeys } from '../lib/useNewKeys'
import { useDebounced, useResource } from '../lib/useResource'

export function usePartner(partnerId: string) {
  return useResource(() => api.partner(partnerId), [partnerId]).data
}

const ACTION: Record<string, string> = {
  requested: 'New job — accept or decline',
  accepted: 'Propose time slots',
  scheduled: 'Visit booked',
  in_progress: 'On site — mark as done',
}

export default function PartnerInbox() {
  const { partnerId = '' } = useParams()
  const partner = usePartner(partnerId)
  const { data, error, reload } = useResource(() => api.jobs(partnerId), [partnerId])
  const refetch = useDebounced(reload, 250)
  useStream(() => refetch())
  const isNew = useNewKeys(data ? data.map((j) => j.case_id + j.status) : null)

  return (
    <PartnerLayout partnerId={partnerId} partnerName={partner?.name}>
      <h1 className="mb-4 text-2xl">Your jobs</h1>
      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {!data && !error && <Loading what="Loading jobs" />}
      {data && data.length === 0 && <Empty>No jobs yet. New jobs from Debye show up here instantly.</Empty>}
      <ul className="flex flex-col gap-3">
        {data?.map((j) => (
          <li key={j.case_id}>
            <Link
              to={`/partner/${partnerId}/jobs/${j.case_id}`}
              className={`block rounded-card border bg-surface p-4 shadow-card active:bg-plum-soft ${j.status === 'requested' ? 'border-plum border-2' : 'border-line'} ${isNew(j.case_id + j.status) ? 'animate-enter' : ''}`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <StatusPill status={j.status} />
                <PriorityPill priority={j.priority} />
                <span className="ml-auto text-sm text-muted">{fmtDateTime(j.updated_at)}</span>
              </div>
              <div className="mt-2 text-xl font-semibold text-plum">{j.title}</div>
              <div className="text-muted">{j.address}</div>
              {j.slot && <div className="mt-1 font-semibold">📅 {fmtSlot(j.slot)}</div>}
              {ACTION[j.status] && <div className="mt-2 font-semibold text-plum">{ACTION[j.status]} →</div>}
            </Link>
          </li>
        ))}
      </ul>
    </PartnerLayout>
  )
}
