import { useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { onStreamStatus } from '../lib/stream'
import { DEMO, USE_FIXTURES } from '../api/client'
import { DemoControls } from './DemoControls'
import { DebyeMark } from './ui'

export function LiveDot() {
  const [on, setOn] = useState(false)
  useEffect(() => onStreamStatus(setOn), [])
  return (
    <span className="inline-flex items-center gap-2 text-sm font-semibold text-on-plum-muted" title={on ? 'Live updates connected' : 'Reconnecting…'}>
      <span className={`h-3 w-3 rounded-full ${on ? 'animate-pulse-dot bg-success' : 'bg-danger'}`} />
      {on ? 'Live' : 'Offline'}
    </span>
  )
}

export function Brand({ product, size = 44 }: { product: string; size?: number }) {
  return (
    <Link to="/" className="flex min-w-0 items-center gap-3">
      <DebyeMark size={size} onDark />
      <span className="min-w-0 leading-tight">
        <span className="block font-serif text-xl font-semibold">Debye</span>
        <span className="block truncate text-xs text-on-plum-muted">AI assistant · {product}</span>
      </span>
    </Link>
  )
}

export function StaffLayout({ children }: { children: ReactNode }) {
  const nav = ({ isActive }: { isActive: boolean }) =>
    `rounded-button px-4 py-2 text-body-sm font-medium transition-colors ${isActive ? 'bg-surface text-plum' : 'text-on-plum hover:bg-plum-dark'}`
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 bg-plum text-on-plum">
        <div className="mx-auto flex h-topbar max-w-[1600px] items-center gap-8 px-gutter lg:px-page">
          <Brand product="for reltix · centrix" />
          <nav className="flex gap-2">
            <NavLink to="/staff" end className={nav}>Cases</NavLink>
            <NavLink to="/staff/units/unit_4b" className={nav}>Unit 4b</NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-4">
            {USE_FIXTURES && <span className="rounded-pill border border-line-on-plum px-3 py-0.5 text-xs text-on-plum-muted">fixtures</span>}
            <LiveDot />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1600px] px-gutter py-section lg:px-page">{children}</main>
      {DEMO && <DemoControls />}
    </div>
  )
}

export function PartnerLayout({ partnerName, partnerId, children }: { partnerName?: string; partnerId: string; children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 bg-plum text-on-plum">
        <div className="mx-auto flex max-w-3xl items-center gap-3 px-gutter py-3">
          <Link to={`/partner/${partnerId}`} className="flex min-w-0 items-center gap-3">
            <DebyeMark size={40} onDark />
            <span className="min-w-0 leading-tight">
              <span className="block font-serif text-xl font-semibold">Debye</span>
              <span className="block truncate text-xs text-on-plum-muted">Jobs for {partnerName ?? partnerId}</span>
            </span>
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-gutter py-6">{children}</main>
      {DEMO && <DemoControls />}
    </div>
  )
}
