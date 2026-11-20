// Types mirror docs/interfaces.md §4. Fields not pinned down by the contract are optional
// so the UI degrades gracefully if the backend omits them.

export type CaseStatus =
  | 'new'
  | 'awaiting_approval'
  | 'requested'
  | 'accepted'
  | 'scheduled'
  | 'in_progress'
  | 'completed'
  | 'invoiced'
  | 'closed'
  | 'declined'
  | (string & {})

export type Priority = 'urgent' | 'high' | 'normal' | 'low' | (string & {})
export type Actor = 'debye' | 'tenant' | 'partner' | 'staff' | 'pm' | 'system' | (string & {})

export interface PartnerRef {
  partner_id: string
  name: string
}

export interface CaseSummary {
  case_id: string
  type: string
  title: string
  status: CaseStatus
  priority: Priority
  unit_id: string
  address: string
  partner: PartnerRef | null
  updated_at: string
  created_at?: string
}

export interface Reporter {
  contact_id: string
  name: string
  unit_id: string
  relation: 'reporter' | 'affected' | (string & {})
}

export interface Asset {
  asset_id?: string
  id?: string
  type?: string
  make: string
  model: string
  error_code?: string | null
  installed?: string
  last_service?: string
}

export interface Slot {
  start: string
  end: string
  label?: string
}

export interface ZeroForms {
  prefilled: string[]
  tenant_inputs: string[]
}

export interface RankingEntry {
  partner_id: string
  name: string
  score: number
  reasons: string[]
}

export interface Consent {
  partner_id: string
  data_shared: string[]
  given_at: string
  channel: string
  purpose: string
  revoked_at?: string | null
}

export interface DocumentItem {
  document_id: string
  kind: 'photo' | 'invoice' | 'report' | 'contract' | (string & {})
  filename: string
  url: string
  mime?: string
  extracted?: Record<string, unknown> | null
  case_id?: string | null
  created_at?: string
}

export interface CaseEvent {
  id?: string
  ts: string
  actor: Actor
  kind: string
  summary: string
  data?: Record<string, unknown> | null
}

export interface ThreadMessage {
  ts: string
  direction: 'in' | 'out'
  contact: string
  text: string
  media: { kind?: string; url?: string; filename?: string }[] | string[]
}

export interface Approval {
  required: boolean
  rule: string
  granted_at?: string | null
  granted_by?: string | null
  amount_eur?: number | null
}

export interface CaseDetail extends CaseSummary {
  reporters: Reporter[]
  asset: Asset | null
  cost_bearer: string | null
  estimated_cost_eur: number | null
  approval: Approval | null
  slot: Slot | null
  zero_forms: ZeroForms | null
  ranking: RankingEntry[]
  consents: Consent[]
  documents: DocumentItem[]
  events: CaseEvent[]
  messages: ThreadMessage[]
  result: Record<string, unknown> | null
}

// ---- units ----
export interface UnitSummary {
  unit_id: string
  address: string
  floor?: number
  tenant?: string | null
  open_cases?: number
}

export interface UnitDetail {
  property: {
    id?: string
    address: string
    postcode?: string
    city?: string
    building_year?: number
    heating_type?: string
    heating_central?: boolean
    energy_certificate?: { class: string; valid_until: string }
    energy_class?: string
  }
  unit: { id?: string; unit_id?: string; floor: number; size_sqm?: number; rooms?: number; meters?: { type: string; number: string }[] }
  assets: Asset[]
  tenant: { contact_id?: string; id?: string; name: string; phone_e164?: string; email?: string; move_in?: string } | null
  lease: { rent_cold_eur?: number; start?: string; [k: string]: unknown } | null
  documents: DocumentItem[]
  cases: CaseSummary[]
}

// ---- partner ----
export interface PartnerProfile {
  partner_id: string
  name: string
  category?: string
  rating?: number
  [k: string]: unknown
}

export interface JobSummary {
  case_id: string
  title: string
  status: CaseStatus
  priority: Priority
  address: string
  updated_at: string
  slot?: Slot | null
}

export interface JobDetail extends JobSummary {
  type?: string
  floor?: number | null
  asset?: Asset | null
  error_code?: string | null
  description?: string | null
  photos: DocumentItem[]
  tenant_contact?: { name?: string; phone?: string } | null
  consented_fields?: string[]
  proposed_slots: Slot[]
  confirmed_slot?: Slot | null
  documents: DocumentItem[]
  estimated_cost_eur?: number | null
}

// ---- SSE ----
export interface StreamMessage {
  type: string
  case_id: string | null
  event: CaseEvent | Record<string, unknown> | null
}
