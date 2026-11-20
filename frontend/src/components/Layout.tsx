import { useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { onStreamStatus } from '../lib/stream'
import { DEMO, USE_FIXTURES } from '../api/client'
import { DemoControls } from './DemoControls'

export function LiveDot() {
  const [on, setOn] = useState(false)
  useEffect(() => onStreamStatus(setOn), [])
  return (
    <span className="inline-flex items-center gap-2 text-sm font-semibold text-muted" title={on ? 'Live updates connected' : 'Reconnecting…'}>
      <span className={`h-3 w-3 rounded-full ${on ? 'bg-success animate-pulse-dot' : 'bg-danger'}`} />
      {on ? 'Live' : 'Offline'}
    </span>
  )
}

export function Brand({ product }: { product: string }) {
  return (
    <Link to="/" className="flex items-baseline gap-3">
      <span className="font-serif text-2xl font-semibold text-plum">Debye</span>
      <span className="hidden text-sm text-muted sm:inline">AI assistant · {product}</span>
    </Link>
  )
}

export function StaffLayout({ children }: { children: ReactNode }) {
  const nav = ({ isActive }: { isActive: boolean }) => `rounded-pill px-4 py-2 font-semibold ${isActive ? 'bg-plum text-on-plum' : 'text-plum hover:bg-plum-soft'}`
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-bg/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center gap-6 px-gutter py-3 lg:px-section">
          <Brand product="centrix (staff)" />
          <nav className="flex gap-2">
            <NavLink to="/staff" end className={nav}>Cases</NavLink>
            <NavLink to="/staff/units/unit_4b" className={nav}>Unit 4b</NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-4">
            {USE_FIXTURES && <span className="rounded-pill bg-warning-soft px-3 py-1 text-xs font-semibold text-warning">fixtures</span>}
            <LiveDot />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1600px] px-gutter py-section lg:px-section">{children}</main>
      {DEMO && <DemoControls />}
    </div>
  )
}

export function PartnerLayout({ partnerName, partnerId, children }: { partnerName?: string; partnerId: string; children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-plum text-on-plum">
        <div className="mx-auto flex max-w-3xl items-center gap-4 px-gutter py-3">
          <Link to={`/partner/${partnerId}`} className="min-w-0">
            <div className="font-serif text-xl font-semibold leading-tight">Debye</div>
            <div className="truncate text-sm opacity-80">Jobs for {partnerName ?? partnerId}</div>
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-gutter py-6">{children}</main>
      {DEMO && <DemoControls />}
    </div>
  )
}
