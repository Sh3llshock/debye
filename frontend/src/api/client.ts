import type { CaseDetail, CaseSummary, JobDetail, JobSummary, PartnerProfile, Slot, UnitDetail, UnitSummary } from './types'

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

const http = {
  staffUnits: () => req<UnitSummary[]>('GET', '/api/staff/units'),
  staffUnit: (id: string) => req<UnitDetail>('GET', `/api/staff/units/${enc(id)}`),
  staffCases: () => req<CaseSummary[]>('GET', '/api/staff/cases'),
  staffCase: (id: string) => req<CaseDetail>('GET', `/api/staff/cases/${enc(id)}`),
  approve: (id: string) => req<CaseDetail>('POST', `/api/staff/cases/${enc(id)}/approve`),
  partner: (pid: string) => req<PartnerProfile>('GET', `/api/partner/${enc(pid)}`),
  jobs: (pid: string) => req<JobSummary[]>('GET', `/api/partner/${enc(pid)}/jobs`),
  job: (pid: string, cid: string) => req<JobDetail>('GET', `/api/partner/${enc(pid)}/jobs/${enc(cid)}`),
  accept: (pid: string, cid: string) => req<JobDetail>('POST', `/api/partner/${enc(pid)}/jobs/${enc(cid)}/accept`),
  decline: (pid: string, cid: string, reason: string) => req<JobDetail>('POST', `/api/partner/${enc(pid)}/jobs/${enc(cid)}/decline`, { reason }),
  slots: (pid: string, cid: string, slots: Slot[]) =>
    req<JobDetail>('POST', `/api/partner/${enc(pid)}/jobs/${enc(cid)}/slots`, { slots: slots.map(({ start, end }) => ({ start, end })) }),
  complete: (pid: string, cid: string, form: FormData) => req<JobDetail>('POST', `/api/partner/${enc(pid)}/jobs/${enc(cid)}/complete`, form),
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
