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
  awaiting_approval: { label: 'Needs approval', tone: 'warning' },
  requested: { label: 'Requested', tone: 'plum' },
  accepted: { label: 'Accepted', tone: 'info' },
  slots_proposed: { label: 'Slots proposed', tone: 'warning' },
  scheduled: { label: 'Scheduled', tone: 'info' },
  in_progress: { label: 'In progress', tone: 'warning' },
  completed: { label: 'Completed', tone: 'success' },
  invoiced: { label: 'Invoiced', tone: 'success' },
  closed: { label: 'Closed', tone: 'neutral' },
  declined: { label: 'Declined', tone: 'danger' },
  partner_declined: { label: 'Partner declined', tone: 'danger' },
  reopened: { label: 'Reopened', tone: 'warning' },
}
export function statusInfo(s: string) {
  return STATUS[s] ?? { label: humanize(s), tone: 'neutral' as StatusTone }
}

/** Lifecycle segments shown on the case card (design: Requested → Accepted → Scheduled → Done → Invoiced → Closed). */
export const LIFECYCLE = ['Requested', 'Accepted', 'Scheduled', 'Done', 'Invoiced', 'Closed'] as const
/** How many lifecycle segments are filled for a status. */
export function lifecycleDone(s: string): number {
  const map: Record<string, number> = {
    new: 0, awaiting_approval: 0, partner_declined: 0, reopened: 0,
    requested: 1,
    accepted: 2, slots_proposed: 2,
    scheduled: 3, in_progress: 3,
    completed: 4,
    invoiced: 5,
    closed: 6,
  }
  return map[s] ?? 0
}

export const OPEN_EXCLUDED = new Set(['closed'])

/** "2 min ago", "18:21", "Yesterday", "Mon" for list views. */
export function fmtRelative(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(+d)) return iso
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff >= 0 && diff < 60) return 'just now'
  if (diff >= 0 && diff < 3600) return `${Math.round(diff / 60)} min ago`
  const day = (x: Date) => new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(x)
  if (day(d) === day(new Date())) return fmtTime(iso)
  if (day(d) === day(new Date(Date.now() - 86400_000))) return 'Yesterday'
  return d.toLocaleDateString('en-GB', { weekday: 'short', hour: '2-digit', minute: '2-digit', timeZone: TZ })
}

export function initials(name?: string | null) {
  if (!name) return '?'
  return name
    .replace(/GmbH|AG|KG/g, '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')
}

export function maskPhone(p?: string | null) {
  if (!p) return ''
  const digits = p.replace(/\s/g, '')
  if (digits.length < 8) return p
  return `${digits.slice(0, 3)} ${digits.slice(3, 6)} •••• ${digits.slice(-4)}`
}

export function floorLabel(f?: number | null) {
  if (f === null || f === undefined) return '—'
  if (f === 0) return 'Ground floor'
  const suf = f === 1 ? 'st' : f === 2 ? 'nd' : f === 3 ? 'rd' : 'th'
  return `${f}${suf} floor`
}
