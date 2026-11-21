// Shared pieces of the tenant portal: data context, top bar, language toggle.
import { createContext, useContext } from 'react'
import { useNavigate } from 'react-router-dom'
import { t, useLang } from '../lib/i18n'
import type { TCase, TMe } from './api'
import { isClosed } from './progress'

export interface Portal {
  me: TMe
  cases: TCase[]
  tick: number // bumps on every relevant live event
  refresh: () => void
  logout: () => void
}
export const Ctx = createContext<Portal | null>(null)
export const usePortal = () => useContext(Ctx)!

export function LangToggle() {
  const [lang, setLang] = useLang()
  return (
    <div className="lang" role="group" aria-label={t('Language')}>
      <button className={lang === 'en' ? 'on' : ''} onClick={() => setLang('en')}>
        EN
      </button>
      <button className={lang === 'de' ? 'on' : ''} onClick={() => setLang('de')}>
        DE
      </button>
    </div>
  )
}

export function TopBar({ sel }: { sel?: string | null }) {
  const { me, cases, logout } = usePortal()
  const nav = useNavigate()
  const open = cases.filter((c) => !isClosed(c))
  const home = me.home
  return (
    <header className="top">
      <button className="tbrand" onClick={() => nav('/tenant')}>
        <div className="logo" />
        Debye
      </button>
      <nav className="tabs">
        <button className={`tab ${!sel ? 'on' : ''}`} onClick={() => nav('/tenant')}>
          {t('Home')}
        </button>
        {open.map((c) => (
          <button key={c.case_id} className={`tab ${sel === c.case_id ? 'on' : ''}`} onClick={() => nav(`/tenant/case/${c.case_id}`)}>
            <span className={`dotst ${['awaiting_approval', 'requested', 'accepted', 'awaiting_technician'].includes(c.status) ? 'wait' : ''}`} />
            {c.title.length > 22 ? c.title.slice(0, 21) + '…' : c.title}
          </button>
        ))}
      </nav>
      <div className="tuser">
        <LangToggle />
        <div className="uav">{me.contact.name[0]}</div>
        <div className="tname">
          <b style={{ fontWeight: 600 }}>{me.contact.name}</b>{' '}
          {home?.address && <span>· {home.address.split(',')[0]}{home.floor != null ? ', ' + floorLabel(home.floor) : ''}</span>}
        </div>
        <button className="logout" onClick={logout}>
          {t('Log out')}
        </button>
      </div>
    </header>
  )
}

export function floorLabel(n: number): string {
  if (n === 0) return t('ground floor')
  return t('floor {n}', { n })
}

