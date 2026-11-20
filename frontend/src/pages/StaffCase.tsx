import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { ApprovalCard, CaseCard, ConsentRecord, Documents, Lifecycle, Ranking, ResultPayload, Timeline, WhatsAppThread } from '../components/case/CasePanels'
import { ErrorBox, Loading } from '../components/ui'
import { patchCase } from '../lib/liveCase'
import { useStream } from '../lib/stream'
import { useDebounced, useResource } from '../lib/useResource'

export default function StaffCase() {
  const { caseId = '' } = useParams()
  const { data: c, setData, error, reload } = useResource(() => api.staffCase(caseId), [caseId])
  const refetch = useDebounced(reload, 250)

  useStream((m) => {
    if (m.type === 'demo.reset' || m.type === 'demo.skip') return refetch()
    if (m.case_id !== caseId) return
    setData((prev) => (prev ? patchCase(prev, m) : prev))
    refetch()
  })

  if (error && !c) return <ErrorBox error={error} onRetry={reload} />
  if (!c) return <Loading what="Loading case" />

  const partnerName = (id: string) => c.ranking.find((r) => r.partner_id === id)?.name ?? (c.partner?.partner_id === id ? c.partner.name : id)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to="/staff" className="text-sm font-semibold text-plum">← All cases</Link>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-4">
          <h1 className="text-3xl">{c.title}</h1>
          <span className="font-mono text-muted">{c.case_id}</span>
        </div>
        <div className="mt-1 text-lg text-muted">
          {c.address} · <Link className="text-plum underline" to={`/staff/units/${c.unit_id}`}>Unit {c.unit_id.replace('unit_', '')}</Link>
        </div>
        <div className="mt-5 max-w-4xl">
          <Lifecycle status={c.status} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-12">
        <div className="flex flex-col gap-6 xl:col-span-4">
          <ApprovalCard c={c} onApprove={async () => setData(await api.approve(c.case_id))} />
          <CaseCard c={c} />
          <Ranking ranking={c.ranking} chosen={c.partner?.partner_id} />
          <ConsentRecord consents={c.consents} partnerName={partnerName} />
        </div>
        <div className="flex flex-col gap-6 xl:col-span-4">
          <Timeline events={c.events} />
          <ResultPayload result={c.result} />
        </div>
        <div className="flex flex-col gap-6 lg:col-span-2 xl:col-span-4">
          <WhatsAppThread messages={c.messages} />
          <Documents docs={c.documents} />
        </div>
      </div>
    </div>
  )
}
