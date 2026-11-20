import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { DocumentItem } from '../api/types'
import {
  ApprovalCard,
  CaseCard,
  ConsentRecord,
  Documents,
  LivePill,
  PriorityBadge,
  Ranking,
  ResultPayload,
  Timeline,
  UnitCard,
  WhatsAppThread,
  ZeroFormsCard,
} from '../components/case/CasePanels'
import { ErrorBox, Loading, StatusPill } from '../components/ui'
import { fmtRelative } from '../lib/format'
import { patchCase } from '../lib/liveCase'
import { useStream } from '../lib/stream'
import { useDebounced, useResource } from '../lib/useResource'

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

  if (error && !c) return <ErrorBox error={error} onRetry={reload} />
  if (!c) return <Loading what="Loading case" />

  const partnerName = (id: string) => c.ranking.find((r) => r.partner_id === id)?.name ?? (c.partner?.partner_id === id ? c.partner.name : id)
  const unitLabel = c.unit_id.replace('unit_', '')
  const street = (c.address ?? '').split(',')[0]

  // Case documents first (newest first), then the unit's other records (lease, certificates).
  const seen = new Set<string>()
  const docs: DocumentItem[] = [...c.documents].reverse().concat(unit.data?.documents ?? []).filter((d) => !seen.has(d.document_id) && !!seen.add(d.document_id))

  return (
    <div className="-mt-2 flex flex-col gap-6">
      <div>
        <div className="text-body-sm text-muted">
          <Link to="/staff" className="hover:text-plum">
            Cases
          </Link>{' '}
          /{' '}
          <Link to={`/staff/units/${c.unit_id}`} className="hover:text-plum">
            {street} · Unit {unitLabel}
          </Link>
        </div>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-wrap items-center gap-4">
            <h1 className="text-3xl">{c.title}</h1>
            <StatusPill status={c.status} big />
            <PriorityBadge priority={c.priority} />
          </div>
          <div className="text-right">
            <div className="font-mono text-lg text-plum">{c.case_id}</div>
            <div className="mt-1">
              <LivePill label={`Live · updated ${fmtRelative(c.updated_at)}`} />
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1fr)_minmax(0,0.9fr)]">
        <div className="flex flex-col gap-6">
          <ApprovalCard c={c} onApprove={async () => setData(await api.approve(c.case_id))} />
          <CaseCard c={c} />
          <ZeroFormsCard c={c} />
        </div>
        <div className="flex flex-col gap-gap">
          <Timeline c={c} />
        </div>
        <div className="flex flex-col gap-gap lg:col-span-2 xl:col-span-1">
          <WhatsAppThread c={c} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-gap lg:grid-cols-2 xl:grid-cols-4">
        <UnitCard u={unit.data} unitId={c.unit_id} />
        <Ranking ranking={c.ranking} chosen={c.partner?.partner_id} />
        <ConsentRecord c={c} partnerName={partnerName} />
        <Documents docs={docs} title={`Documents · unit ${unitLabel}`} priceCheck={c.price_check} />
      </div>

      <ResultPayload result={c.result} />
    </div>
  )
}
