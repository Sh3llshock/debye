import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { onStreamStatus } from '../lib/stream'
import { DEMO, USE_FIXTURES } from '../api/client'
import { initials } from '../lib/format'
import { t, useLang } from '../lib/i18n'
import { DemoControls } from './DemoControls'
import { Icon } from './icons'
import { Mascot } from './ui'

// ---------- breadcrumb: pages set it, the shell header shows it ----------
export type Crumb = { label: string; to?: string }
const CrumbCtx = createContext<(c: Crumb[]) => void>(() => {})
export function useCrumbs(crumbs: Crumb[]) {
  const set = useContext(CrumbCtx)
  const key = JSON.stringify(crumbs)
  useEffect(() => set(crumbs), [key]) // eslint-disable-line react-hooks/exhaustive-deps
}

export function LiveDot() {
  const [on, setOn] = useState(false)
  useEffect(() => onStreamStatus(setOn), [])
  return (
    <span className="inline-flex items-center gap-2 text-label text-secondary" title={on ? t('Live updates connected') : t('Reconnecting…')}>
      <span className={`h-2 w-2 rounded-full ${on ? 'animate-pulse-dot bg-positive' : 'bg-negative'}`} />
      <span className="hidden sm:inline">{on ? t('Live') : t('Offline')}</span>
    </span>
  )
}

/** EN / DE segmented toggle (top right of every page). */
export function LangToggle() {
  const [lang, setLang] = useLang()
  return (
    <div className="inline-flex rounded border border-line p-0.5" role="group" aria-label={t('Language')}>
      {(['en', 'de'] as const).map((l) => (
        <button
          key={l}
          onClick={() => setLang(l)}
          aria-pressed={lang === l}
          className={`rounded-chip px-2 py-0.5 text-meta font-semibold uppercase transition-colors ${lang === l ? 'bg-ink text-on-action' : 'text-secondary hover:bg-sub'}`}
        >
          {l}
        </button>
      ))}
    </div>
  )
}

type RailItem = { to: string; label: string; icon: string; end?: boolean }

function Shell({ logo, items, crumbs, right, children, phoneCrumb }: { logo: ReactNode; items: RailItem[]; crumbs: Crumb[]; right: ReactNode; children: ReactNode; phoneCrumb?: number }) {
  const keep = phoneCrumb ?? crumbs.length - 1
  return (
    <div className="min-h-screen md:pl-rail">
      <aside className="fixed inset-x-0 bottom-0 z-30 flex h-16 items-center justify-around bg-rail md:inset-y-0 md:left-0 md:right-auto md:h-auto md:w-rail md:flex-col md:justify-start md:gap-2 md:py-4">
        <div className="hidden md:mb-4 md:block">{logo}</div>
        {items.map((it) => (
          <NavLink
            key={it.to}
            to={it.to}
            end={it.end}
            className={({ isActive }) =>
              `flex w-16 flex-col items-center gap-1 rounded py-2 text-center text-tiny transition-colors ${isActive ? 'bg-rail-active text-rail-text-active' : 'text-rail-text hover:text-rail-text-active'}`
            }
          >
            <Icon name={it.icon} className="h-5 w-5" />
            {it.label}
          </NavLink>
        ))}
      </aside>
      <header className="sticky top-0 z-20 flex h-header items-center gap-3 border-b border-line bg-surface px-4 md:gap-4 md:px-work">
        <div className="shrink-0 md:hidden">{logo}</div>
        <nav className="flex min-w-0 items-center gap-2 text-body">
          {crumbs.map((c, i) => (
            <span key={i} className={`min-w-0 items-center gap-2 ${i === keep ? 'flex' : 'hidden sm:flex'}`}>
              {i > 0 && <Icon name="chevron" className={`h-4 w-4 shrink-0 text-muted ${i === keep ? 'hidden sm:block' : ''}`} />}
              {c.to ? (
                <Link to={c.to} className={`truncate ${i === 0 ? 'font-semibold text-ink' : 'text-action'} hover:underline`}>
                  {c.label}
                </Link>
              ) : (
                <span className={`truncate ${i === 0 ? 'font-semibold text-ink' : 'text-secondary'}`}>{c.label}</span>
              )}
            </span>
          ))}
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-3 md:gap-4">
          {right}
          <LangToggle />
        </div>
      </header>
      <main className="px-4 pb-24 pt-work md:px-work md:pb-work">{children}</main>
      {DEMO && <DemoControls />}
    </div>
  )
}

function MascotLogo({ to = '/staff' }: { to?: string }) {
  return (
    <Link to={to} className="block h-11 w-11 overflow-hidden rounded-full bg-surface" title="Debye · AI assistant">
      <Mascot pose="avatar" alt="Debye" className="h-full w-full object-cover" />
    </Link>
  )
}

export function StaffLayout({ children }: { children: ReactNode }) {
  const [crumbs, setCrumbs] = useState<Crumb[]>([{ label: t('Cases') }])
  return (
    <CrumbCtx.Provider value={setCrumbs}>
      <Shell
        logo={<MascotLogo />}
        items={[
          { to: '/staff', label: t('Cases'), icon: 'cases', end: true },
          { to: '/staff/units', label: t('Units'), icon: 'building' },
          { to: '/staff/partners', label: t('Partners'), icon: 'wrench' },
        ]}
        crumbs={crumbs}
        right={
          <>
            {USE_FIXTURES && <span className="rounded-chip bg-warning-soft px-2 py-0.5 text-meta font-semibold text-warning">fixtures</span>}
            <LiveDot />
            <span className="hidden text-body text-secondary lg:inline">Anna Becker · reltix</span>
          </>
        }
      >
        {children}
      </Shell>
    </CrumbCtx.Provider>
  )
}

export function PartnerLayout({ partnerName, partnerId, staffName, children }: { partnerName?: string; partnerId: string; staffName?: string; children: ReactNode }) {
  const logo = (
    <Link to={`/partner/${partnerId}`} className="flex h-11 w-11 items-center justify-center rounded bg-surface text-label font-semibold text-ink" title={partnerName}>
      {initials(partnerName ?? partnerId)}
    </Link>
  )
  return (
    <Shell
      logo={logo}
      items={[{ to: `/partner/${partnerId}`, label: t('Jobs'), icon: 'jobs' }]}
      crumbs={[{ label: partnerName ?? partnerId, to: `/partner/${partnerId}` }, { label: t('Jobs from reltix, sent by Debye') }]}
      phoneCrumb={0}
      right={
        <>
          <LiveDot />
          {staffName && <span className="hidden text-body text-secondary lg:inline">{staffName}</span>}
        </>
      }
    >
      {children}
    </Shell>
  )
}

export function TechLayout({ techId, name, partnerName, children }: { techId: string; name?: string; partnerName?: string; children: ReactNode }) {
  return (
    <Shell
      logo={<MascotLogo to={`/tech/${techId}`} />}
      items={[{ to: `/tech/${techId}`, label: t('My jobs'), icon: 'jobs' }]}
      crumbs={[{ label: name ?? techId, to: `/tech/${techId}` }, ...(partnerName ? [{ label: partnerName }] : [])]}
      phoneCrumb={0}
      right={<LiveDot />}
    >
      {children}
    </Shell>
  )
}
