// Shared pieces of the v3 staff portal (inbox, cases table, case page): status pill, 8-step bar,
// WhatsApp-style chat, and the case summary card.
import { useEffect, useRef } from 'react'
import type { CaseDetail, CaseSummary, ThreadMessage } from '../../api/types'
import { explainCodes } from '../../lib/errors'
import { fmtSlotShort, fmtTime, placeLabel } from '../../lib/format'
import { lineState, needsApproval, NO_TECH_STATIONS, STAFF_STATIONS } from '../../lib/lifecycle'
import { messageKey } from '../../lib/keys'
import { t } from '../../lib/i18n'
import { useNewKeys } from '../../lib/useNewKeys'
import { isNoTechnician, isNoTechnicianSummary } from '../case/Diagnosis'
import { splitButtons, zeroForms } from '../case/CasePanels'

type Tone = '' | 'hot' | 'wait' | 'blue' | 'ok' | 'red' | 'warn'
const TONE: Record<Tone, string> = {
  '': 'bg-beige text-secondary',
  wait: 'bg-beige text-secondary',
  hot: 'bg-wine-tint text-wine',
  blue: 'bg-blue-tint text-blue',
  ok: 'bg-ok-tint text-ok',
  red: 'bg-red-tint text-red',
  warn: 'bg-warn-tint text-warn',
}

/** Status in the v3 wording ("Waiting for partner", "Booked", …), English source for t(). */
const STAGE: Record<string, [string, Tone]> = {
  new: ['Diagnosing', 'hot'],
  reopened: ['Reopened', 'warn'],
  approval_pending: ['Needs approval', 'hot'],
  awaiting_approval: ['Needs approval', 'hot'],
  rejected: ['Not approved', ''],
  requested: ['Waiting for partner', 'wait'],
  accepted: ['Partner picking times', 'wait'],
  partner_declined: ['Finding another partner', 'warn'],
  slots_proposed: ['Tenant confirming time', 'wait'],
  awaiting_technician: ['Technician confirming', 'wait'],
  scheduled: ['Booked', 'blue'],
  in_progress: ['Technician on site', 'blue'],
  completed: ['Repaired · checking invoice', 'blue'],
  invoiced: ['Invoice received', 'blue'],
  closed: ['Closed', 'ok'],
}

export function stageOf(c: CaseSummary | CaseDetail): [string, Tone] {
  if (c.priority === 'urgent' && (c as CaseDetail).diagnosis?.outcome === 'emergency') return [t('Emergency'), 'red']
  if (c.status === 'closed' && ('diagnosis' in c ? isNoTechnician(c as CaseDetail) : isNoTechnicianSummary(c))) return [t('Fixed by tenant'), 'ok']
  const s = STAGE[c.status]
  return s ? [t(s[0]), s[1]] : [c.status.replace(/_/g, ' '), '']
}

export function Pill({ tone = '', children, className = '' }: { tone?: Tone; children: React.ReactNode; className?: string }) {
  return <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-[3px] text-meta font-semibold ${TONE[tone]} ${className}`}>{children}</span>
}

export const isOpen = (c: CaseSummary) => !['closed', 'rejected'].includes(c.status)
export const needsMe = (c: CaseSummary) => needsApproval(c.status)

/** Status pill; cases waiting for approval say "Needs you" in the inbox. */
export function StagePill({ c, inbox = false }: { c: CaseSummary | CaseDetail; inbox?: boolean }) {
  const [label, tone] = stageOf(c)
  return <Pill tone={tone}>{needsMe(c) && inbox ? t('Needs you') : label}</Pill>
}

/** Eight thin segments: green = done, wine = the step now. */
export function MiniBar({ c }: { c: CaseSummary }) {
  const noTech = isNoTechnicianSummary(c)
  const line = lineState(noTech ? NO_TECH_STATIONS : STAFF_STATIONS, c.status)
  const k = noTech && c.status === 'closed' ? 8 : line.reached
  return (
    <div className="grid w-[120px] grid-cols-8 gap-[3px]" aria-label={t('{n} of 8 steps', { n: k })}>
      {Array.from({ length: 8 }).map((_, i) => (
        <i key={i} className={`h-1 rounded-sm ${i < k ? 'bg-ok' : i === k ? 'bg-wine' : 'bg-beige-d'}`} />
      ))}
    </div>
  )
}

export const tenantOf = (d?: CaseDetail) => d?.reporters[0]?.name ?? null
export const firstName = (n?: string | null) => (n ?? '').split(' ')[0]

/** WhatsApp or the tenant web portal ("Website"). */
export function channelOf(d?: CaseDetail): 'WhatsApp' | 'Website' | 'Phone' {
  const created = d?.events.find((e) => e.kind === 'case.created')
  const ch = String((created?.data as Record<string, unknown> | null)?.channel ?? d?.consents[0]?.channel ?? 'whatsapp').toLowerCase()
  if (ch.includes('web') || ch.includes('portal')) return 'Website'
  if (ch.includes('voice') || ch.includes('phone') || ch.includes('call')) return 'Phone'
  return 'WhatsApp'
}

export function ChannelTag({ ch }: { ch: string }) {
  const cls = ch === 'WhatsApp' ? 'bg-wa-tint text-wa-text' : 'bg-blue-tint text-blue'
  return <span className={`rounded-sm px-1.5 py-px text-[10.5px] font-semibold ${cls}`}>{ch === 'Website' ? t('Website') : ch === 'Phone' ? t('Phone') : 'WhatsApp'}</span>
}

export function lastMessage(d?: CaseDetail): ThreadMessage | null {
  return d?.messages.length ? d.messages[d.messages.length - 1] : null
}
export function messagePreview(m: ThreadMessage | null) {
  if (!m) return ''
  if (!m.text && m.media?.length) return t('Photo') // TODO(slop:F7) icon: camera (return ReactNode with <Icon name="camera"/>)
  return m.text ? splitButtons(m.text).body : ''
}

/** WhatsApp-style thread: tenant on the right in green, Debye on the left in white (as in the mockup). */
export function Chat({ c, maxH = 'max-h-[520px]' }: { c: CaseDetail; maxH?: string }) {
  const box = useRef<HTMLDivElement>(null)
  const isNew = useNewKeys(c.messages.map(messageKey))
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight })
  }, [c.messages.length])
  const ch = channelOf(c)
  return (
    <div ref={box} className={`flex flex-col gap-2 overflow-y-auto rounded-panel bg-chat-bg p-4 ${maxH}`}>
      {c.messages.length === 0 && <span className="text-muted">{t('No messages')}</span>}
      {c.messages.map((m) => {
        const tenant = m.direction === 'in'
        const { body, buttons } = !tenant && m.text ? splitButtons(m.text) : { body: m.text ?? '', buttons: [] as string[] }
        // TODO(slop:F7) icon: mic / camera before each label
        const media = m.media?.length ? m.media.map((x) => (x.kind === 'audio' || x.kind === 'voice_note' ? t('Voice note') : t('Photo'))).join(' ') : ''
        return (
          <div key={messageKey(m)} className={`max-w-[78%] rounded-[12px] px-3 py-2 text-body leading-[1.45] shadow-bubble ${tenant ? 'self-end bg-chat-out' : 'self-start bg-surface'} ${isNew(messageKey(m)) ? 'animate-rise' : ''}`}>
            {media && <div className="text-secondary">{media}</div>}
            {body && <div className="whitespace-pre-line [overflow-wrap:anywhere]">{body}</div>}
            {buttons.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {buttons.map((b) => (
                  <span key={b} className="rounded-full bg-beige px-2.5 py-0.5 text-meta font-medium text-wine">
                    {b}
                  </span>
                ))}
              </div>
            )}
            <small className="mt-[3px] block text-right text-[10.5px] text-muted">
              {tenant ? (ch === 'Website' ? t('Website') : ch === 'Phone' ? t('Phone') : 'WhatsApp') : 'Debye'} · {fmtTime(m.ts)}
            </small>
          </div>
        )
      })}
    </div>
  )
}

function SumItem({ label, children, wide = false }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={`min-w-0 [overflow-wrap:anywhere] ${wide ? 'sm:col-span-2' : ''}`}>
      <b className="mb-0.5 block text-meta font-medium text-muted">{label}</b>
      {children}
    </div>
  )
}

/** The "Summary" card: problem, Debye's diagnosis with confidence, flat + device, tenant's times. */
export function SummaryCard({ c, className = '' }: { c: CaseDetail; className?: string }) {
  const d = c.diagnosis
  const pct = d?.confidence == null ? null : Math.round(d.confidence <= 1 ? d.confidence * 100 : d.confidence)
  const firstIn = c.messages.find((m) => m.direction === 'in' && m.text)?.text
  const asked = d?.questions_asked?.length ?? 0
  const photo = c.documents.some((x) => x.kind === 'photo')
  const z = zeroForms(c)
  const times = c.slot ? fmtSlotShort(c.slot) : c.proposed_slots?.length ? c.proposed_slots.map((s) => s.label ?? fmtSlotShort(s)).join(', ') : c.approval?.suggested_slot ? `${fmtSlotShort(c.approval.suggested_slot)} (${t('suggested')})` : null
  return (
    <div className={`rounded-panel bg-surface px-5 py-[18px] shadow-ring ${className}`}>
      <h4 className="mb-2 text-meta font-semibold tracking-normal text-muted">{t('Summary')}</h4>
      <div className="grid grid-cols-1 gap-x-[26px] gap-y-3.5 sm:grid-cols-2">
        <SumItem label={t('Problem')}>
          {c.title}
          {(firstIn || c.summary) && <>: “{firstIn ?? c.summary}”</>}
        </SumItem>
        <SumItem label={t('Diagnosis')}>
          {d ? (
            <>
              {explainCodes(d.label)}
              {pct != null && (
                <div className="mt-1.5 h-1.5 w-40 overflow-hidden rounded-full bg-beige-d">
                  <i className="block h-full bg-wine" style={{ width: `${pct}%` }} />
                </div>
              )}
              <span className="text-meta text-muted">
                {[pct != null ? t('{n}% sure', { n: pct }) : null, asked ? t(asked === 1 ? '{n} question' : '{n} questions', { n: asked }) : null, photo ? t('photo') : null].filter(Boolean).join(' · ')}
              </span>
            </>
          ) : (
            <span className="text-muted">{t('Still asking questions')}</span>
          )}
        </SumItem>
        <SumItem label={t('Flat')}>
          {placeLabel(c.address, c.unit_id)}
          {c.asset && (
            <>
              <br />
              <span className="text-muted">
                {c.asset.make} {c.asset.model}
                {c.asset.error_code ? ` · ${c.asset.error_code}` : ''}
              </span>
            </>
          )}
        </SumItem>
        <SumItem label={t('Tenant’s times')}>{times ?? <span className="text-muted">{t('Not given yet')}</span>}</SumItem>
        {z && (
          <SumItem label={t('Typed by the tenant')} wide>
            <span className="font-semibold text-wine">{t('0 fields')}</span> · {t('{n} filled from centrix', { n: z.prefilled })} · {z.inputs}
          </SumItem>
        )}
      </div>
    </div>
  )
}
