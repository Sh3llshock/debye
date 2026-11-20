// The service line: the case lifecycle as stations, with a timestamp under each reached station.
import type { CaseEvent } from '../api/types'

export interface Station {
  key: string
  label: string
  events: string[] // event kinds that mark the station as reached
}

export const STAFF_STATIONS: Station[] = [
  { key: 'reported', label: 'Reported', events: ['case.created'] },
  { key: 'consent', label: 'Consent', events: ['consent.recorded'] },
  { key: 'dispatched', label: 'Dispatched', events: ['job.sent'] },
  { key: 'booked', label: 'Booked', events: ['slot.confirmed'] },
  { key: 'done', label: 'Done', events: ['job.completed'] },
  { key: 'invoiced', label: 'Invoiced', events: ['invoice.checked'] },
  { key: 'closed', label: 'Closed', events: ['case.closed'] },
]

export const PARTNER_STATIONS: Station[] = [
  { key: 'new', label: 'New', events: ['job.sent'] },
  { key: 'accepted', label: 'Accepted', events: ['job.accepted'] },
  { key: 'times', label: 'Times sent', events: ['slot.proposed'] },
  { key: 'booked', label: 'Booked', events: ['slot.confirmed'] },
  { key: 'done', label: 'Done', events: ['job.completed'] },
]

/** How many staff stations a status has reached (fallback when there are no events, e.g. list rows). */
const STAFF_REACHED: Record<string, number> = {
  new: 1, reopened: 1, partner_declined: 2, awaiting_approval: 2,
  requested: 3, accepted: 3, slots_proposed: 3,
  scheduled: 4, in_progress: 4,
  completed: 5, invoiced: 6, closed: 7,
}
const PARTNER_REACHED: Record<string, number> = {
  requested: 1, accepted: 2, reopened: 2, slots_proposed: 3, scheduled: 4, in_progress: 4,
  completed: 5, invoiced: 5, closed: 5, declined: 1, partner_declined: 1,
}

/** What is happening right now, in words (shown under the compact line and the current station). */
export const STATUS_TEXT: Record<string, string> = {
  new: 'Reported, Debye is triaging',
  awaiting_approval: 'Needs your decision',
  requested: 'Sent to partner',
  accepted: 'Accepted by partner',
  slots_proposed: 'Times offered to resident',
  scheduled: 'Visit booked',
  in_progress: 'Partner on site',
  completed: 'Work done, checking invoice',
  invoiced: 'Invoiced',
  closed: 'Closed',
  partner_declined: 'Partner declined, finding another',
  reopened: 'Reopened',
  declined: 'You declined',
}

export interface LineState {
  stations: { label: string; reached: boolean; ts?: string }[]
  reached: number // count of reached stations; the last reached one is "current"
}

export function lineState(stations: Station[], status: string, events: CaseEvent[] = [], partner = false): LineState {
  const byStatus = (partner ? PARTNER_REACHED : STAFF_REACHED)[status] ?? 0
  const ts = stations.map((s) => events.find((e) => s.events.includes(e.kind))?.ts)
  // A station counts as reached if its event exists or the status says we are past it.
  let reached = byStatus
  ts.forEach((t, i) => {
    if (t && i + 1 > reached) reached = i + 1
  })
  return { stations: stations.map((s, i) => ({ label: s.label, reached: i < reached, ts: ts[i] })), reached }
}
