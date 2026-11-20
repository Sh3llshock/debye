import type { CaseDetail, CaseEvent, StreamMessage } from '../api/types'
import { eventKey, messageKey } from './keys'

function isCaseEvent(x: unknown): x is CaseEvent {
  return !!x && typeof x === 'object' && 'ts' in x && 'kind' in x && 'summary' in x
}

/** Optimistically patch a case with a stream message (the follow-up refetch makes it exact). */
export function patchCase(c: CaseDetail, m: StreamMessage): CaseDetail {
  if (m.case_id !== c.case_id || !isCaseEvent(m.event)) return c
  const ev = m.event
  if (ev.kind === 'message.in' || ev.kind === 'message.out' || m.type === 'message.in' || m.type === 'message.out') {
    const d = (ev.data ?? {}) as Record<string, unknown>
    const msg = {
      ts: (d.ts as string) ?? ev.ts,
      direction: ((d.direction as string) ?? (m.type === 'message.in' ? 'in' : 'out')) as 'in' | 'out',
      contact: (d.contact as string) ?? '',
      text: (d.text as string) ?? ev.summary,
      media: (d.media as []) ?? [],
    }
    if (c.messages.some((x) => messageKey(x) === messageKey(msg))) return c
    return { ...c, messages: [...c.messages, msg], updated_at: ev.ts }
  }
  if (c.events.some((x) => eventKey(x) === eventKey(ev))) return c
  return { ...c, events: [...c.events, ev], updated_at: ev.ts }
}
