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
      <div className="mt-0.5 [overflow-wrap:anywhere] hyphens-auto">{children ?? '—'}</div>
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

/** Debye mark (docs/design/debye-avatar.svg): aubergine circle, white serif "d", lilac spark.
 *  `bare` drops the circle (for the aubergine top bar). */
const MARK_D = 'M113.68 185.54C105.813 185.54 98.8133 183.54 92.68 179.54C86.5467 175.54 81.68 170.007 78.08 162.94C74.6133 155.74 72.88 147.673 72.88 138.74C72.88 129.673 74.6133 121.607 78.08 114.54C81.68 107.473 86.5467 101.94 92.68 97.94C98.8133 93.8067 105.813 91.74 113.68 91.74C120.08 91.74 126.147 93.14 131.88 95.94C137.613 98.74 142.813 102.873 147.48 108.34L145.48 114.34C141.613 109.807 137.413 106.34 132.88 103.94C128.48 101.407 124.013 100.14 119.48 100.14C112.013 100.14 106.213 103.54 102.08 110.34C97.9467 117.007 95.88 126.473 95.88 138.74C95.88 150.74 97.9467 160.14 102.08 166.94C106.213 173.74 112.08 177.14 119.68 177.14C123.813 177.14 127.947 176.073 132.08 173.94C136.347 171.673 140.747 168.273 145.28 163.74L147.88 167.94C142.813 173.807 137.413 178.207 131.68 181.14C126.08 184.073 120.08 185.540 113.68 185.54ZM146.28 185.34L143.68 170.54L141.88 167.14V63.14C141.88 57.2733 140.813 53.14 138.68 50.74C136.68 48.34 133.013 47.0733 127.68 46.94L125.88 46.74V41.14C133.613 41.14 140.28 41.0067 145.88 40.74C151.613 40.34 157.28 39.6733 162.88 38.74V160.54C162.88 166.94 163.947 171.34 166.08 173.74C168.213 176.007 172.213 177.273 178.08 177.54V183.14H172.08C167.28 183.14 162.813 183.273 158.68 183.54C154.68 183.940 150.547 184.54 146.28 185.34Z'
const MARK_SPARK = 'M207.36 20.48L214.963 51.2772L245.76 58.88L214.963 66.4828L207.36 97.28L199.757 66.4828L168.96 58.88L199.757 51.2772L207.36 20.48Z'
export function DebyeMark({ size = 40, bare }: { size?: number; bare?: boolean; onDark?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 256 256" role="img" aria-label="Debye" className="shrink-0">
      {!bare && <circle cx="128" cy="128" r="128" className="fill-plum" />}
      <path d={MARK_D} className="fill-on-plum" />
      <path d={MARK_SPARK} className="fill-lilac" />
    </svg>
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

/** Designer's mascot (docs/design/mascot, downscaled copies in public/mascot). */
const MASCOT = {
  waving: '/mascot/debye-mascot-waving.png',
  'thumbs-up': '/mascot/debye-mascot-thumbs-up.png',
  avatar: '/mascot/debye-mascot-whatsapp.png',
} as const
export function Mascot({ pose, className = '', alt = 'Debye' }: { pose: keyof typeof MASCOT; className?: string; alt?: string }) {
  return <img src={MASCOT[pose]} alt={alt} draggable={false} className={`select-none ${className}`} />
}
