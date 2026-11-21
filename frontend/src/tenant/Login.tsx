import { useState } from 'react'
import { t } from '../lib/i18n'
import { ApiError, api } from './api'
import { LangToggle } from './shell'

export default function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [id, setId] = useState('')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const go = async () => {
    if (!id.trim()) return setErr(t('We couldn’t find a tenancy with that email or phone number.'))
    setBusy(true)
    try {
      const r = await api.login(id.trim(), pw)
      setErr('')
      onLogin(r.token)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setErr(t('We couldn’t find a tenancy with that email or phone number.'))
      else if (e instanceof ApiError && e.status === 400) setErr(t('Please enter your password.'))
      else setErr(t('Could not reach Debye. Please try again.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <form
        className="lbox"
        onSubmit={(e) => {
          e.preventDefault()
          go()
        }}
      >
        <div className="logo" />
        <h1>{t('Log in to Debye')}</h1>
        <p>{t('Report a problem and follow the repair.')}</p>
        <input value={id} onChange={(e) => setId(e.target.value)} placeholder={t('Email or phone number')} autoComplete="username" />
        <input value={pw} onChange={(e) => setPw(e.target.value)} type="password" placeholder={t('Password')} autoComplete="current-password" />
        {err && <div className="err">{err}</div>}
        <button className="primary" type="submit" disabled={busy}>
          {t('Log in')}
        </button>
        <div className="lnote">
          {t('Use the email or phone number from your tenancy agreement. You can also just message Debye on WhatsApp.')}
        </div>
        <LangToggle />
      </form>
    </div>
  )
}
