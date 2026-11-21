// Tenant portal API (backend/app/channels/web.py, /api/tenant/*).
const TOKEN_KEY = 'debye-tenant-token'

export interface TContact {
  contact_id: string
  name: string
  first_name: string
  email: string | null
  phone: string | null
  language: string
  unit_id: string | null
}
export interface TAsset {
  asset_id: string
  type: string
  make: string | null
  model: string | null
  installed: string | null
  last_service: string | null
  central: boolean
}
export interface THome {
  unit_id: string
  floor: number | null
  address: string | null
  postcode: string | null
  city: string | null
  landlord: string | null
  assets: TAsset[]
}
export interface TOption {
  id: string
  title: string
}
export interface TPending {
  question: string | null
  options: TOption[]
}
export interface TMe {
  contact: TContact
  home: THome | null
  conversation: { case_id: string | null; step: string; pending: TPending | null }
}
export interface TCase {
  case_id: string
  title: string
  status: string
  priority: string
  type: string
  created_at: string
  updated_at: string
  closed_at: string | null
  closed: boolean
  resolution: string | null
  error_code: string | null
  error_label: string | null
  partner_name: string | null
  technician_name: string | null
  slot: { start: string; end: string } | null
  approval: { required: boolean; granted: boolean; rejected: boolean }
  diagnosis: { label: string | null; confidence: number | null; outcome: string | null } | null
}
export interface TDocument {
  document_id: string
  kind: string
  filename: string
  mime: string
  url: string
}
export interface TCaseDetail extends TCase {
  summary: string
  asset: { type: string; make: string | null; model: string | null; last_service: string | null } | null
  proposed_slots: { start: string; end: string; label?: string }[]
  documents: TDocument[]
  completion: { notes: string | null } | null
  events: { ts: string; actor: string; kind: string }[]
  first_channel: string | null
}
export interface TMessage {
  id: string
  ts: string
  direction: 'in' | 'out'
  channel: string
  text: string | null
  options: TOption[]
  list_button: string | null
  media: { document_id: string; url: string; mime: string; kind: string }[]
}
export interface THistory {
  case_id: string | null
  current: boolean
  messages: TMessage[]
  pending: TPending | null
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}
export function setToken(t: string | null) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* private mode */
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const tok = getToken()
  if (tok) headers.set('Authorization', `Bearer ${tok}`)
  const r = await fetch(`/api/tenant${path}`, { ...init, headers })
  if (!r.ok) {
    let msg = r.statusText
    try {
      msg = (await r.json()).detail ?? msg
    } catch {
      /* not JSON */
    }
    throw new ApiError(r.status, String(msg))
  }
  return r.json() as Promise<T>
}

export const api = {
  login: (login: string, password: string) =>
    req<{ token: string; contact: TContact }>('/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login, password }),
    }),
  me: () => req<TMe>('/me'),
  cases: () => req<TCase[]>('/cases'),
  case: (id: string) => req<TCaseDetail>(`/cases/${encodeURIComponent(id)}`),
  messages: (caseId?: string | null) =>
    req<THistory>(caseId ? `/messages?case_id=${encodeURIComponent(caseId)}` : '/messages'),
  send: (m: { text?: string; buttonId?: string; buttonTitle?: string; file?: File | null; newCase?: boolean }) => {
    const fd = new FormData()
    if (m.newCase) fd.set('new_case', 'true')
    if (m.text) fd.set('text', m.text)
    if (m.buttonId) fd.set('button_id', m.buttonId)
    if (m.buttonTitle) fd.set('button_title', m.buttonTitle)
    if (m.file) fd.set('file', m.file)
    return req<{ ok: boolean; id: string }>('/messages', { method: 'POST', body: fd })
  },
}
