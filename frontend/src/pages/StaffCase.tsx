import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { DocumentItem } from '../api/types'
import { Activity, Conversation, Inspector, PartnerChoice, ServiceLine, ZeroFormsStrip } from '../components/case/CasePanels'
import { useCrumbs } from '../components/Layout'
import { ErrorBox, Loading, PriorityChip, StatusChip } from '../components/ui'
import { fmtDateTime } from '../lib/format'
import { lineState, STAFF_STATIONS } from '../lib/lifecycle'
import { patchCase } from '../lib/liveCase'
import { useStream } from '../lib/stream'
import { useDebounced, useResource } from '../lib/useResource'

/** What the next station is waiting for, in words. */
function waitingText(status: string, who: string) {
  switch (status) {
    case 'new':
      return `waiting for ${who}'s consent`
    case 'awaiting_approval':
      return 'waiting for your decision'
    case 'requested':
    case 'accepted':
      return 'waiting for partner times'
    case 'slots_proposed':
      return `waiting for ${who} to pick`
    case 'scheduled':
      return 'after the visit'
    case 'completed':
      return 'checking invoice'
    case 'invoiced':
      return `waiting for ${who}`
    default:
      return null
  }
}

export default function StaffCase() {
  const { caseId = '' } = useParams()
  const { data: c, setData, error, reload } = useResource(() => api.staffCase(caseId), [caseId])
  const unitId = c?.unit_id ?? ''
  const unit = useResource(() => (unitId ? api.staffUnit(unitId) : Promise.resolve(null)), [unitId])
  const refetch = useDebounced(() => {
    reload()
    unit.reload()
  }, 250)

  useStream((m) => {
    if (m.type === 'demo.reset' || m.type === 'demo.skip') return refetch()
    if (m.case_id !== caseId) return
    setData((prev) => (prev ? patchCase(prev, m) : prev))
    refetch()
  })

  const street = (c?.address ?? '').split(',')[0]
  useCrumbs([{ label: 'Cases', to: '/staff' }, { label: c ? `${street} · ${c.unit_id.replace('unit_', '')}` : caseId }])

  if (error && !c) return <ErrorBox error={error} onRetry={reload} />
  if (!c) return <Loading what="Loading case" />

  const partnerName = (id: string) => c.ranking.find((r) => r.partner_id === id)?.name ?? (c.partner?.partner_id === id ? c.partner.name : id)
  const who = c.reporters[0]?.name.split(' ')[0] ?? 'the resident'
  const line = lineState(STAFF_STATIONS, c.status, c.events)

  // Case documents first (newest first), then the unit's other records (lease, certificates).
  const seen = new Set<string>()
  const docs: DocumentItem[] = [...c.documents]
    .reverse()
    .concat(unit.data?.documents ?? [])
    .filter((d) => !seen.has(d.document_id) && !!seen.add(d.document_id))

  return (
    <div className="flex flex-col gap-work">
      {/* Header work area: title, service line, zero-forms strip */}
      <section className="-mx-4 -mt-work border-b border-line bg-surface px-4 pb-6 pt-8 md:-mx-work md:px-work">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-page">{c.title}</h1>
            <StatusChip status={c.status} />
            <PriorityChip priority={c.priority} />
          </div>
          <div className="text-body-sm text-secondary">
            {c.case_id} · opened {fmtDateTime(c.created_at)}
          </div>
        </div>
        <div className="mt-8 overflow-x-auto">
          <div className="min-w-[720px]">
            <ServiceLine line={line} waiting={waitingText(c.status, who)} />
          </div>
        </div>
        <div className="mt-6">
          <ZeroFormsStrip c={c} />
        </div>
      </section>

      <div className="grid grid-cols-1 gap-work xl:grid-cols-[minmax(0,1fr)_theme(spacing.conversation)_theme(spacing.inspector)]">
        <div className="flex min-w-0 flex-col gap-work xl:col-span-2">
          <div className="grid grid-cols-1 gap-work lg:grid-cols-[minmax(0,1fr)_theme(spacing.conversation)]">
            <Activity c={c} />
            <Conversation c={c} />
          </div>
          <PartnerChoice c={c} ranking={c.ranking} chosen={c.partner?.partner_id} onApprove={async () => setData(await api.approve(c.case_id))} />
        </div>
        <Inspector c={c} unit={unit.data} docs={docs} partnerName={partnerName} />
      </div>
    </div>
  )
}
