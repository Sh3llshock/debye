import type { ReactNode } from 'react'
import type { StatusTone } from '../theme'
import { statusInfo } from '../lib/format'

export function Card({ title, action, children, className = '', tone }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; tone?: 'warning' | 'success' }) {
  const toneCls = tone === 'warning' ? 'border-warning bg-warning-soft' : tone === 'success' ? 'border-success bg-success-soft' : 'border-line bg-surface'
  return (
    <section className={`rounded-card border shadow-card p-card ${toneCls} ${className}`}>
      {(title || action) && (
        <header className="mb-4 flex items-center justify-between gap-4">
          {title && <h2 className="text-xl">{title}</h2>}
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
  plum: 'bg-plum-soft text-plum border-plum',
}

export function Pill({ tone = 'neutral', children, big }: { tone?: StatusTone; children: ReactNode; big?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-2 whitespace-nowrap rounded-pill border font-semibold ${big ? 'px-4 py-1 text-lg' : 'px-3 py-0.5 text-sm'} ${TONE[tone]}`}>
      {children}
    </span>
  )
}

export function StatusPill({ status, big }: { status: string; big?: boolean }) {
  const s = statusInfo(status)
  return <Pill tone={s.tone} big={big}>{s.label}</Pill>
}

export function PriorityPill({ priority }: { priority: string }) {
  const tone: StatusTone = priority === 'urgent' ? 'danger' : priority === 'high' ? 'warning' : 'neutral'
  return <Pill tone={tone}>{priority === 'urgent' ? '● Urgent' : priority.charAt(0).toUpperCase() + priority.slice(1)}</Pill>
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
    <div className="rounded-card border border-danger bg-danger-soft p-card text-danger">
      <div className="font-semibold">Something went wrong</div>
      <div className="mt-1">{error}</div>
      {onRetry && <button className="btn-secondary mt-4" onClick={onRetry}>Try again</button>}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded border border-dashed border-line p-card text-center text-muted">{children}</div>
}

const ACTOR: Record<string, { icon: string; label: string; cls: string }> = {
  debye: { icon: '✦', label: 'Debye', cls: 'bg-plum text-on-plum' },
  tenant: { icon: '👤', label: 'Resident', cls: 'bg-info-soft text-info' },
  partner: { icon: '🔧', label: 'Installer', cls: 'bg-warning-soft text-warning' },
  staff: { icon: '🏢', label: 'Property manager', cls: 'bg-success-soft text-success' },
  pm: { icon: '🏢', label: 'Property manager', cls: 'bg-success-soft text-success' },
  system: { icon: '⚙', label: 'System', cls: 'bg-surface-alt text-muted' },
}
export function actorInfo(a: string) {
  return ACTOR[a] ?? ACTOR.system
}
export function ActorIcon({ actor, size = 'md' }: { actor: string; size?: 'md' | 'lg' }) {
  const a = actorInfo(actor)
  const s = size === 'lg' ? 'h-12 w-12 text-xl' : 'h-10 w-10 text-lg'
  return (
    <span title={a.label} className={`inline-flex shrink-0 items-center justify-center rounded-full font-semibold ${s} ${a.cls}`}>
      {a.icon}
    </span>
  )
}

export function JsonView({ value }: { value: unknown }) {
  return (
    <pre className="max-h-[480px] overflow-auto rounded bg-plum-dark p-4 font-mono text-sm text-on-plum">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}
