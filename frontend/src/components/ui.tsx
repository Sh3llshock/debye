import type { ReactNode } from 'react'
import { chipColors, type ChipTone } from '../theme'
import { statusInfo } from '../lib/format'
import { Icon } from './icons'

/** A work area: white with a 1px border; optional header row with a bottom rule. */
export function Panel({ title, meta, children, className = '', bodyClass = '' }: { title?: ReactNode; meta?: ReactNode; children: ReactNode; className?: string; bodyClass?: string }) {
  return (
    <section className={`panel overflow-hidden ${className}`}>
      {(title || meta) && (
        <header className="panel-head">
          {title && <h2 className="text-panel">{title}</h2>}
          {meta && <div className="text-label text-muted">{meta}</div>}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  )
}

export function Chip({ tone = 'neutral', children }: { tone?: ChipTone; children: ReactNode }) {
  const c = chipColors[tone]
  return (
    <span className="inline-flex items-center whitespace-nowrap rounded-chip px-2.5 py-[3px] text-label font-semibold" style={{ color: c.fg, backgroundColor: c.bg }}>
      {children}
    </span>
  )
}

export function StatusChip({ status }: { status: string }) {
  const s = statusInfo(status)
  return <Chip tone={s.tone}>{s.label}</Chip>
}

/** Only urgent gets a chip; everything else is plain text (colour only where it means something). */
export function PriorityChip({ priority }: { priority: string }) {
  if (priority === 'urgent') return <Chip tone="negative">Urgent</Chip>
  if (priority === 'high') return <Chip tone="warning">High</Chip>
  return <span className="text-secondary">{priority.charAt(0).toUpperCase() + priority.slice(1)}</span>
}

/** Inspector property row: label column + value. */
export function Prop({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-3 py-1.5">
      <dt className="text-label text-muted">{label}</dt>
      <dd className="text-body-sm text-ink [overflow-wrap:anywhere]">{children ?? '—'}</dd>
    </div>
  )
}

export function Loading({ what = 'Loading' }: { what?: string }) {
  return <div className="p-8 text-center text-muted">{what}…</div>
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="rounded-panel border border-negative bg-negative-soft p-5 text-negative">
      <div className="font-semibold">Something went wrong</div>
      <div className="mt-1 text-secondary">{error}</div>
      {onRetry && (
        <button className="btn-secondary mt-4" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-5 py-8 text-center text-body-sm text-muted">{children}</div>
}

/** Designer's v2 mascot (docs/design/v2/mascot, downscaled copies in public/mascot). */
const MASCOT = {
  waving: '/mascot/waving.png',
  'thumbs-up': '/mascot/thumbs-up.png',
  thinking: '/mascot/thinking.png',
  avatar: '/mascot/avatar.png',
} as const
export function Mascot({ pose, className = '', alt = 'Debye' }: { pose: keyof typeof MASCOT; className?: string; alt?: string }) {
  return <img src={MASCOT[pose]} alt={alt} draggable={false} className={`select-none ${className}`} />
}

const ACTOR_LABEL: Record<string, string> = { debye: 'Debye', tenant: 'Resident', partner: 'Installer', staff: 'Property manager', pm: 'Property manager', system: 'System' }
export function actorInfo(a: string) {
  return { label: ACTOR_LABEL[a] ?? 'System' }
}
const ACTOR_ICON: Record<string, string> = { tenant: 'user', partner: 'wrench', staff: 'briefcase', pm: 'briefcase', system: 'gear' }

/** Activity icon: the mascot for Debye, a plain outline icon on a sub-tint for everyone else. */
export function ActorIcon({ actor, size = 28 }: { actor: string; size?: number }) {
  if (actor === 'debye')
    return (
      <span className="inline-flex shrink-0 overflow-hidden rounded-full bg-surface ring-1 ring-line" style={{ width: size, height: size }}>
        <Mascot pose="avatar" alt="Debye" className="h-full w-full object-cover" />
      </span>
    )
  return (
    <span className="inline-flex shrink-0 items-center justify-center rounded-full bg-sub text-secondary" style={{ width: size, height: size }} title={actorInfo(actor).label}>
      <Icon name={ACTOR_ICON[actor] ?? 'gear'} className="h-4 w-4" />
    </span>
  )
}

export function JsonView({ value }: { value: unknown }) {
  return <pre className="max-h-[360px] overflow-auto rounded border border-line bg-sub p-3 text-meta text-ink">{JSON.stringify(value, null, 2)}</pre>
}
