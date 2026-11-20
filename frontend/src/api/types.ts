// Types mirror docs/interfaces.md §4. Fields not pinned down by the contract are optional
// so the UI degrades gracefully if the backend omits them.

export type CaseStatus =
  | 'new'
  | 'awaiting_approval'
  | 'approval_pending'
  | 'rejected'
  | 'requested'
  | 'accepted'
  | 'scheduled'
  | 'in_progress'
  | 'completed'
  | 'invoiced'
  | 'closed'
  | 'declined'
  | 'slots_proposed'
  | 'partner_declined'
  | 'reopened'
  | 'awaiting_technician'
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
  error_code?: string | null
  error_label?: string | null
  technician?: TechnicianRef | null
  /** closed without a partner: self_help | caretaker | utility, with the avoided call-out cost */
  resolution?: string | null
  saving_eur?: number | null
  trade?: string | null
}

export interface TechnicianRef {
  tech_id: string
  name: string
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
  error_label?: string | null
  error_meaning?: string | null
  installed?: string | null
  last_service?: string | null
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
  consent_id?: string
  contact_id?: string
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
  unit_id?: string | null
  created_at?: string | null
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
  contact: string | null
  contact_id?: string | null
  text: string | null
  media: { document_id?: string; kind?: string; url?: string; filename?: string }[]
}

export interface Approval {
  required: boolean
  rule: string
  granted?: boolean
  granted_at?: string | null
  granted_by?: string | null
  amount_eur?: number | null
  /** approval_pending: Debye's proposal shown on the approval card */
  suggested_technician?: TechnicianRef | null
  suggested_slot?: Slot | null
  rejected_reason?: string | null
  /** backend: the partner the job would go to (case.partner is null while approval_pending) */
  partner?: PartnerRef | null
  rejected?: boolean
  reason?: string | null
  /** backend: staff member who rejected the job */
  rejected_by?: string | null
}

/** Debye's diagnosis before dispatching (KB: data/diagnosis/*.json). */
export interface DiagnosisQA {
  id?: string
  question?: string
  text?: string
  q?: string
  answer?: string
  answer_text?: string
  a?: string
}
export interface Diagnosis {
  cause_id: string
  label: string
  confidence?: number | null // 0..1 (or 0..100)
  reasoning?: string | null
  questions_asked?: (DiagnosisQA | string)[]
  outcome?: 'self_help' | 'caretaker' | 'technician' | 'utility' | 'emergency' | (string & {}) | null
  trade?: string | null
  estimated_cost_eur?: number | null
  estimated_saving_eur?: number | null
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
  summary?: string | null
  symptoms?: string | null
  proposed_slots?: Slot[]
  price_check?: unknown
  trade?: string | null
  diagnosis?: Diagnosis | null
  closed_at?: string | null
}

// ---- units ----
export interface UnitSummary {
  unit_id: string
  address: string | null
  floor?: number
  size_sqm?: number
  rooms?: number
  tenant?: { contact_id: string; name: string } | null
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
    energy_class?: string | null
    energy_valid_until?: string | null
  } | null
  unit: { id?: string; unit_id?: string; floor: number; size_sqm?: number; rooms?: number; meters?: { type: string; number: string }[] }
  assets: Asset[]
  tenant: { contact_id?: string; id?: string; name: string; phone_e164?: string; email?: string; move_in?: string } | null
  lease: { data?: { rent_cold_eur?: number; start?: string }; rent_cold_eur?: number; start?: string; [k: string]: unknown } | null
  documents: DocumentItem[]
  cases: CaseSummary[]
}

// ---- partner ----
export interface PartnerProfile {
  partner_id: string
  name: string
  category?: string
  rating?: number
  capabilities?: { trades?: string[]; brands_certified?: string[]; [k: string]: unknown }
  service_area?: { postcodes?: string[] }
  active?: boolean
  staff?: { contact_id: string; name: string }[]
  open_jobs?: number
  [k: string]: unknown
}

export interface JobSummary {
  case_id: string
  type?: string
  title: string
  status: CaseStatus
  priority: Priority
  address: string | null
  postcode?: string | null
  floor?: number | null
  asset?: Asset | null
  error_code?: string | null
  error_label?: string | null
  updated_at: string
  created_at?: string
  slot?: Slot | null
  technician?: TechnicianRef | null
  /** technician API: the slot the tenant picked, and true while awaiting_technician */
  chosen_slot?: Slot | null
  needs_confirmation?: boolean
}

/** GET /api/partner/{pid}/technicians */
export interface Technician extends TechnicianRef {
  skills: string[]
  free_slots: Slot[]
  phone_e164?: string | null
}

/** GET /api/tech/{tech_id} */
export interface TechProfile extends TechnicianRef {
  partner_id?: string
  partner_name?: string
}

export interface JobDetail extends JobSummary {
  summary?: string | null
  symptoms?: string | null
  description?: string | null
  photos: { document_id: string; url: string; filename: string }[]
  tenant?: { name?: string | null; phone?: string | null } | null
  consented_fields?: string[]
  proposed_slots: Slot[]
  confirmed_slot?: Slot | null
  documents: DocumentItem[]
  estimated_cost_eur?: number | null
  completion?: Record<string, unknown> | null
  price_check?: unknown
  events?: CaseEvent[]
  /** backend: who released the job, e.g. text "Approved by reltix staff (Anna Becker)" */
  approval?: JobApproval | null
}

export interface JobApproval {
  granted?: boolean
  granted_by?: string | null
  granted_at?: string | null
  text?: string | null
}

// ---- SSE ----
export interface StreamMessage {
  type: string
  case_id: string | null
  event: CaseEvent | Record<string, unknown> | null
}
