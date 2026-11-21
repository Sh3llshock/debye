// v3 case page: "Diagnosed. Approve the partner" card (partner cards) and the vertical "Case progress".
import { useState, type ReactNode } from 'react'
import type { CaseDetail, CaseEvent } from '../../api/types'
import { explainCodes } from '../../lib/errors'
import { fmtDateTime, fmtEur, fmtSlot, fmtSlotShort, fmtTime } from '../../lib/format'
import { needsApproval } from '../../lib/lifecycle'
import { t } from '../../lib/i18n'
import { Icon } from '../icons'
import { diagnosisOutcome, isNoTechnician } from '../case/Diagnosis'
import { priceCheckInfo } from '../case/CasePanels'
import { channelOf, firstName, Pill, tenantOf } from './StaffBits'

const REJECT_REASONS = ['Tenant must pay this', 'Too expensive, get a second quote', 'Not urgent, wait for the annual service', 'Duplicate of another case']

/** Staff approve every job before the partner sees it: Debye's ranked partners as cards, the recommended one first. */
export function ApprovalChoice({ c, onApprove, onReject }: { c: CaseDetail; onApprove: () => Promise<void>; onReject: (reason: string) => Promise<void> }) {
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  if (!needsApproval(c.status)) return null
  const recId = c.approval?.partner?.partner_id ?? c.ranking[0]?.partner_id
  const ranked = c.ranking.length ? [...c.ranking].sort((a, b) => Number(b.partner_id === recId) - Number(a.partner_id === recId)).slice(0, 3) : c.approval?.partner ? [{ partner_id: c.approval.partner.partner_id, name: c.approval.partner.name, score: 1, reasons: [] as string[] }] : []
  const amount = c.approval?.amount_eur ?? c.estimated_cost_eur
  const tech = c.approval?.suggested_technician
  const slot = c.approval?.suggested_slot
  const who = firstName(tenantOf(c)) || t('the tenant')
  const recName = ranked[0]?.name ?? t('the partner')
  const run = async (kind: 'approve' | 'reject', fn: () => Promise<void>) => {
    setBusy(kind)
    setErr(null)
    try {
      await fn()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }
  return (
    // TODO(slop:F33) replace shadow-lift with shadow-card + 1.5px wine ring (shadow-rec); no big blur
    <section className="animate-rise mb-[18px] rounded-panel bg-surface p-5 shadow-lift" aria-live="polite">
      <h3 className="mb-3 flex items-center justify-between gap-2 text-panel">
        {t('Diagnosed. Approve the partner')}
        <Pill tone="hot">{t('Needs you')}</Pill>
      </h3>
      <div className="leading-normal text-secondary">{t('Debye ranked the partners who are qualified, free soon and nearby. The partner sees nothing until you approve.')}</div>
      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-3">
        {ranked.map((r, i) => {
          const rec = i === 0
          return (
            <div key={r.partner_id} className={`flex flex-col gap-2 rounded-tile p-3.5 ${rec ? 'bg-surface shadow-rec' : 'bg-bg shadow-ring'}`}>
              {rec ? <span className="self-start rounded-full bg-wine px-[9px] py-0.5 text-tiny font-bold text-cream">{t('Recommended')}</span> : <span className="h-[19px]" />}
              <b className="text-[15px]">{r.name}</b>
              {rec && amount != null && <div className="text-[22px] font-semibold tracking-[-0.02em]">{fmtEur(amount)}</div>}
              <span className="text-meta text-muted">
                {t('Match score {n}', { n: Math.round(r.score * 100) })}
                {rec && tech ? ` · ${tech.name}` : ''}
                {rec && slot ? ` · ${fmtSlotShort(slot)}` : ''}
              </span>
              {r.reasons.length > 0 && (
                <ul className="m-0 pl-4 text-label leading-normal text-secondary">
                  {r.reasons.map((w) => (
                    <li key={w} className="list-disc">
                      {w}
                    </li>
                  ))}
                </ul>
              )}
              {rec ? (
                <button className="btn-primary mt-auto justify-center" disabled={!!busy} onClick={() => run('approve', onApprove)}>
                  {busy === 'approve' ? t('Approving…') : t('Approve & send to {partner}', { partner: r.name.replace(/ GmbH$| KG$/, '') })}
                </button>
              ) : (
                <span className="mt-auto text-meta text-muted">{t('{name} agreed to share data with {partner} only.', { name: who, partner: recName.replace(/ GmbH$| KG$/, '') })}</span>
              )}
            </div>
          )
        })}
      </div>
      <div className="mt-2.5 text-label text-warn">{t('Every job needs your approval before the partner is contacted.')}</div>
      {!rejecting ? (
        <button className="link-btn mt-2.5" onClick={() => setRejecting(true)}>
          {t('I’ll handle this myself')}
        </button>
      ) : (
        <div className="mt-4 border-t border-line pt-4">
          <div className="text-label font-medium">{t('Why are you rejecting? Debye tells the resident.')}</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {REJECT_REASONS.map((r) => (
              <button key={r} type="button" onClick={() => setReason(t(r))} className={`rounded-full px-3 py-1 text-label ${reason === t(r) ? 'bg-wine-tint font-semibold text-wine' : 'bg-beige hover:bg-beige-d'}`}>
                {t(r)}
              </button>
            ))}
          </div>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder={t('Reason')} className="field mt-2" />
          <div className="mt-2 flex flex-wrap gap-2">
            <button className="btn-danger" disabled={!!busy || !reason.trim()} onClick={() => run('reject', () => onReject(reason.trim()))}>
              {busy === 'reject' ? t('Rejecting…') : t('Reject job')}
            </button>
            <button className="btn-ghost" onClick={() => setRejecting(false)}>
              {t('Cancel')}
            </button>
          </div>
        </div>
      )}
      {err && <div className="mt-2 rounded bg-red-tint p-2 text-red">{err}</div>}
    </section>
  )
}

type StepState = 'done' | 'now' | 'pending'
interface Step {
  s: StepState
  title: string
  mod: string
  time?: string
  body?: ReactNode
}

const ev = (c: CaseDetail, ...kinds: string[]): CaseEvent | undefined => c.events.find((e) => kinds.includes(e.kind))
const evLast = (c: CaseDetail, ...kinds: string[]): CaseEvent | undefined => [...c.events].reverse().find((e) => kinds.includes(e.kind))
const time = (e?: CaseEvent) => (e ? fmtTime(e.ts) : '')

function What({ children, gray = false }: { children: ReactNode; gray?: boolean }) {
  return <div className={`mt-1 leading-normal ${gray ? 'text-muted' : 'text-secondary'}`}>{children}</div>
}

/** Order of the statuses along the flow (index = how far the case got). */
const ORDER: Record<string, number> = {
  new: 1, reopened: 1, approval_pending: 2, awaiting_approval: 2, rejected: 2, partner_declined: 3,
  requested: 3, accepted: 3, slots_proposed: 4, awaiting_technician: 4, scheduled: 5, in_progress: 5, completed: 5, invoiced: 5, closed: 6,
}

export function caseSteps(c: CaseDetail): Step[] {
  const who = tenantOf(c) ?? t('the tenant')
  const pn = (c.partner?.name ?? c.approval?.partner?.name ?? '').replace(/ GmbH$| KG$/, '')
  const at = ORDER[c.status] ?? 1
  const st = (i: number): StepState => (at > i ? 'done' : at === i ? 'now' : 'pending')
  const first = c.messages.find((m) => m.direction === 'in' && m.text)?.text ?? c.summary
  const steps: Step[] = [
    {
      s: 'done',
      title: t('Case opened'),
      mod: t('Input'),
      time: fmtTime(c.created_at),
      body: (
        <What>
          {first ? `“${first}” · ` : ''}
          {t('via {ch}', { ch: channelOf(c) === 'Website' ? t('Website') : channelOf(c) === 'Phone' ? t('Phone') : 'WhatsApp' })}. {t('Recognised {name} by phone number.', { name: who })}
        </What>
      ),
    },
  ]
  // diagnosis
  const d = c.diagnosis
  const pct = d?.confidence == null ? null : Math.round(d.confidence <= 1 ? d.confidence * 100 : d.confidence)
  const qs = (d?.questions_asked ?? []).map((x) => (typeof x === 'string' ? { q: x, a: '' } : { q: x.question ?? x.text ?? x.q ?? '', a: x.answer_text ?? x.answer ?? x.a ?? '' })).filter((x) => x.q)
  const diagDone = !!d || at > 1
  steps.push({
    s: diagDone ? 'done' : 'now',
    title: diagDone ? t('Diagnosis') : t('Diagnosis in progress'),
    mod: t('Missing data · Classifier'),
    time: time(ev(c, 'diagnosis.recorded', 'diagnosis.made', 'diagnosis.completed')),
    body: d ? (
      <>
        <What>
          <b className="text-ink">{explainCodes(d.label)}</b>
          {pct != null ? ` · ${t('{n}% sure', { n: pct })}` : ''}
        </What>
        {qs.length > 0 && (
          <ul className="mt-2.5 grid grid-cols-1 gap-x-[18px] gap-y-1.5 sm:grid-cols-2">
            {qs.map((x, i) => (
              <li key={i} className="grid grid-cols-[20px_minmax(0,1fr)] gap-2 leading-snug">
                <span className="mt-px grid h-[18px] w-[18px] place-items-center rounded-full bg-ok text-[10px] font-bold text-cream"><Icon name="check" className="h-3 w-3" /></span>
                <span>
                  {x.q}
                  {x.a && <span className="font-medium"> → {x.a}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </>
    ) : (
      <What gray>{t('Debye is asking {name} a few quick questions.', { name: firstName(who) })}</What>
    ),
  })
  if (isNoTechnician(c)) {
    const care = diagnosisOutcome(c) === 'caretaker'
    steps.push({
      s: c.status === 'closed' ? 'done' : 'now',
      title: care ? t('Caretaker handles it') : t('Fixed by the tenant'),
      mod: t('Closing'),
      time: time(ev(c, 'case.closed', 'caretaker.notified')),
      body: <What>{care ? t('No technician needed. The caretaker was told.') : t('Fixed with Debye’s help. No technician, no cost.')}{c.saving_eur ? ` ${t('Saved ~{eur}', { eur: fmtEur(c.saving_eur) })}.` : ''}</What>,
    })
    return steps
  }
  // consent + approval
  const k = c.consents[0]
  const granted = ev(c, 'approval.granted')
  steps.push({
    s: needsApproval(c.status) ? 'now' : c.status === 'rejected' ? 'pending' : at > 2 ? 'done' : 'pending',
    title: needsApproval(c.status) ? t('Approve the partner') : c.status === 'rejected' ? t('Handled by you') : granted ? t('Partner approved: {p}', { p: pn }) : t('Approval'),
    mod: t('Consent · Matching · Approval'),
    time: time(granted ?? ev(c, 'approval.rejected', 'approval.required')),
    body: needsApproval(c.status) ? (
      <What>
        {k ? t('{name} agreed to share {data} with {p}.', { name: firstName(who), data: k.data_shared.join(', '), p: pn }) + ' ' : ''}
        {t('Waiting for your choice above.')}
      </What>
    ) : c.status === 'rejected' ? (
      <What>
        {t('Not approved')}
        {c.approval?.rejected_by ? ` ${t('by {name}', { name: c.approval.rejected_by })}` : ''}
        {c.approval?.reason ?? c.approval?.rejected_reason ? `: ${c.approval?.reason ?? c.approval?.rejected_reason}` : ''}. {t('The tenant was told.')}
      </What>
    ) : granted ? (
      <What>
        {c.approval?.granted_by ? t('Approved by {name}', { name: c.approval.granted_by }) : t('Approved')}
        {c.approval?.amount_eur != null || c.estimated_cost_eur != null ? ` · ${fmtEur(c.approval?.amount_eur ?? c.estimated_cost_eur)}` : ''}
        {k ? ` · ${t('consent recorded ({data})', { data: k.data_shared.join(', ') })}` : ''}
      </What>
    ) : (
      k && <What>{t('consent recorded ({data})', { data: k.data_shared.join(', ') })}</What>
    ),
  })
  if (c.status === 'rejected') return steps
  // partner
  const accepted = ev(c, 'job.accepted')
  const declined = c.events.filter((e) => e.kind === 'job.declined')
  steps.push({
    s: st(3),
    title: accepted ? t('{p} accepted', { p: pn }) : t('Waiting for {p}', { p: pn || t('the partner') }),
    mod: t('Order job'),
    time: time(accepted ?? ev(c, 'job.sent')),
    body: accepted ? (
      <What>
        {c.technician ? t('{tech} assigned', { tech: c.technician.name }) : t('Choosing a technician')}
        {c.proposed_slots?.length ? ` · ${t('{n} times offered', { n: c.proposed_slots.length })}` : ''}
      </What>
    ) : at >= 3 ? (
      <What gray>
        {t('Job sent to {p}.', { p: pn })}
        {declined.length ? ` ${t('Declined by another partner, Debye picked the next one.')}` : ''}
      </What>
    ) : undefined,
  })
  // booking
  const confirmed = evLast(c, 'technician.confirmed', 'slot.confirmed')
  steps.push({
    s: st(4),
    title: at > 4 ? t('Visit booked') : c.status === 'awaiting_technician' ? t('{tech} confirming the time', { tech: firstName(c.technician?.name) || t('Technician') }) : t('Tenant picks a time'),
    mod: t('Order confirmation'),
    time: time(confirmed),
    body: c.slot ? <What>{fmtSlot(c.slot)}</What> : c.status === 'slots_proposed' ? <What gray>{t('Waiting for {name} to pick one of the times.', { name: firstName(who) })}</What> : undefined,
  })
  // visit + closing
  const inv = c.documents.find((x) => x.kind === 'invoice')
  const x = (inv?.extracted ?? {}) as Record<string, unknown>
  const gross = typeof x.gross_eur === 'number' ? (x.gross_eur as number) : null
  const pc = priceCheckInfo(x.price_check ?? c.price_check).status
  const visit: Record<string, string> = { scheduled: 'Scheduled', in_progress: 'Technician on site', completed: 'Repair done, invoice coming', invoiced: 'Invoice received' }
  steps.push({
    s: c.status === 'closed' ? 'done' : at === 5 ? 'now' : 'pending',
    title: c.status === 'closed' ? t('Repaired and closed') : t('Visit and closing'),
    mod: t('Closing'),
    time: c.status === 'closed' ? fmtDateTime(c.closed_at ?? ev(c, 'case.closed')?.ts) : c.slot ? fmtSlotShort(c.slot) : '',
    body:
      at >= 5 ? (
        <What>
          {c.status === 'closed' ? t('Closed') : t(visit[c.status] ?? '')}
          {gross != null ? ` · ${t('invoice {eur}', { eur: fmtEur(gross, true) })}` : ''}
          {pc === 'ok' ? ` · ${t('price check passed')}` : pc === 'flagged' ? ` · ${t('price check flagged')}` : ''}
          {c.status === 'closed' ? `. ${t('Written back to centrix.')}` : ''}
        </What>
      ) : undefined,
  })
  return steps
}

/** The vertical flow with numbered dots: green done, wine now (with a halo), beige pending. */
export function CaseProgress({ c }: { c: CaseDetail }) {
  const steps = caseSteps(c)
  return (
    <ol className="m-0 list-none p-0">
      {steps.map((x, n) => {
        const last = n === steps.length - 1
        return (
          <li key={n} className={`relative grid grid-cols-[28px_minmax(0,1fr)] gap-3.5 ${last ? '' : 'pb-[22px]'}`}>
            {!last && <span className={`absolute bottom-0.5 left-[13px] top-[30px] w-0.5 rounded-sm ${x.s === 'done' ? 'bg-ok-line' : 'bg-beige-d'}`} />}
            <span
              className={`relative z-[1] grid h-7 w-7 place-items-center rounded-full border-[1.5px] text-meta font-bold ${
                x.s === 'done' ? 'border-ok bg-ok text-cream' : x.s === 'now' ? 'animate-station border-wine bg-wine text-cream shadow-[0_0_0_5px_theme(colors.wine-tint)]' : 'border-beige-d bg-bg text-muted'
              }`}
            >
              {x.s === 'done' ? <Icon name="check" className="h-3.5 w-3.5" /> : n + 1}
            </span>
            <div className="min-w-0">
              <div className="flex justify-between gap-3 pt-1">
                <span>
                  <b className={`text-[15px] ${x.s === 'pending' ? 'font-medium text-muted' : 'font-semibold'}`}>{x.title}</b>
                  <span className="ml-2 text-tiny text-muted">{x.mod}</span>
                </span>
                <time className="whitespace-nowrap text-meta text-muted">{x.time}</time>
              </div>
              {x.body}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
