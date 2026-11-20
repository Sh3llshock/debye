import type { ReactNode } from 'react'
import { actorColors, priorityColors, statusColors, type StatusTone } from '../theme'
import { statusInfo } from '../lib/format'

export function Card({ title, action, children, className = '', tone }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; tone?: 'warning' | 'success' | 'inverse' }) {
  const toneCls =
    tone === 'inverse' ? 'border-plum bg-plum text-on-plum' : tone === 'warning' ? 'border-warning bg-warning-soft' : tone === 'success' ? 'border-success bg-success-soft' : 'border-line bg-surface'
  return (
    <section className={`rounded-card border p-card-sm shadow-card ${toneCls} ${className}`}>
      {(title || action) && (
        <header className="mb-4 flex items-center justify-between gap-4">
          {title && <h2 className={`text-xl ${tone === 'inverse' ? '!text-on-plum' : ''}`}>{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

const TONE: Record<StatusTone, string> = {
  neutral: 'bg-surface-alt text-muted border-line',
  info: 'bg-info-soft text-info border-info',
  warning: 'bg-warning-soft text-warning border-warning',
  success: 'bg-success-soft text-success border-success',
  danger: 'bg-danger-soft text-danger border-danger',
  plum: 'bg-violet-soft text-plum border-plum',
}

export function Pill({ tone = 'neutral', children, big }: { tone?: StatusTone; children: ReactNode; big?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-2 whitespace-nowrap rounded-pill border font-semibold ${big ? 'px-4 py-1 text-body-sm' : 'px-3 py-0.5 text-sm'} ${TONE[tone]}`}>
      {children}
    </span>
  )
}

/** tokens component.statusPill: full radius, 8px dot in fg, label in fg on bg. */
export function StatusPill({ status, big }: { status: string; big?: boolean }) {
  const s = statusInfo(status)
  const c = statusColors[status] ?? statusColors.closed
  return (
    <span
      className={`inline-flex items-center gap-2 whitespace-nowrap rounded-pill font-semibold transition-colors duration-500 ${big ? 'px-4 py-1.5 text-body-sm' : 'px-3 py-0.5 text-sm'}`}
      style={{ color: c.fg, backgroundColor: c.bg }}
    >
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: c.fg }} />
      {s.label}
    </span>
  )
}

export function PriorityPill({ priority }: { priority: string }) {
  const c = priorityColors[priority] ?? priorityColors.normal
  return (
    <span className="inline-flex items-center whitespace-nowrap rounded-pill px-3 py-0.5 text-sm font-semibold" style={{ color: c.fg, backgroundColor: c.bg }}>
      {priority.charAt(0).toUpperCase() + priority.slice(1)}
    </span>
  )
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      <div className="mt-0.5 break-words">{children ?? '—'}</div>
    </div>
  )
}

export function Loading({ what = 'Loading' }: { what?: string }) {
  return <div className="p-section text-center text-lg text-muted">{what}…</div>
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="rounded-card border border-danger bg-danger-soft p-card-sm text-danger">
      <div className="font-semibold">Something went wrong</div>
      <div className="mt-1">{error}</div>
      {onRetry && <button className="btn-secondary mt-4" onClick={onRetry}>Try again</button>}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded border border-dashed border-line p-card-sm text-center text-body-sm text-muted">{children}</div>
}

const ACTOR_LABEL: Record<string, string> = { debye: 'Debye', tenant: 'Resident', partner: 'Installer', staff: 'Property manager', pm: 'Property manager', system: 'System' }

export function actorInfo(a: string) {
  return { label: ACTOR_LABEL[a] ?? 'System' }
}

/** Debye mark: aubergine circle, white serif "d", violet spark top right. */
export function DebyeMark({ size = 40, onDark }: { size?: number; onDark?: boolean }) {
  return (
    <span
      title="Debye"
      className={`relative inline-flex shrink-0 items-center justify-center rounded-full bg-plum font-serif font-semibold leading-none text-on-plum ${onDark ? "ring-2 ring-line-on-plum" : ""}`}
      style={{ width: size, height: size, fontSize: size * 0.62 }}
    >
      <span style={{ marginTop: -size * 0.08 }}>d</span>
      <span className="absolute rounded-full bg-violet" style={{ width: size * 0.22, height: size * 0.22, top: size * 0.04, right: size * 0.04 }} />
    </span>
  )
}

const ICON_PATHS: Record<string, string> = {
  tenant: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0', // user
  partner: 'M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17v3h3l5.3-5.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4 2.5-2.5Z', // wrench
  staff: 'M4 8h16v11H4zM9 8V5h6v3M4 13h16', // briefcase
  system:
    'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7.5 7.5 0 0 0-2-1.2L14.5 3h-5l-.4 2.6a7.5 7.5 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7.5 7.5 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7.5 7.5 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z', // gear
}
ICON_PATHS.pm = ICON_PATHS.staff

/** tokens color.actor: 40px circle per actor. */
export function ActorIcon({ actor, size = 40 }: { actor: string; size?: number }) {
  if (actor === 'debye') return <DebyeMark size={size} />
  const c = actorColors[actor] ?? actorColors.system
  const d = ICON_PATHS[actor] ?? ICON_PATHS.system
  return (
    <span title={actorInfo(actor).label} className="inline-flex shrink-0 items-center justify-center rounded-full" style={{ width: size, height: size, backgroundColor: c.bg, color: c.fg }}>
      <svg viewBox="0 0 24 24" width={size * 0.55} height={size * 0.55} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d={d} />
      </svg>
    </span>
  )
}

export function JsonView({ value }: { value: unknown }) {
  return <pre className="max-h-[480px] overflow-auto rounded-lg bg-plum-dark p-4 font-mono text-sm text-on-plum">{JSON.stringify(value, null, 2)}</pre>
}
