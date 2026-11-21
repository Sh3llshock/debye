import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { DocumentItem } from '../api/types'
import { Activity, Documents } from '../components/case/CasePanels'
import { DiagnosisPanel } from '../components/case/Diagnosis'
import { useCrumbs } from '../components/Layout'
import { ApprovalChoice, CaseProgress } from '../components/staff/CaseFlow'
import { Chat, channelOf, firstName, Pill, StagePill, SummaryCard, tenantOf } from '../components/staff/StaffBits'
import { ErrorBox, JsonView, Loading } from '../components/ui'
import { fmtDateTime, fmtEur, fmtSlot, fmtTime, humanize, maskPhone, placeLabel, unitLabel } from '../lib/format'
import { locale, t } from '../lib/i18n'
import { patchCase } from '../lib/liveCase'
import { useStream } from '../lib/stream'
import { useDebounced, useResource } from '../lib/useResource'
import { shortId } from './StaffCases'

function Card({ title, right, children, className = '' }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {title && (
        <h3 className="mb-3 flex items-center justify-between gap-2 text-panel">
          {title}
          {right}
        </h3>
      )}
      {children}
    </section>
  )
}

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {rows
        .filter(([, v]) => v != null && v !== '')
        .map(([k, v]) => (
          <div key={k} className="contents">
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
    </dl>
  )
}

export default function StaffCase() {
  const { caseId = '' } = useParams()
  const { data: c, setData, error, reload } = useResource(() => api.staffCase(caseId), [caseId])
  const unitId = c?.unit_id ?? ''
  const unit = useResource(() => (unitId ? api.staffUnit(unitId) : Promise.resolve(null)), [unitId])
  const [log, setLog] = useState(false)
  const [json, setJson] = useState(false)
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

  useCrumbs([{ label: t('Cases'), to: '/staff/cases' }, { label: shortId(caseId) }])

  if (error && !c) return <ErrorBox error={error} onRetry={reload} />
  if (!c) return <Loading what={t('Loading case')} />

  const tenant = tenantOf(c)
  const u = unit.data
  const p = u?.property
  const boiler = u?.assets.find((a) => a.type?.includes('boiler') || a.type?.includes('heater')) ?? u?.assets[0] ?? c.asset
  const k = c.consents[0]
  const seen = new Set<string>()
  const docs: DocumentItem[] = [...c.documents]
    .reverse()
    // unit documents (lease, …) belong here too, but not another case's report or invoice
    .concat((u?.documents ?? []).filter((d) => !d.case_id || d.case_id === c.case_id))
    .filter((d) => !seen.has(d.document_id) && !!seen.add(d.document_id))
  const partnerName = (id: string) => c.ranking.find((r) => r.partner_id === id)?.name ?? (c.partner?.partner_id === id ? c.partner.name : id)
  const ch = channelOf(c)
  const urgent = c.priority === 'urgent' || c.priority === 'high'

  return (
    <>
      <div className="mb-[18px] flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-page font-bold">{c.title}</h1>
          <p className="mt-1 text-secondary">
            {[tenant, placeLabel(c.address).split(' · ')[0]].filter(Boolean).join(' · ')} <span className="text-muted">· {t('unit {u}', { u: unitLabel(c.unit_id, c.address) })}</span> · {t('opened {time} via {ch}', { time: fmtTime(c.created_at), ch: ch === 'Website' ? t('Website') : ch === 'Phone' ? t('Phone') : 'WhatsApp' })}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {urgent && c.status !== 'closed' && <Pill tone="warn">{c.priority === 'urgent' ? t('Urgent · within 24 h') : t('High priority')}</Pill>}
          <StagePill c={c} />
        </div>
      </div>

      <ApprovalChoice c={c} onApprove={async () => setData(await api.approve(c.case_id))} onReject={async (reason) => setData(await api.reject(c.case_id, reason))} />

      <div className="grid grid-cols-1 items-start gap-[18px] xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="flex min-w-0 flex-col gap-4">
          <SummaryCard c={c} />
          {c.diagnosis && <DiagnosisPanel c={c} />}
          <Card
            title={t('Case progress')}
            right={
              <button className="link-btn no-underline" onClick={() => setLog(!log)}>
                {log ? t('Hide activity log') : t('Activity log ({n})', { n: c.events.filter((e) => !e.kind.startsWith('message.')).length })}
              </button>
            }
          >
            <CaseProgress c={c} />
          </Card>
          {log && <Activity c={c} />}
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <Card title={t('WhatsApp & website chat')}>
            <Chat c={c} maxH="max-h-[460px]" />
          </Card>
          <Card title={placeLabel(c.address, c.unit_id)}>
            <div className="-mt-2 mb-3.5 text-label text-muted">
              {[t('Unit {u}', { u: unitLabel(c.unit_id, c.address) }), u?.unit.size_sqm ? `${u.unit.size_sqm} m²` : null, u?.unit.rooms ? t('{n} rooms', { n: u.unit.rooms }) : null].filter(Boolean).join(' · ')}
            </div>
            <KV
              rows={[
                [t('Tenant'), u?.tenant?.name ?? tenant],
                [t('Phone'), u?.tenant?.phone_e164 ? maskPhone(u.tenant.phone_e164) : null],
                [t('Hot water'), boiler ? `${boiler.make} ${boiler.model}${boiler.installed ? ` (${boiler.installed.slice(0, 4)})` : ''}` : null],
                [t('Last service'), boiler?.last_service ? new Date(boiler.last_service).toLocaleDateString(locale(), { day: 'numeric', month: 'short', year: 'numeric' }) : null],
                [t('Building'), [p?.building_year, p?.heating_type ? humanize(p.heating_type) : null].filter(Boolean).join(' · ')],
                [t('Cost bearer'), c.cost_bearer ? humanize(c.cost_bearer) : null],
              ]}
            />
            <Link className="btn-ghost mt-3.5" to={`/staff/units/${c.unit_id}`}>
              {t('Open property')}
            </Link>
          </Card>
          {c.partner && (
            <Card title={c.partner.name}>
              <KV
                rows={[
                  [t('Technician'), c.technician ? c.technician.name : '–'],
                  [t('Visit'), c.slot ? fmtSlot(c.slot) : c.proposed_slots?.length ? t('{n} times offered', { n: c.proposed_slots.length }) : t('not booked')],
                  [t('Estimate'), c.estimated_cost_eur != null ? fmtEur(c.estimated_cost_eur) : null],
                  [t('Approved by'), c.approval?.granted && c.approval.granted_by ? c.approval.granted_by : null],
                ]}
              />
              <Link className="btn-ghost mt-3.5" to="/staff/partners">
                {t('Open partner')}
              </Link>
            </Card>
          )}
          <Card title={t('Consent')}>
            {k ? (
              <KV
                rows={[
                  [t('Shared with'), partnerName(k.partner_id)],
                  [t('Data'), k.data_shared.join(', ')],
                  [t('When'), `${fmtDateTime(k.given_at)}, ${k.channel === 'whatsapp' ? 'WhatsApp' : humanize(k.channel)}`],
                  [t('Revoked'), k.revoked_at ? fmtDateTime(k.revoked_at) : null],
                ]}
              />
            ) : (
              <span className="text-muted">{t("Nothing shared yet. No data leaves centrix without {name}'s tap.", { name: firstName(tenant) || t('the tenant') })}</span>
            )}
          </Card>
          <Card title={t('Documents')}>
            <Documents docs={docs} priceCheck={c.price_check} />
          </Card>
          {c.result && (
            <Card
              title={t('Written back to centrix')}
              right={
                <button className="link-btn no-underline" onClick={() => setJson(!json)}>
                  {json ? t('Hide JSON') : t('Show JSON')}
                </button>
              }
            >
              {json ? <JsonView value={c.result} /> : <span className="text-muted">{t('Case closed in centrix with the invoice and visit report.')}</span>}
            </Card>
          )}
        </div>
      </div>
    </>
  )
}
