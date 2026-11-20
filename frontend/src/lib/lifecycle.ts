// The service line: the case lifecycle as stations, with a timestamp under each reached station.
import type { CaseEvent } from '../api/types'
import { t } from './i18n'

export interface Station {
  key: string
  label: string // English source; shown through t()
  events: string[] // event kinds that mark the station as reached
  tsFallback?: string[] // used only for the timestamp when the status says the station is reached
}

export const STAFF_STATIONS: Station[] = [
  { key: 'reported', label: 'Reported', events: ['case.created'] },
  { key: 'consent', label: 'Consent', events: ['consent.recorded'] },
  { key: 'dispatched', label: 'Dispatched', events: ['job.sent'] },
  // Booked = the technician confirmed the time the resident picked.
  { key: 'booked', label: 'Booked', events: ['technician.confirmed'], tsFallback: ['slot.confirmed'] },
  { key: 'done', label: 'Done', events: ['job.completed'] },
  { key: 'invoiced', label: 'Invoiced', events: ['invoice.checked'] },
  { key: 'closed', label: 'Closed', events: ['case.closed'] },
]

export const PARTNER_STATIONS: Station[] = [
  { key: 'new', label: 'New', events: ['job.sent'] },
  { key: 'accepted', label: 'Accepted', events: ['job.accepted'] },
  { key: 'times', label: 'Times sent', events: ['slot.proposed'] },
  { key: 'picked', label: 'Picked', events: ['slot.confirmed'] },
  { key: 'booked', label: 'Booked', events: ['technician.confirmed'], tsFallback: ['slot.confirmed'] },
  { key: 'done', label: 'Done', events: ['job.completed'] },
]

/** How many staff stations a status has reached (fallback when there are no events, e.g. list rows). */
const STAFF_REACHED: Record<string, number> = {
  new: 1, reopened: 1, partner_declined: 2, awaiting_approval: 2,
  requested: 3, accepted: 3, slots_proposed: 3, awaiting_technician: 3,
  scheduled: 4, in_progress: 4,
  completed: 5, invoiced: 6, closed: 7,
}
const PARTNER_REACHED: Record<string, number> = {
  requested: 1, accepted: 2, reopened: 2, slots_proposed: 3, awaiting_technician: 4, scheduled: 5, in_progress: 5,
  completed: 6, invoiced: 6, closed: 6, declined: 1, partner_declined: 1,
}

/** What is happening right now, in words (English source; shown through t()). */
export const STATUS_TEXT: Record<string, string> = {
  new: 'Reported, Debye is triaging',
  awaiting_approval: 'Needs your decision',
  requested: 'Sent to partner',
  accepted: 'Accepted by partner',
  slots_proposed: 'Times offered to resident',
  awaiting_technician: 'Resident picked, technician to confirm',
  scheduled: 'Visit booked',
  in_progress: 'Partner on site',
  completed: 'Work done, checking invoice',
  invoiced: 'Invoiced',
  closed: 'Closed',
  partner_declined: 'Partner declined, finding another',
  reopened: 'Reopened',
  declined: 'You declined',
}
export const statusText = (s: string) => (STATUS_TEXT[s] ? t(STATUS_TEXT[s]) : s.replace(/_/g, ' '))

export interface LineState {
  stations: { label: string; reached: boolean; ts?: string }[]
  reached: number // count of reached stations; the last reached one is "current"
}

export function lineState(stations: Station[], status: string, events: CaseEvent[] = [], partner = false): LineState {
  const byStatus = (partner ? PARTNER_REACHED : STAFF_REACHED)[status] ?? 0
  const find = (kinds?: string[]) => (kinds ? events.find((e) => kinds.includes(e.kind))?.ts : undefined)
  const ts = stations.map((s) => find(s.events))
  // A station counts as reached if its event exists or the status says we are past it.
  let reached = byStatus
  ts.forEach((x, i) => {
    if (x && i + 1 > reached) reached = i + 1
  })
  return {
    stations: stations.map((s, i) => ({ label: t(s.label), reached: i < reached, ts: ts[i] ?? (i < reached ? find(s.tsFallback) : undefined) })),
    reached,
  }
}
