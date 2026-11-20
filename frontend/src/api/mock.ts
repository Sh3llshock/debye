// In-browser fake backend for VITE_USE_FIXTURES=1. Holds state in memory, implements the
// same endpoints as docs/interfaces.md §4 and emits the same SSE messages, so the whole
// golden path (new → requested → accepted → scheduled → completed → closed) can be demoed
// without the backend. `mockAdvance()` plays the resident (WhatsApp) side step by step.

import type {
  CaseDetail,
  CaseEvent,
  CaseSummary,
  DocumentItem,
  JobDetail,
  JobSummary,
  PartnerProfile,
  Slot,
  StreamMessage,
  TechProfile,
  Technician,
  ThreadMessage,
  UnitDetail,
  UnitSummary,
} from './types'

const ADDRESS = 'Musterstraße 12, 52062 Aachen'
const SCHMIDT = { partner_id: 'heizung-schmidt', name: 'Heizung Schmidt GmbH' }

const partners: Record<string, PartnerProfile> = {
  'heizung-schmidt': { partner_id: 'heizung-schmidt', name: 'Heizung Schmidt GmbH', category: 'repair.heating', rating: 4.8, staff: [{ contact_id: 'c_301', name: 'Tom Schmidt' }] },
  'waerme-wagner': { partner_id: 'waerme-wagner', name: 'Wärme Wagner', category: 'repair.heating', rating: 4.6 },
  'heiztechnik-gruen': { partner_id: 'heiztechnik-gruen', name: 'Heiztechnik Grün', category: 'repair.heating', rating: 4.1 },
}

// ---------- technicians (dispatcher + technician pages) ----------
const TECHS: Record<string, { tech_id: string; name: string; partner_id: string; skills: string[]; busy: string[] }> = {
  tech_tom: { tech_id: 'tech_tom', name: 'Tom Schmidt', partner_id: 'heizung-schmidt', skills: ['Vaillant', 'gas boilers', 'heat pumps'], busy: ['1-14:00', '2-08:00', '3-10:00'] },
  tech_ali: { tech_id: 'tech_ali', name: 'Ali Yilmaz', partner_id: 'heizung-schmidt', skills: ['Buderus', 'gas boilers'], busy: ['1-08:00', '1-10:00', '2-14:00'] },
}
const WINDOWS: [string, string][] = [['08:00', '10:00'], ['10:00', '12:00'], ['14:00', '16:00']]
function berlinDay(i: number) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Berlin' }).format(new Date(Date.now() + i * 86400_000))
}
/** Free slots for the next working days, relative to today, minus each technician's busy windows. */
function freeSlots(techId: string) {
  const t = TECHS[techId]
  const out: Slot[] = []
  for (let i = 1, n = 0; n < 4 && i < 10; i++) {
    const d = new Date(Date.now() + i * 86400_000)
    if (new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Berlin', weekday: 'short' }).format(d) === 'Sun') continue
    n++
    for (const [a, b] of WINDOWS) {
      if (t.busy.includes(`${n}-${a}`)) continue
      out.push({ start: `${berlinDay(i)}T${a}:00+01:00`, end: `${berlinDay(i)}T${b}:00+01:00` })
    }
  }
  return out
}

// ---------- clock ----------
function now(): string {
  const d = new Date(Date.UTC(2026, 10, 20 + state.dayOffset, 17, 12 + state.minute))
  state.minute += 1
  return berlin(d)
}
function berlin(d: Date): string {
  // Europe/Berlin is UTC+1 in November
  const local = new Date(d.getTime() + 3600_000)
  return local.toISOString().replace(/\.\d{3}Z$/, '+01:00')
}
const at = (day: number, h: number, m = 0) => berlin(new Date(Date.UTC(2026, 10, day, h - 1, m)))

// ---------- state ----------
type State = {
  cases: Record<string, CaseDetail>
  docSeq: number
  unitDocs: DocumentItem[]
  pendingSlots: Record<string, Slot[]>
  techOf?: Record<string, string>
  dayOffset: number
  minute: number
}
const STORE_KEY = 'debye-fixtures-v3'
let state: State = loadState() ?? initialState()

function loadState(): State | null {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    return raw ? (JSON.parse(raw) as State) : null
  } catch {
    return null
  }
}
function saveState() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(state))
  } catch {
    /* private mode: state stays per tab */
  }
}

function initialState(): State {
  const approvalCase: CaseDetail = {
    case_id: 'case_0002',
    type: 'repair.plumbing',
    title: 'Leaking riser pipe in basement',
    status: 'awaiting_approval',
    priority: 'high',
    unit_id: 'unit_2a',
    address: ADDRESS,
    partner: { partner_id: 'waerme-wagner', name: 'Wärme Wagner' },
    updated_at: at(20, 16, 40),
    created_at: at(20, 16, 2),
    reporters: [{ contact_id: 'c_203', name: 'Jonas Weber', unit_id: 'unit_2a', relation: 'reporter' }],
    asset: null,
    cost_bearer: 'landlord',
    estimated_cost_eur: 620,
    approval: { required: true, rule: 'needs approval: €620 > €500 framework limit', amount_eur: 620 },
    slot: null,
    zero_forms: { prefilled: ['address', 'unit', 'floor', 'tenant name', 'phone', 'lease', 'owner'], tenant_inputs: ['photo', 'tap: consent'] },
    ranking: [{ partner_id: 'waerme-wagner', name: 'Wärme Wagner', score: 0.81, reasons: ['Framework agreement', 'Free Monday 9–12'] }],
    consents: [{ partner_id: 'waerme-wagner', data_shared: ['name', 'phone', 'address', 'photos'], given_at: at(20, 16, 20), channel: 'whatsapp', purpose: 'plumbing repair visit' }],
    documents: [],
    events: [
      { ts: at(20, 16, 2), actor: 'debye', kind: 'case.created', summary: "Case opened from Jonas's photo of a wet basement wall" },
      { ts: at(20, 16, 20), actor: 'tenant', kind: 'consent.recorded', summary: 'Jonas shared name, phone, address, photos with Wärme Wagner' },
      { ts: at(20, 16, 40), actor: 'system', kind: 'approval.required', summary: 'Estimate €620 is above the €500 limit — waiting for a property manager' },
    ],
    messages: [
      { ts: at(20, 16, 1), direction: 'in', contact: 'Jonas Weber', text: 'Im Keller ist die Wand nass, da tropft es aus dem Rohr.', media: [{ kind: 'photo' }] },
      { ts: at(20, 16, 3), direction: 'out', contact: 'Jonas Weber', text: 'Danke Jonas! Ich habe einen Fall angelegt und kümmere mich um einen Installateur.', media: [] },
    ],
    result: null,
  }
  return { cases: { case_0002: approvalCase }, docSeq: 1, unitDocs: [], pendingSlots: {}, dayOffset: 0, minute: 0 }
}

// ---------- event bus ----------
type Listener = (m: StreamMessage) => void
const listeners = new Set<Listener>()
export function mockSubscribe(fn: Listener): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}
// Tabs share one fake backend: state lives in localStorage, events go over a BroadcastChannel.
const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('debye-fixtures') : null
channel?.addEventListener('message', (e) => {
  state = loadState() ?? state
  listeners.forEach((l) => l(e.data as StreamMessage))
})
function emit(m: StreamMessage) {
  saveState()
  channel?.postMessage(m)
  // async like a real stream
  setTimeout(() => listeners.forEach((l) => l(m)), 0)
}

function addEvent(c: CaseDetail, actor: string, kind: string, summary: string, data?: Record<string, unknown>) {
  const ev: CaseEvent = { id: `ev_${Math.random().toString(36).slice(2, 8)}`, ts: now(), actor, kind, summary, data: data ?? null }
  c.events.push(ev)
  c.updated_at = ev.ts
  emit({ type: kind, case_id: c.case_id, event: ev })
}
function addMessage(c: CaseDetail, direction: 'in' | 'out', contact: string, text: string, media: ThreadMessage['media'] = []) {
  const m: ThreadMessage = { ts: now(), direction, contact, text, media }
  c.messages.push(m)
  emit({ type: direction === 'in' ? 'message.in' : 'message.out', case_id: c.case_id, event: { ts: m.ts, actor: direction === 'in' ? 'tenant' : 'debye', kind: `message.${direction}`, summary: text, data: m as unknown as Record<string, unknown> } })
}
function newDoc(c: CaseDetail, kind: string, filename: string, extracted: Record<string, unknown> | null = null): DocumentItem {
  const id = `doc_${String(state.docSeq++).padStart(4, '0')}`
  const url = DEMO_FILES[filename] ?? `/files/${id}`
  const doc: DocumentItem = { document_id: id, kind, filename, url, extracted, case_id: c.case_id, unit_id: c.unit_id, created_at: now() }
  c.documents.push(doc)
  return doc
}

// Demo media from data/demo (copied to public/demo).
const DEMO_FILES: Record<string, string> = {
  'boiler_display_F28.jpg': '/demo-media/boiler_display_F28.jpg',
  'after_repair.jpg': '/demo-media/repair_done.jpg',
  'RE-2026-1187.pdf': '/demo-media/invoice_RE-2026-1187.pdf',
}

// ---------- golden path, resident side ----------
const SLOTS: Slot[] = [
  { start: at(21, 8), end: at(21, 10), label: 'Tomorrow 8–10' },
  { start: at(21, 14), end: at(21, 16), label: 'Tomorrow 14–16' },
  { start: at(22, 10), end: at(22, 12), label: 'Sun 10–12' },
]

function heating(): CaseDetail | undefined {
  return state.cases['case_0001']
}

export interface MockStep {
  label: string
  run: () => void
  ready: () => boolean
}

export const mockSteps: MockStep[] = [
  {
    label: 'Luka sends voice note + photo',
    ready: () => !heating(),
    run: () => {
      const c: CaseDetail = {
        case_id: 'case_0001',
        type: 'repair.heating',
        title: 'No heating – central boiler',
        status: 'new',
        priority: 'urgent',
        unit_id: 'unit_4b',
        address: ADDRESS,
        partner: null,
        updated_at: now(),
        created_at: now(),
        reporters: [{ contact_id: 'c_202', name: 'Luka', unit_id: 'unit_4b', relation: 'reporter' }],
        asset: { asset_id: 'asset_boiler_1', type: 'gas_boiler', make: 'Vaillant', model: 'ecoTEC plus VC 206/5-5', error_code: 'F.28', error_meaning: 'Ignition failed at start-up (no flame detected)' },
        summary: 'Radiators cold in the whole building since this morning (unit 2a reports the same). Likely ignition fault at the central boiler.',
        cost_bearer: 'landlord',
        estimated_cost_eur: 250,
        approval: { required: false, rule: 'auto-approved: €250 < €500 framework limit' },
        slot: null,
        zero_forms: { prefilled: ['address', 'unit', 'floor', 'tenant name', 'phone', 'lease', 'boiler make', 'boiler model', 'last service', 'owner', 'cost bearer', 'framework contract', 'error code table', 'heating type'], tenant_inputs: ['voice note'] },
        ranking: [],
        consents: [],
        documents: [],
        events: [],
        messages: [],
        result: null,
      }
      state.cases[c.case_id] = c
      const photo = newDoc(c, 'photo', 'boiler_display_F28.jpg')
      addMessage(c, 'in', 'Luka', '„Hallo, die Heizung ist komplett kalt seit heute Morgen.“', [{ kind: 'audio' }, { document_id: photo.document_id, kind: 'photo', url: photo.url }])
      addEvent(c, 'debye', 'case.created', "Case opened from Luka's voice note — photo shows error F.28 (ignition failed)")
      addMessage(c, 'out', 'Luka', 'Oh nein, das tut mir leid, Luka! Sind alle Heizkörper kalt oder nur einer?', [])
    },
  },
  {
    label: 'Luka taps “Überall kalt”',
    ready: () => heating()?.status === 'new' && !heating()!.zero_forms!.tenant_inputs.includes('tap: Überall kalt'),
    run: () => {
      const c = heating()!
      addMessage(c, 'in', 'Luka', 'Überall kalt')
      c.zero_forms!.tenant_inputs.push('tap: Überall kalt')
      addEvent(c, 'tenant', 'case.updated', 'All radiators cold — central boiler, priority urgent')
    },
  },
  {
    label: 'Neighbour Jonas reports the same',
    ready: () => !!heating() && heating()!.reporters.length === 1,
    run: () => {
      const c = heating()!
      c.reporters.push({ contact_id: 'c_203', name: 'Jonas Weber', unit_id: 'unit_2a', relation: 'affected' })
      addEvent(c, 'debye', 'case.linked_reporter', 'Jonas Weber (2a) reported cold radiators — merged into this case, no duplicate opened')
    },
  },
  {
    label: 'Debye ranks partners',
    ready: () => !!heating() && heating()!.ranking.length === 0,
    run: () => {
      const c = heating()!
      c.ranking = [
        { partner_id: 'heizung-schmidt', name: 'Heizung Schmidt GmbH', score: 0.86, reasons: ['Vaillant-certified', 'Free tomorrow 8–10', 'Framework agreement'] },
        { partner_id: 'waerme-wagner', name: 'Wärme Wagner', score: 0.71, reasons: ['Vaillant-certified', 'Fully booked until Tue'] },
        { partner_id: 'heiztechnik-gruen', name: 'Heiztechnik Grün', score: 0.54, reasons: ['Cheapest', 'Not Vaillant-certified'] },
      ]
      addEvent(c, 'debye', 'partner.ranked', 'Top match: Heizung Schmidt (0.86) — Vaillant-certified, free tomorrow')
      addMessage(c, 'out', 'Luka', 'Heizung Schmidt kann morgen kommen. Darf ich Name, Telefon, Adresse und Fotos teilen?')
    },
  },
  {
    label: 'Luka taps consent',
    ready: () => !!heating() && heating()!.ranking.length > 0 && heating()!.consents.length === 0,
    run: () => {
      const c = heating()!
      addMessage(c, 'in', 'Luka', 'Ja, teilen')
      c.zero_forms!.tenant_inputs.push('tap: consent')
      c.consents.push({ contact_id: 'c_202', partner_id: 'heizung-schmidt', data_shared: ['name', 'phone', 'address', 'unit_floor', 'photos'], given_at: now(), channel: 'whatsapp', purpose: 'heating repair visit' })
      addEvent(c, 'tenant', 'consent.recorded', 'Luka shared name, phone, address, floor, photos with Heizung Schmidt')
      addEvent(c, 'system', 'approval.granted', 'Auto-approved: estimate €250 is within the €500 framework limit')
      c.partner = SCHMIDT
      c.status = 'requested'
      addEvent(c, 'debye', 'job.sent', 'Job sent to Heizung Schmidt GmbH')
    },
  },
  {
    label: '(partner page) Accept + propose slots',
    ready: () => false,
    run: () => {},
  },
  {
    label: 'Luka picks a slot',
    ready: () => !!heating() && heating()!.status === 'slots_proposed' && !!state.pendingSlots['case_0001']?.length,
    run: () => {
      const c = heating()!
      const s = state.pendingSlots['case_0001'][0]
      addMessage(c, 'in', 'Luka', s.label ?? fmtSlot(s))
      c.zero_forms!.tenant_inputs.push('tap: slot')
      c.slot = { start: s.start, end: s.end }
      c.status = 'awaiting_technician'
      addEvent(c, 'tenant', 'slot.confirmed', `Luka picked ${s.label ?? fmtSlot(s)}, waiting for ${c.technician?.name ?? 'the technician'} to confirm`)
      addMessage(c, 'out', 'Luka', `Danke! Ich frage kurz bei ${c.technician?.name ?? 'Heizung Schmidt'} nach und bestätige dir den Termin gleich.`)
    },
  },
  {
    label: '(technician page) Confirm the visit',
    ready: () => false,
    run: () => {},
  },
  {
    label: '(partner page) Mark as done',
    ready: () => false,
    run: () => {},
  },
  {
    label: 'Luka confirms: warm again',
    ready: () => !!heating() && (heating()!.status === 'completed' || heating()!.status === 'invoiced'),
    run: () => {
      const c = heating()!
      addMessage(c, 'out', 'Luka', 'Heizung Schmidt ist fertig. Ist es wieder warm?')
      addMessage(c, 'in', 'Luka', '👍 Ja, warm!')
      c.zero_forms!.tenant_inputs.push('tap: fixed')
      const inv = c.documents.find((d) => d.kind === 'invoice')
      c.status = 'closed'
      c.result = {
        unit_id: 'unit_4b',
        contact_id: 'c_202',
        service_job: {
          partner: 'Heizung Schmidt GmbH',
          category: 'repair.heating',
          case_id: 'case_0001',
          status: 'closed',
          visit: c.slot,
          resolution: 'Ignition electrode replaced, boiler restarted',
          invoice: { number: 'RE-2026-1187', gross_eur: 237.41, document_id: inv?.document_id ?? null, price_check: 'ok' },
          affected_units: c.reporters.map((r) => r.unit_id),
          consent: { data_shared: c.consents[0]?.data_shared, given_at: c.consents[0]?.given_at, channel: 'whatsapp' },
        },
      }
      const report = newDoc(c, 'report', 'service_report_case_0001.json')
      state.unitDocs.push(...c.documents.filter((d) => d.kind !== 'photo'), report)
      addEvent(c, 'debye', 'case.closed', 'Luka confirmed it is warm again — result written to unit 4b')
    },
  },
]


function fmtSlot(s: Slot) {
  const d = new Date(s.start)
  return `${d.toLocaleDateString('de-DE', { weekday: 'short' })} ${d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })}`
}

/** Runs the next resident-side step that is ready. Returns its label or null. */
export function mockAdvance(): string | null {
  const step = mockSteps.find((s) => s.ready())
  if (!step) return null
  step.run()
  return step.label
}
export function mockNextLabel(): string | null {
  return mockSteps.find((s) => s.ready())?.label ?? null
}

// ---------- endpoints ----------
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))
const summary = (c: CaseDetail): CaseSummary => ({
  case_id: c.case_id, type: c.type, title: c.title, status: c.status, priority: c.priority,
  unit_id: c.unit_id, address: c.address, partner: c.partner, updated_at: c.updated_at, created_at: c.created_at,
  error_code: c.asset?.error_code ?? null, technician: c.technician ?? null,
})

function jobFor(partnerId: string, c: CaseDetail): JobDetail {
  const consent = c.consents.find((k) => k.partner_id === partnerId)
  const fields = consent?.data_shared ?? []
  return {
    case_id: c.case_id,
    title: c.title,
    type: c.type,
    status: c.status,
    priority: c.priority,
    address: fields.includes('address') ? c.address.split(',')[0] : null,
    postcode: '52062',
    floor: 2,
    asset: c.asset ? { ...c.asset, installed: '2014-09-15', last_service: '2025-10-08' } : null,
    error_code: c.asset?.error_code ?? null,
    summary: c.summary,
    photos: c.documents.filter((d) => d.kind === 'photo' && (fields.includes('photos') || d.filename.startsWith('after_'))).map((d) => ({ document_id: d.document_id, url: d.url, filename: d.filename })),
    tenant: fields.includes('name') ? { name: 'Luka', phone: fields.includes('phone') ? '+491510000001' : null } : null,
    consented_fields: fields,
    proposed_slots: state.pendingSlots[c.case_id] ?? [],
    confirmed_slot: c.slot,
    slot: c.slot,
    documents: c.documents.filter((d) => d.kind === 'invoice' || d.kind === 'report'),
    price_check: c.price_check ?? null,
    estimated_cost_eur: c.estimated_cost_eur,
    updated_at: c.updated_at,
    created_at: c.created_at,
    events: c.events.filter((e) => /^(job|slot|technician|invoice|case\.closed)/.test(e.kind)),
    technician: c.technician ?? null,
  }
}
const jobSummary = (j: JobDetail): JobSummary => ({
  case_id: j.case_id, title: j.title, status: j.status, priority: j.priority, address: j.address, floor: j.floor,
  error_code: j.error_code, updated_at: j.updated_at, slot: j.slot, technician: j.technician,
})

function partnerCase(partnerId: string, caseId: string): CaseDetail {
  const c = state.cases[caseId]
  if (!c || c.partner?.partner_id !== partnerId || c.status === 'awaiting_approval') throw new Error('Job not found')
  return c
}

const delay = (ms = 150) => new Promise((r) => setTimeout(r, ms))

export const mockApi = {
  async staffUnits(): Promise<UnitSummary[]> {
    await delay()
    return [
      { unit_id: 'unit_4b', address: ADDRESS, floor: 2, size_sqm: 68, rooms: 3, tenant: { contact_id: 'c_202', name: 'Luka' }, open_cases: Object.values(state.cases).filter((c) => c.unit_id === 'unit_4b' && c.status !== 'closed').length },
      { unit_id: 'unit_2a', address: ADDRESS, floor: 1, size_sqm: 54, rooms: 2, tenant: { contact_id: 'c_203', name: 'Jonas Weber' }, open_cases: Object.values(state.cases).filter((c) => c.unit_id === 'unit_2a' && c.status !== 'closed').length },
    ]
  },
  async staffUnit(unitId: string): Promise<UnitDetail> {
    await delay()
    const is4b = unitId === 'unit_4b'
    if (!is4b && unitId !== 'unit_2a') throw new Error('Unit not found')
    return clone({
      property: { id: 'prop_12', address: ADDRESS, postcode: '52062', city: 'Aachen', building_year: 1972, heating_type: 'gas central heating', heating_central: true, energy_class: 'E', energy_valid_until: '2029-03-31' },
      unit: is4b
        ? { id: 'unit_4b', floor: 2, size_sqm: 68, rooms: 3, meters: [{ type: 'electricity', number: '1ESY1160123456' }, { type: 'gas', number: '7GMT0042001234' }] }
        : { id: 'unit_2a', floor: 1, size_sqm: 54, rooms: 2, meters: [{ type: 'electricity', number: '1ESY1160123401' }] },
      assets: [{ asset_id: 'asset_boiler_1', type: 'gas_boiler', make: 'Vaillant', model: 'ecoTEC plus VC 206/5-5', installed: '2014-09-15', last_service: '2025-10-08' }],
      tenant: is4b ? { contact_id: 'c_202', name: 'Luka', email: 'luka@example.com', move_in: '2026-12-01' } : { contact_id: 'c_203', name: 'Jonas Weber', email: 'jonas@example.com', move_in: '2021-04-01' },
      lease: { id: `ct_lease_${unitId}`, type: 'lease', data: is4b ? { rent_cold_eur: 780, start: '2026-12-01' } : { rent_cold_eur: 610, start: '2021-04-01' } },
      documents: [
        ...(is4b ? [...state.unitDocs].reverse() : []),
        { document_id: 'doc_lease', kind: 'contract', filename: `Lease ${unitId.replace('unit_', '')}.pdf`, url: '#', created_at: '2026-11-01T10:00:00+01:00' },
        { document_id: 'doc_energy', kind: 'contract', filename: 'Energy certificate.pdf', url: '#', created_at: '2024-03-31T10:00:00+01:00' },
      ],
      cases: Object.values(state.cases).filter((c) => c.unit_id === unitId || c.reporters.some((r) => r.unit_id === unitId)).map(summary),
    })
  },
  async staffCases(): Promise<CaseSummary[]> {
    await delay()
    return Object.values(state.cases).map(summary).sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  },
  async staffCase(caseId: string): Promise<CaseDetail> {
    await delay()
    const c = state.cases[caseId]
    if (!c) throw new Error('Case not found')
    return clone(c)
  },
  async approve(caseId: string): Promise<CaseDetail> {
    await delay()
    const c = state.cases[caseId]
    c.approval = { ...(c.approval ?? { rule: '' }), required: false, granted: true, granted_at: now(), granted_by: 'staff', rule: `approved by property manager (€${c.estimated_cost_eur})` }
    c.status = 'requested'
    addEvent(c, 'staff', 'approval.granted', `Property manager approved the €${c.estimated_cost_eur} repair`)
    addEvent(c, 'debye', 'job.sent', `Job sent to ${c.partner?.name}`)
    return clone(c)
  },
  async partner(partnerId: string): Promise<PartnerProfile> {
    await delay()
    const p = partners[partnerId]
    if (!p) throw new Error('Partner not found')
    return p
  },
  async jobs(partnerId: string): Promise<JobSummary[]> {
    await delay()
    return Object.values(state.cases)
      .filter((c) => c.partner?.partner_id === partnerId && c.status !== 'awaiting_approval' && c.status !== 'new')
      .map((c) => jobSummary(jobFor(partnerId, c)))
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  },
  async job(partnerId: string, caseId: string): Promise<JobDetail> {
    await delay()
    return clone(jobFor(partnerId, partnerCase(partnerId, caseId)))
  },
  async accept(partnerId: string, caseId: string): Promise<JobDetail> {
    await delay()
    const c = partnerCase(partnerId, caseId)
    c.status = 'accepted'
    addEvent(c, 'partner', 'job.accepted', `${c.partner?.name} accepted the job`)
    addMessage(c, 'out', c.reporters[0].name, `${c.partner?.name} hat den Auftrag angenommen.`)
    return clone(jobFor(partnerId, c))
  },
  async decline(partnerId: string, caseId: string, reason: string): Promise<JobDetail> {
    await delay()
    const c = partnerCase(partnerId, caseId)
    c.status = 'declined'
    addEvent(c, 'partner', 'job.declined', `${c.partner?.name} declined${reason ? `: ${reason}` : ''}`)
    return clone(jobFor(partnerId, c))
  },
  async technicians(partnerId: string): Promise<Technician[]> {
    await delay()
    return Object.values(TECHS)
      .filter((t) => t.partner_id === partnerId)
      .map((t) => ({ tech_id: t.tech_id, name: t.name, skills: t.skills, free_slots: freeSlots(t.tech_id) }))
  },
  async slots(partnerId: string, caseId: string, slots: Slot[], techId?: string): Promise<JobDetail> {
    await delay()
    const c = partnerCase(partnerId, caseId)
    if (techId && TECHS[techId]) {
      c.technician = { tech_id: techId, name: TECHS[techId].name }
      addEvent(c, 'partner', 'technician.assigned', `${c.partner?.name} assigned ${TECHS[techId].name}`)
    }
    state.pendingSlots[caseId] = slots.map((s) => ({ ...s, label: s.label ?? SLOTS.find((x) => x.start === s.start)?.label ?? fmtSlot(s) }))
    c.status = 'slots_proposed'
    c.proposed_slots = state.pendingSlots[caseId]
    addEvent(c, 'partner', 'slot.proposed', `${c.partner?.name} proposed ${slots.length} time slot${slots.length > 1 ? 's' : ''}`)
    addMessage(c, 'out', c.reporters[0].name, `Wann passt es dir? ${state.pendingSlots[caseId].map((s) => s.label).join(' · ')}`)
    return clone(jobFor(partnerId, c))
  },
  async tech(techId: string): Promise<TechProfile> {
    await delay()
    const t = TECHS[techId]
    if (!t) throw new Error('Technician not found')
    return { tech_id: t.tech_id, name: t.name, partner_id: t.partner_id, partner_name: partners[t.partner_id]?.name }
  },
  async techJobs(techId: string): Promise<JobSummary[]> {
    await delay()
    return Object.values(state.cases)
      .filter((c) => c.technician?.tech_id === techId)
      .map((c) => jobSummary(jobFor(c.partner!.partner_id, c)))
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  },
  async techJob(techId: string, caseId: string): Promise<JobDetail> {
    await delay()
    const c = state.cases[caseId]
    if (!c || c.technician?.tech_id !== techId) throw new Error('Job not found')
    return clone(jobFor(c.partner!.partner_id, c))
  },
  async techConfirm(techId: string, caseId: string): Promise<JobDetail> {
    await delay()
    const c = state.cases[caseId]
    if (!c || c.technician?.tech_id !== techId) throw new Error('Job not found')
    c.status = 'scheduled'
    addEvent(c, 'partner', 'technician.confirmed', `${c.technician.name} confirmed the visit: ${fmtSlot(c.slot!)}`)
    addMessage(c, 'out', c.reporters[0].name, `Super, ${c.technician.name} kommt ${fmtSlot(c.slot!)}. Ich erinnere dich vorher.`)
    return clone(jobFor(c.partner!.partner_id, c))
  },
  async complete(partnerId: string, caseId: string, form: FormData): Promise<JobDetail> {
    await delay(500)
    const c = partnerCase(partnerId, caseId)
    const notes = String(form.get('notes') ?? '')
    const photo = form.get('photo') as File | null
    const invoice = form.get('invoice') as File | null
    c.status = 'completed'
    addEvent(c, 'partner', 'job.completed', `Work done: ${notes || 'Ignition electrode replaced, boiler restarted'}`)
    if (photo && photo.size) {
      newDoc(c, 'photo', 'after_repair.jpg')
      addEvent(c, 'partner', 'document.attached', `Photo attached: ${photo.name}`)
    }
    const extracted = {
      invoice_number: 'RE-2026-1187',
      date: '2026-11-21',
      net_eur: 199.5,
      vat_eur: 37.91,
      gross_eur: 237.41,
      labour_hours: 1.0,
      line_items: [
        { desc: 'Anfahrtspauschale (Rahmenvertrag)', qty: 1, unit_price: 89.0 },
        { desc: 'Arbeitszeit Heizungstechniker, Std.', qty: 1, unit_price: 72.0 },
        { desc: 'Zündelektrode Vaillant ecoTEC plus', qty: 1, unit_price: 38.5 },
      ],
    }
    newDoc(c, 'invoice', 'RE-2026-1187.pdf', extracted)
    addEvent(c, 'partner', 'document.attached', `Invoice attached: ${invoice?.name || 'RE-2026-1187.pdf'}`)
    c.status = 'invoiced'
    c.price_check = { result: 'ok', flags: [] }
    ;(c.documents.find((d) => d.kind === 'invoice')!.extracted as Record<string, unknown>).price_check = c.price_check
    addEvent(c, 'debye', 'invoice.checked', 'Invoice RE-2026-1187 read: €237.41 gross, matches framework prices. Filed on unit 4b.')
    return clone(jobFor(partnerId, c))
  },
  async demoReset(): Promise<void> {
    state = initialState()
    emit({ type: 'demo.reset', case_id: null, event: null })
  },
  async demoSkip(): Promise<void> {
    state.dayOffset += 1
    state.minute = 0
    const c = heating()
    if (c?.status === 'scheduled') addEvent(c, 'system', 'demo.skip', 'Next morning: Tom from Heizung Schmidt is on site')
    else emit({ type: 'demo.skip', case_id: null, event: null })
  },
}
