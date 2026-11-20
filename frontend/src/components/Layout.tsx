import { useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { onStreamStatus } from '../lib/stream'
import { DEMO, USE_FIXTURES } from '../api/client'
import { initials } from '../lib/format'
import { DemoControls } from './DemoControls'
import { DebyeMark } from './ui'

export function LiveDot({ dark }: { dark?: boolean }) {
  const [on, setOn] = useState(false)
  useEffect(() => onStreamStatus(setOn), [])
  return (
    <span className={`inline-flex items-center gap-2 text-sm font-semibold ${dark ? 'text-on-plum-muted' : 'text-muted'}`} title={on ? 'Live updates connected' : 'Reconnecting…'}>
      <span className={`h-2.5 w-2.5 rounded-full ${on ? 'animate-pulse-dot bg-success' : 'bg-danger'}`} />
      {on ? 'Live' : 'Offline'}
    </span>
  )
}

export function StaffLayout({ children }: { children: ReactNode }) {
  const nav = ({ isActive }: { isActive: boolean }) =>
    `relative py-2 text-body font-medium transition-colors ${isActive ? 'text-on-plum after:absolute after:-bottom-1 after:left-1/4 after:h-[3px] after:w-1/2 after:rounded-full after:bg-lilac' : 'text-on-plum-muted hover:text-on-plum'}`
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 bg-plum text-on-plum">
        <div className="mx-auto flex h-topbar max-w-[1600px] items-center gap-10 px-gutter lg:px-page">
          <Link to="/staff" className="flex shrink-0 items-center gap-2">
            <DebyeMark size={52} bare />
            <span className="leading-tight">
              <span className="block font-serif text-xl font-semibold">Debye</span>
              <span className="block text-sm text-on-plum-muted">AI assistant</span>
            </span>
          </Link>
          <nav className="mx-auto hidden gap-10 md:flex">
            <NavLink to="/staff" end className={nav}>
              Cases
            </NavLink>
            <NavLink to="/staff/units" className={nav}>
              Units
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-4">
            {USE_FIXTURES && <span className="rounded-pill bg-plum-dark px-3 py-0.5 text-xs text-on-plum-muted">fixtures</span>}
            <LiveDot dark />
            <span className="hidden rounded-pill border border-line-on-plum px-3 py-1 text-sm text-on-plum-muted lg:inline">for reltix · centrix</span>
            <span className="hidden items-center gap-2 lg:flex">
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-info text-sm font-semibold">AB</span>
              <span className="text-body-sm">Anna Becker</span>
            </span>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1600px] px-gutter py-section lg:px-page">{children}</main>
      {DEMO && <DemoControls />}
    </div>
  )
}

export function PartnerLayout({ partnerName, partnerId, staffName, children }: { partnerName?: string; partnerId: string; staffName?: string; children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-surface">
        <div className="mx-auto flex max-w-[1600px] items-center gap-3 px-gutter py-3 lg:h-topbar lg:px-page lg:py-0">
          <Link to={`/partner/${partnerId}`} className="flex min-w-0 items-center gap-3">
            <span className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-warning text-body-sm font-semibold text-on-plum">{initials(partnerName ?? partnerId)}</span>
            <span className="min-w-0 leading-tight">
              <span className="block truncate font-serif text-xl font-semibold text-heading lg:text-2xl">{partnerName ?? partnerId}</span>
              <span className="block text-sm text-muted">Partner jobs</span>
            </span>
          </Link>
          <div className="ml-auto flex items-center gap-4">
            <span className="hidden items-center gap-2 rounded-pill bg-plum-faint py-1 pl-1 pr-4 text-sm font-medium text-plum sm:inline-flex">
              <DebyeMark size={32} /> via Debye · for reltix
            </span>
            {staffName && <span className="hidden text-body-sm lg:inline">{staffName}</span>}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1600px] px-gutter py-6 lg:px-page lg:py-section">{children}</main>
      {DEMO && <DemoControls />}
    </div>
  )
}
