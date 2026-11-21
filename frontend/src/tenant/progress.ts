// Case status → the tenant's 8-step progress (mockup's right panel), adapted to the real flow:
// the partner proposes times and the tenant picks one, then the technician confirms.
import { locale, t } from '../lib/i18n'
import type { TCase, TCaseDetail, THome } from './api'

export type StepState = 'done' | 'now' | 'pending' | 'skip'
export interface Step {
  state: StepState
  title: string
  sub?: string
}

const ORDER = ['new', 'awaiting_approval', 'requested', 'slots_proposed', 'awaiting_technician', 'scheduled', 'completed', 'closed']
// statuses that map onto one of the 8 positions above
const POS: Record<string, number> = {
  new: 1,
  reopened: 1,
  awaiting_approval: 2,
  approval_pending: 2,
  requested: 3,
  partner_declined: 3,
  accepted: 3,
  slots_proposed: 4,
  awaiting_technician: 5,
  scheduled: 6,
  in_progress: 6,
  completed: 7,
  invoiced: 7,
  closed: 8,
}

export const isEmergency = (c: TCase) => c.type?.startsWith('emergency') || c.priority === 'emergency'
export const solvedWithoutTech = (c: TCase) =>
  c.status === 'closed' && !!c.resolution && c.resolution !== 'repaired' && !c.partner_name
export const isClosed = (c: TCase) => c.closed || c.status === 'closed'

export function stepIndex(c: TCase): number {
  if (solvedWithoutTech(c)) return 8
  return POS[c.status] ?? 1
}

export function fmtTime(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(+d)) return ''
  return d.toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit' })
}

export function fmtDay(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(+d)) return ''
  const today = new Date()
  if (d.toDateString() === today.toDateString()) return t('today') + ', ' + fmtTime(iso)
  return d.toLocaleDateString(locale(), { day: 'numeric', month: 'short' }) + ', ' + fmtTime(iso)
}

export function fmtSlot(s?: { start: string; end: string } | null): string {
  if (!s) return ''
  const a = new Date(s.start)
  const b = new Date(s.end)
  if (isNaN(+a)) return ''
  const day = a.toLocaleDateString(locale(), { weekday: 'short', day: 'numeric', month: 'short' })
  return `${day}, ${fmtTime(s.start)}${isNaN(+b) ? '' : ' – ' + fmtTime(s.end)}`
}

/** Short label for the pill / open-case card. */
export function stepShort(c: TCase): string {
  if (isEmergency(c) && !isClosed(c)) return t('Emergency')
  if (solvedWithoutTech(c)) return t('Fixed')
  switch (c.status) {
    case 'new':
    case 'reopened':
      return t('Diagnosis')
    case 'awaiting_approval':
    case 'approval_pending':
      return c.approval.rejected ? t('Manager will call') : t('Waiting for approval')
    case 'requested':
    case 'partner_declined':
    case 'accepted':
      return t('Waiting for technician')
    case 'slots_proposed':
      return t('Pick a time')
    case 'awaiting_technician':
      return t('Technician confirming')
    case 'scheduled':
    case 'in_progress':
      return t('Visit booked')
    case 'completed':
    case 'invoiced':
      return t('Confirm the repair')
    case 'closed':
      return t('Closed')
    default:
      return c.status
  }
}

export function stageLabel(c: TCase): [string, '' | 'ok' | 'red'] {
  if (isEmergency(c) && !isClosed(c)) return [t('Emergency'), 'red']
  if (solvedWithoutTech(c)) return [t('Fixed without a technician'), 'ok']
  if (isClosed(c)) return [t('Closed'), 'ok']
  return [stepShort(c), '']
}

export function steps(c: TCaseDetail, home: THome | null): Step[] {
  void home
  const i = stepIndex(c)
  const resolved = solvedWithoutTech(c)
  const at = (k: number): StepState => (resolved ? (k === 1 || k === 7 ? 'done' : 'skip') : i > k ? 'done' : i === k ? 'now' : 'pending')
  const partner = c.partner_name || t('Technician')
  const via = c.first_channel === 'whatsapp' ? t('on WhatsApp') : c.first_channel === 'voice' ? t('by phone') : t('on the website')
  const diagSub =
    c.diagnosis?.label
      ? c.diagnosis.label + (c.diagnosis.confidence ? ' · ' + t('{n}% sure', { n: Math.round(c.diagnosis.confidence * (c.diagnosis.confidence <= 1 ? 100 : 1)) }) : '')
      : c.error_code
        ? `${c.error_code}${c.error_label ? ': ' + c.error_label : ''}`
        : ''
  const approvalSub = c.approval.rejected
    ? t('Your property manager will call you')
    : c.approval.granted
      ? t('Approved')
      : c.approval.required && i === 2
        ? t('Your property manager is checking the repair')
        : ''
  const done = c.status === 'closed'
  const rows: Step[] = [
    { state: 'done', title: t('Problem reported'), sub: `${fmtDay(c.created_at)} · ${via}` },
    { state: at(1), title: t('Diagnosis'), sub: diagSub },
    { state: at(2), title: t('Property manager approves'), sub: approvalSub },
    { state: at(3), title: t('{partner} accepts', { partner }), sub: c.partner_name && i > 3 ? c.partner_name : '' },
    { state: at(4), title: t('You pick a time'), sub: i === 4 ? t('Tap the time that suits you') : c.slot ? fmtSlot(c.slot) : '' },
    { state: at(5), title: t('Technician confirms'), sub: c.technician_name && i > 4 ? c.technician_name : '' },
    { state: at(6), title: t('Visit and repair'), sub: c.slot && i >= 6 ? fmtSlot(c.slot) + (i > 6 ? ' · ' + t('done') : '') : '' },
    {
      state: resolved || done ? 'done' : i === 7 ? 'now' : 'pending',
      title: t('Done'),
      sub: resolved ? t('Fixed without a technician') : done ? t('Report filed on your home record') : i === 7 ? t('Is everything working again?') : '',
    },
  ]
  if (resolved) rows[7].state = 'done'
  if (isEmergency(c) && !isClosed(c)) {
    rows.splice(1, rows.length - 1, { state: 'now', title: t('Emergency: gas smell'), sub: t('Leave the flat. Your property manager was alerted.') })
  }
  return rows
}

export { ORDER }
