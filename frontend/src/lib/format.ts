import type { StatusTone } from '../theme'
import type { Slot } from '../api/types'

const TZ = 'Europe/Berlin'

export function fmtTime(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(+d)) return iso
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: TZ })
}
export function fmtDate(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(+d)) return iso
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: TZ })
}
export function fmtDateTime(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(+d)) return iso
  return d.toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: TZ })
}
export function fmtSlot(s?: Slot | null) {
  if (!s) return '—'
  if (s.label) return s.label
  const a = new Date(s.start)
  const b = new Date(s.end)
  const day = a.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: TZ })
  const t = (d: Date) => d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: TZ })
  return `${day}, ${t(a)}–${t(b)}`
}
export function fmtEur(n?: number | null, cents = false) {
  if (n === null || n === undefined || isNaN(Number(n))) return '—'
  const v = Number(n)
  return new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR', minimumFractionDigits: cents || !Number.isInteger(v) ? 2 : 0 }).format(v)
}
export function humanize(s?: string | null) {
  if (!s) return '—'
  return s.replace(/[._]/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

export const STATUS: Record<string, { label: string; tone: StatusTone }> = {
  new: { label: 'New', tone: 'info' },
  triage: { label: 'Triage', tone: 'info' },
  awaiting_approval: { label: 'Needs approval', tone: 'warning' },
  approval_required: { label: 'Needs approval', tone: 'warning' },
  requested: { label: 'Sent to partner', tone: 'plum' },
  dispatched: { label: 'Sent to partner', tone: 'plum' },
  accepted: { label: 'Accepted', tone: 'plum' },
  scheduled: { label: 'Scheduled', tone: 'plum' },
  in_progress: { label: 'On site', tone: 'plum' },
  completed: { label: 'Work done', tone: 'success' },
  invoiced: { label: 'Invoiced', tone: 'success' },
  closed: { label: 'Closed', tone: 'neutral' },
  declined: { label: 'Declined', tone: 'danger' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
}
export function statusInfo(s: string) {
  return STATUS[s] ?? { label: humanize(s), tone: 'neutral' as StatusTone }
}

/** Golden-path lifecycle shown as a stepper. */
export const LIFECYCLE = ['new', 'requested', 'accepted', 'scheduled', 'completed', 'closed'] as const
export function lifecycleIndex(s: string): number {
  const map: Record<string, number> = {
    new: 0, triage: 0, awaiting_approval: 0, approval_required: 0,
    requested: 1, dispatched: 1, declined: 1,
    accepted: 2,
    scheduled: 3, in_progress: 3,
    completed: 4, invoiced: 4,
    closed: 5,
  }
  return map[s] ?? 0
}
