import type { CaseDetail, CaseSummary, CentrixEventResult, JobDetail, JobSummary, OnboardCheck, OnboardDocument, OnboardResult, PartnerApplication, PartnerProfile, Slot, TechProfile, Technician, UnitDetail, UnitSummary, WebsiteAutofill } from './types'

export const USE_FIXTURES = import.meta.env.VITE_USE_FIXTURES === '1'
export const DEMO = import.meta.env.VITE_DEMO === '1'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
  }
  const res = await fetch(path, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`)
  }
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

const enc = encodeURIComponent
// Partner ids from partners/*.json, used only while GET /api/partners does not exist.
const KNOWN_PARTNERS = ['heizung-schmidt', 'waerme-wagner', 'heiztechnik-gruen', 'elektro-klein', 'example-fibre']

const http = {
  staffUnits: () => req<UnitSummary[]>('GET', '/api/staff/units'),
  staffUnit: (id: string) => req<UnitDetail>('GET', `/api/staff/units/${enc(id)}`),
  // centrix moment → partners whose manifest triggers on it (backend/app/triggers.py)
  centrixMoveIn: (unitId: string, contactId?: string, moveInDate?: string) =>
    req<CentrixEventResult>('POST', '/api/centrix/events', { type: 'tenant.move_in', unit_id: unitId, contact_id: contactId, move_in_date: moveInDate }),
  staffCases: () => req<CaseSummary[]>('GET', '/api/staff/cases'),
  staffCase: (id: string) => req<CaseDetail>('GET', `/api/staff/cases/${enc(id)}`),
  approve: (id: string) => req<CaseDetail>('POST', `/api/staff/cases/${enc(id)}/approve`),
  reject: (id: string, reason: string) => req<CaseDetail>('POST', `/api/staff/cases/${enc(id)}/reject`, { reason }),
  partner: (pid: string) => req<PartnerProfile>('GET', `/api/partner/${enc(pid)}`),
  jobs: (pid: string) => req<JobSummary[]>('GET', `/api/partner/${enc(pid)}/jobs`),
  job: (pid: string, cid: string) => req<JobDetail>('GET', `/api/partner/${enc(pid)}/jobs/${enc(cid)}`),
  accept: (pid: string, cid: string) => req<JobDetail>('POST', `/api/partner/${enc(pid)}/jobs/${enc(cid)}/accept`),
  decline: (pid: string, cid: string, reason: string) => req<JobDetail>('POST', `/api/partner/${enc(pid)}/jobs/${enc(cid)}/decline`, { reason }),
  technicians: (pid: string) => req<Technician[]>('GET', `/api/partner/${enc(pid)}/technicians`),
  slots: (pid: string, cid: string, slots: Slot[], techId?: string) =>
    req<JobDetail>('POST', `/api/partner/${enc(pid)}/jobs/${enc(cid)}/slots`, { ...(techId ? { tech_id: techId } : {}), slots: slots.map(({ start, end }) => ({ start, end })) }),
  tech: (tid: string) => req<TechProfile>('GET', `/api/tech/${enc(tid)}`),
  techJobs: (tid: string) => req<JobSummary[]>('GET', `/api/tech/${enc(tid)}/jobs`),
  techJob: (tid: string, cid: string) => req<JobDetail>('GET', `/api/tech/${enc(tid)}/jobs/${enc(cid)}`),
  techConfirm: (tid: string, cid: string) => req<JobDetail>('POST', `/api/tech/${enc(tid)}/jobs/${enc(cid)}/confirm`),
  complete: (pid: string, cid: string, form: FormData) => req<JobDetail>('POST', `/api/partner/${enc(pid)}/jobs/${enc(cid)}/complete`, form),
  /** GET /api/partners; until the backend has it, fetch each known partner (ids from partners/*.json). */
  partners: async (): Promise<PartnerProfile[]> => {
    try {
      return await req<PartnerProfile[]>('GET', '/api/partners')
    } catch (e) {
      if (!(e instanceof ApiError) || (e.status !== 404 && e.status !== 405)) throw e
      const got = await Promise.all(KNOWN_PARTNERS.map((pid) => req<PartnerProfile>('GET', `/api/partner/${enc(pid)}`).catch(() => null)))
      return got.filter((p): p is PartnerProfile => !!p)
    }
  },
  onboardValidate: (manifest: Record<string, unknown>) => req<{ valid: boolean; checks: OnboardCheck[] }>('POST', '/api/partners/onboard/validate', { manifest }),
  askTenant: (pid: string, caseId: string, text: string) => req<JobDetail>('POST', `/api/partner/${enc(pid)}/jobs/${enc(caseId)}/question`, { text }),
  onboardFromWebsite: (url: string) => req<WebsiteAutofill>('POST', '/api/partners/onboard/from-website', { url }),
  onboard: (manifest: Record<string, unknown>, technicians: { name: string; skills: string[] }[], documents: OnboardDocument[] = [], company?: Record<string, string>) =>
    req<OnboardResult>('POST', '/api/partners/onboard', { manifest, technicians, documents, ...(company ? { company } : {}) }),
  partnerApplications: () => req<PartnerApplication[]>('GET', '/api/staff/partners/applications'),
  approvePartner: (pid: string) => req<{ status: string }>('POST', `/api/staff/partners/${enc(pid)}/approve`, {}),
  rejectPartner: (pid: string, reason: string) => req<{ status: string }>('POST', `/api/staff/partners/${enc(pid)}/reject`, { reason }),
  demoScenarios: () => req<unknown>('POST', '/demo/scenarios'),
  demoReset: () => req<void>('POST', '/demo/reset'),
  demoSkip: () => req<void>('POST', '/demo/skip-to-tomorrow'),
}

export type Api = typeof http

// Fixtures are loaded lazily so they are not part of the production bundle's hot path.
let mockPromise: Promise<Api> | null = null
function mock(): Promise<Api> {
  mockPromise ??= import('./mock').then((m) => m.mockApi as unknown as Api)
  return mockPromise
}

export const api: Api = new Proxy(http, {
  get(target, prop: keyof Api) {
    if (!USE_FIXTURES) return target[prop]
    return (...args: unknown[]) => mock().then((m) => (m[prop] as (...a: unknown[]) => unknown)(...args))
  },
})
