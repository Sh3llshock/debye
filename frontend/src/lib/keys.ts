import type { CaseEvent, ThreadMessage } from '../api/types'
export const eventKey = (e: CaseEvent) => e.id ?? `${e.ts}|${e.kind}|${e.summary}`
export const messageKey = (m: ThreadMessage) => `${m.ts}|${m.direction}|${m.text}`
