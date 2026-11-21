// Route gate for the portals: staff, partner and technician pages need a session (lib/auth.ts).
// The server enforces it anyway; this only shows the right login instead of empty pages.
import { useState, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { ApiError, USE_FIXTURES, api } from '../api/client'
import { anyPartnerToken, partnerToken, saveLogin, staffToken, techToken, useAuthVersion } from '../lib/auth'
import { t } from '../lib/i18n'
import { LangToggle, Logo } from './Layout'

export function RequireLogin({ role, children }: { role: 'staff' | 'partner' | 'tech'; children: ReactNode }) {
  useAuthVersion()
  const loc = useLocation()
  if (USE_FIXTURES) return <>{children}</>
  const id = decodeURIComponent(loc.pathname.split('/').filter(Boolean)[1] ?? '')
  if (role === 'staff') return staffToken() ? <>{children}</> : <StaffLogin />
  const ok = role === 'partner' ? !!partnerToken(id) : !!(techToken(id) ?? anyPartnerToken())
  if (ok) return <>{children}</>
  return <Navigate to={`/partner/login?next=${encodeURIComponent(loc.pathname)}`} replace />
}

const STAFF_DEMO = 'anna.becker@example.com'

function StaffLogin() {
  const [login, setLogin] = useState(STAFF_DEMO)
  const [pass, setPass] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    setErr('')
    if (!pass) return setErr(t('Enter your password.'))
    setBusy(true)
    try {
      const r = await api.login(login.trim(), pass, 'staff')
      saveLogin(r)
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 404 ? t('No property-management account with this email.') : t('Login failed. Please try again.'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="grid min-h-screen place-items-center bg-bg px-4">
      <form
        className="card w-full max-w-[400px]"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <div className="mb-4 flex items-center justify-between">
          <Logo className="h-9 w-9" />
          <LangToggle />
        </div>
        <h1 className="text-page">{t('Property management')}</h1>
        <p className="mb-5 mt-1 text-secondary">{t('Log in to see and approve cases.')}</p>
        <label className="label mb-1 block" htmlFor="slogin">
          {t('Email')}
        </label>
        <input id="slogin" className="field mb-3" value={login} onChange={(e) => setLogin(e.target.value)} autoComplete="username" />
        <label className="label mb-1 block" htmlFor="spass">
          {t('Password')}
        </label>
        <input id="spass" className="field" type="password" value={pass} onChange={(e) => setPass(e.target.value)} autoComplete="current-password" autoFocus />
        {err && <p className="mb-0 mt-3 font-medium text-red">{err}</p>}
        <button type="submit" className="btn-primary mt-5 w-full" disabled={busy}>
          {busy ? t('Logging in…') : t('Log in')}
        </button>
        <p className="mb-0 mt-4 text-label text-muted">
          {t('Demo: Anna Becker, any password works.')}
        </p>
      </form>
    </div>
  )
}
