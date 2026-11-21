import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { api, DEMO, USE_FIXTURES } from '../api/client'
import { onStreamStatus, useStream } from '../lib/stream'
import { needsApproval } from '../lib/lifecycle'
import { useDebounced, useResource } from '../lib/useResource'
import { t, useLang } from '../lib/i18n'
import { DemoControls } from './DemoControls'
import { Icon } from './icons'

// ---------- breadcrumb: pages set it, the shell shows it above the page title ----------
export type Crumb = { label: string; to?: string }
const CrumbCtx = createContext<(c: Crumb[]) => void>(() => {})
export function useCrumbs(crumbs: Crumb[]) {
  const set = useContext(CrumbCtx)
  const key = JSON.stringify(crumbs)
  useEffect(() => set(crumbs), [key]) // eslint-disable-line react-hooks/exhaustive-deps
}

// ---------- full-bleed pages (the inbox fills the window under the top bar) ----------
const BleedCtx = createContext<(on: boolean) => void>(() => {})
export function useFullBleed() {
  const set = useContext(BleedCtx)
  useEffect(() => {
    set(true)
    return () => set(false)
  }, [set])
}

/** The Debye line logo (docs/design/v3, public/brand). */
export function Logo({ className = 'h-7 w-7' }: { className?: string }) {
  return <img src="/brand/debye-logo.png" alt="" aria-hidden draggable={false} className={`flex-none select-none object-contain ${className}`} />
}

/** Logo + "Debye" + small role label, as in the v3 top bar. */
export function Brand({ to, sub }: { to: string; sub?: string }) {
  return (
    <Link to={to} className="flex min-w-0 items-center gap-[9px] text-[19px] font-semibold tracking-[-0.02em] text-ink no-underline">
      <Logo />
      Debye
      {sub && <small className="ml-0.5 hidden truncate text-meta font-medium tracking-normal text-muted sm:inline">{sub}</small>}
    </Link>
  )
}

export function LiveDot() {
  const [on, setOn] = useState(false)
  useEffect(() => onStreamStatus(setOn), [])
  return (
    <span className="inline-flex items-center gap-2 text-meta text-muted" title={on ? t('Live updates connected') : t('Reconnecting…')}>
      <span className={`h-2 w-2 rounded-full ${on ? 'animate-pulse-dot bg-ok' : 'bg-red'}`} />
      <span className="hidden sm:inline">{on ? t('Live') : t('Offline')}</span>
    </span>
  )
}

/** EN / DE pill toggle (top right of every page). */
export function LangToggle() {
  const [lang, setLang] = useLang()
  return (
    <div className="inline-flex rounded-full bg-surface p-0.5 shadow-ring" role="group" aria-label={t('Language')}>
      {(['en', 'de'] as const).map((l) => (
        <button
          key={l}
          onClick={() => setLang(l)}
          aria-pressed={lang === l}
          className={`rounded-full px-2.5 py-0.5 text-meta font-semibold uppercase transition-colors ${lang === l ? 'bg-wine text-cream' : 'text-secondary hover:bg-beige'}`}
        >
          {l}
        </button>
      ))}
    </div>
  )
}

/** Round initial avatar + name (the signed-in person). */
export function Me({ name, onClick }: { name: string; onClick?: () => void }) {
  const inner = (
    <>
      <span className="uav">{name.charAt(0).toUpperCase()}</span>
      <span className="hidden lg:inline">{name}</span>
    </>
  )
  const cls = 'flex items-center gap-[9px] whitespace-nowrap font-medium text-ink'
  return onClick ? (
    <button className={cls} onClick={onClick} title={name}>
      {inner}
    </button>
  ) : (
    <span className={cls} title={name}>
      {inner}
    </span>
  )
}

export type TabItem = { to: string; label: string; count?: number; soft?: boolean; end?: boolean; match?: (path: string) => boolean }

function Tabs({ items }: { items: TabItem[] }) {
  const { pathname } = useLocation()
  return (
    <nav className="no-scrollbar flex gap-1 overflow-x-auto">
      {items.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.end}
          className={({ isActive }) => `tab ${isActive || it.match?.(pathname) ? 'tab-on' : ''}`}
        >
          {it.label}
          {!!it.count && <span className={`cnt ${it.soft ? 'cnt-soft' : ''}`}>{it.count}</span>}
        </NavLink>
      ))}
    </nav>
  )
}

/** Crumbs above the page title ("Cases > 7781"); hidden when there is only one level. */
function Crumbs({ crumbs }: { crumbs: Crumb[] }) {
  if (crumbs.length < 2) return null
  return (
    <div className="crumb flex min-w-0 flex-wrap items-center gap-1">
      {crumbs.map((c, i) => (
        <span key={i} className="flex min-w-0 items-center gap-1">
          {i > 0 && <Icon name="chevron" className="h-3.5 w-3.5" />}
          {c.to ? <Link to={c.to}>{c.label}</Link> : <span className="truncate">{c.label}</span>}
        </span>
      ))}
    </div>
  )
}

/**
 * The v3 shell: a top bar (brand, pill tabs, extras, language, person) and a centred page
 * (max 1320px, 26/28px padding). On phones the tabs move to a second, scrollable row.
 */
export function Shell({ brand, tabs, extra, right, crumbs = [], children, bleed: bleedProp }: { brand: ReactNode; tabs?: TabItem[]; extra?: ReactNode; right?: ReactNode; crumbs?: Crumb[]; children: ReactNode; bleed?: boolean }) {
  const [bleedState, setBleed] = useState(false)
  const bleed = bleedProp ?? bleedState
  return (
    <BleedCtx.Provider value={setBleed}>
      <div className={`flex flex-col ${bleed ? 'h-[100dvh]' : 'min-h-[100dvh]'}`}>
        <header className="sticky top-0 z-20 flex-none border-b border-line bg-bg">
          <div className="flex items-center gap-4 px-4 py-3 md:px-7">
            {brand}
            {tabs && tabs.length > 0 && (
              <div className="ml-5 hidden min-w-0 md:block">
                <Tabs items={tabs} />
              </div>
            )}
            <div className="ml-auto flex min-w-0 items-center gap-3 md:gap-4">
              {extra}
              {right}
              <LangToggle />
            </div>
          </div>
          {tabs && tabs.length > 0 && (
            <div className="-mt-1 px-3 pb-2 md:hidden">
              <Tabs items={tabs} />
            </div>
          )}
        </header>
        <main className={bleed ? 'min-h-0 flex-1 overflow-hidden' : 'flex-1'}>
          {bleed ? (
            children
          ) : (
            <div className="mx-auto w-full max-w-[1320px] px-4 pb-[60px] pt-[26px] md:px-7">
              <Crumbs crumbs={crumbs} />
              {children}
            </div>
          )}
        </main>
        {DEMO && <DemoControls />}
      </div>
    </BleedCtx.Provider>
  )
}

/** Staff search: Enter jumps to the cases table filtered by the text. */
function StaffSearch() {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  return (
    <form
      className="hidden xl:block"
      onSubmit={(e) => {
        e.preventDefault()
        nav(`/staff/cases${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''}`)
      }}
    >
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={t('Search cases, flats, tenants…')}
        aria-label={t('Search')}
        className="w-[260px] rounded-full bg-surface px-3.5 py-2 text-label text-ink shadow-ring outline-none placeholder:text-muted focus:shadow-[0_0_0_2px_theme(colors.wine)]"
      />
    </form>
  )
}

export function StaffLayout({ children }: { children: ReactNode }) {
  const [crumbs, setCrumbs] = useState<Crumb[]>([])
  const { data, reload } = useResource(() => api.staffCases(), [])
  const refetch = useDebounced(reload, 400)
  useStream(() => refetch())
  const needs = data?.filter((c) => needsApproval(c.status)).length ?? 0
  const running = data?.filter((c) => !['closed', 'rejected'].includes(c.status)).length ?? 0
  return (
    <CrumbCtx.Provider value={setCrumbs}>
      <Shell
        brand={<Brand to="/staff" sub={t('Property management')} />}
        tabs={[
          { to: '/staff', label: t('Inbox'), count: needs, end: true },
          { to: '/staff/cases', label: t('Cases'), count: running, soft: true },
          { to: '/staff/units', label: t('Properties') },
          { to: '/staff/partners', label: t('Partners'), match: (p) => p.startsWith('/partners/') },
        ]}
        crumbs={crumbs}
        extra={
          <>
            <StaffSearch />
            <span className="hidden whitespace-nowrap text-meta text-muted 2xl:inline">
              {t('Fields typed by tenants')} <b className="text-wine">0</b> · {t('Calls')} <b className="text-wine">0</b>
            </span>
          </>
        }
        right={
          <>
            {USE_FIXTURES && <span className="pill bg-warn-tint text-warn">fixtures</span>}
            <LiveDot />
            <Me name="Anna Becker" />
          </>
        }
      >
        {children}
      </Shell>
    </CrumbCtx.Provider>
  )
}

/** Simple shell for pages without tabs of their own (technician phone pages, call page). */
export function PlainLayout({ to, sub, right, crumbs = [], children }: { to: string; sub?: string; right?: ReactNode; crumbs?: Crumb[]; children: ReactNode }) {
  return (
    <Shell brand={<Brand to={to} sub={sub} />} right={right} crumbs={crumbs}>
      {children}
    </Shell>
  )
}

export function TechLayout({ techId, name, partnerName, children }: { techId: string; name?: string; partnerName?: string; children: ReactNode }) {
  return (
    <PlainLayout
      to={`/tech/${techId}`}
      sub={partnerName ? `${t('Technician')} · ${partnerName}` : t('Technician')}
      right={
        <>
          <LiveDot />
          {name && <Me name={name} />}
        </>
      }
    >
      {children}
    </PlainLayout>
  )
}

export { Icon }

/** v3 partner portal top bar: "Debye Partners", tabs with counts, WhatsApp note, company + contact. */
export function PartnerLayout({
  partnerName,
  partnerId,
  contact,
  counts = {},
  crumbs = [],
  children,
}: {
  partnerName?: string
  partnerId: string
  contact?: string
  counts?: { new?: number; wip?: number; availability?: number; done?: number }
  crumbs?: Crumb[]
  children: ReactNode
}) {
  const base = `/partner/${partnerId}`
  const name = partnerName ?? partnerId
  return (
    <Shell
      brand={<Brand to={base} sub={t('Partners')} />}
      tabs={[
        { to: base, label: t('Overview'), end: true },
        { to: `${base}/new`, label: t('New jobs'), count: counts.new },
        { to: `${base}/wip`, label: t('Work in progress'), count: counts.wip, match: (p) => p.startsWith(`${base}/jobs/`) },
        { to: `${base}/availability`, label: t('Availability'), count: counts.availability },
        { to: `${base}/done`, label: t('Done & invoices'), count: counts.done },
        { to: `${base}/profile`, label: t('Profile') },
      ]}
      crumbs={crumbs}
      extra={<span className="hidden whitespace-nowrap text-meta text-muted 2xl:inline">{t('Jobs also arrive on WhatsApp')}</span>}
      right={
        <>
          <LiveDot />
          <Link to={`${base}/profile`} className="flex items-center gap-[9px] whitespace-nowrap" title={name}>
            <span className="uav">{name.charAt(0).toUpperCase()}</span>
            <span className="hidden leading-tight lg:block">
              <b className="block text-label font-semibold text-ink">{name}</b>
              {contact && <span className="text-meta text-muted">{contact.split(' ')[0]}</span>}
            </span>
          </Link>
        </>
      }
    >
      {children}
    </Shell>
  )
}
