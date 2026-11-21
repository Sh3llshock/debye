// Portal sessions (backend app/auth.py): one signed token per role, picked by the URL being called.
// Demo login (any password) via POST /api/auth/login; the server checks role and ownership.
import { useSyncExternalStore } from 'react'

export type Role = 'staff' | 'partner' | 'tech' | 'tenant'
export interface LoginResult {
  role: Role
  sub: string
  pid?: string
  name: string
  to: string
  token: string
}
interface Store {
  staff?: string
  partner?: Record<string, string> // partner id → token
  tech?: Record<string, string> // technician id → token
}

const KEY = 'debye-auth-v1'
const TENANT_KEY = 'debye-tenant-token' // owned by the tenant portal (src/tenant/api.ts)
const listeners = new Set<() => void>()
let version = 0

function load(): Store {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? '{}') as Store
  } catch {
    return {}
  }
}
function save(s: Store) {
  try {
    localStorage.setItem(KEY, JSON.stringify(s))
  } catch {
    /* private mode: the session lasts for this page only */
  }
  version++
  listeners.forEach((f) => f())
}
function tenantToken(): string | null {
  try {
    return localStorage.getItem(TENANT_KEY)
  } catch {
    return null
  }
}

export const staffToken = () => load().staff ?? null
export const partnerToken = (pid: string) => load().partner?.[pid] ?? null
export const techToken = (tid: string) => load().tech?.[tid] ?? null
/** Any partner session (a company may open its technicians' pages; the server checks the company). */
export const anyPartnerToken = () => Object.values(load().partner ?? {})[0] ?? null

export function saveLogin(r: Pick<LoginResult, 'role' | 'sub' | 'pid' | 'token'>) {
  const s = load()
  if (r.role === 'staff') s.staff = r.token
  else if (r.role === 'partner' && r.pid) s.partner = { ...s.partner, [r.pid]: r.token }
  else if (r.role === 'tech') s.tech = { ...s.tech, [r.sub]: r.token }
  else if (r.role === 'tenant') {
    try {
      localStorage.setItem(TENANT_KEY, r.token)
    } catch {
      /* private mode */
    }
  }
  save(s)
}

export function logout(role: Role, id?: string) {
  const s = load()
  if (role === 'staff') delete s.staff
  if (role === 'partner' && id && s.partner) delete s.partner[id]
  if (role === 'tech' && id && s.tech) delete s.tech[id]
  save(s)
}

/** Token for an API path: /api/staff → staff, /api/partner/<pid> → that partner, /api/tech/<tid> → tech. */
export function tokenForPath(path: string): string | null {
  const parts = path.split('?')[0].split('/').filter(Boolean)
  if (path.startsWith('/api/staff') || path.startsWith('/api/partners?') || path === '/api/partners') return staffToken()
  if (path.startsWith('/api/partner/') && parts[2]) return partnerToken(decodeURIComponent(parts[2]))
  if (path.startsWith('/api/tech/') && parts[2]) return techToken(decodeURIComponent(parts[2])) ?? anyPartnerToken()
  if (path.startsWith('/api/tenant')) return tenantToken()
  return null
}

/** Token for the page being shown (live stream): /staff, /partner/<pid>, /tech/<tid>, /tenant. */
export function tokenForPage(pathname = location.pathname): string | null {
  const parts = pathname.split('/').filter(Boolean)
  if (parts[0] === 'staff' || parts[0] === 'partners') return staffToken()
  if (parts[0] === 'partner' && parts[1]) return partnerToken(parts[1])
  if (parts[0] === 'tech' && parts[1]) return techToken(parts[1]) ?? anyPartnerToken()
  if (parts[0] === 'tenant') return tenantToken()
  return null
}

/** A 401 from the API: forget that session so the page shows its login again. */
export function expireFor(path: string) {
  const parts = path.split('?')[0].split('/').filter(Boolean)
  if (path.startsWith('/api/staff') || path === '/api/partners') logout('staff')
  else if (path.startsWith('/api/partner/') && parts[2]) logout('partner', decodeURIComponent(parts[2]))
  else if (path.startsWith('/api/tech/') && parts[2]) logout('tech', decodeURIComponent(parts[2]))
}

/** Re-render when a login/logout happens (also in other tabs). */
export function useAuthVersion(): number {
  return useSyncExternalStore(
    (f) => {
      listeners.add(f)
      const onStorage = (e: StorageEvent) => {
        if (e.key === KEY || e.key === TENANT_KEY) {
          version++
          f()
        }
      }
      window.addEventListener('storage', onStorage)
      return () => {
        listeners.delete(f)
        window.removeEventListener('storage', onStorage)
      }
    },
    () => version,
  )
}

export function onAuthChange(f: () => void): () => void {
  listeners.add(f)
  return () => listeners.delete(f)
}
