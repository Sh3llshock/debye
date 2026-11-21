// Shared bits of the v3 partner portal (docs/design/v3/partner-portal1.html).
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Icon } from '../../components/icons'
import { api } from '../../api/client'
import type { JobDetail, JobSummary, Slot } from '../../api/types'
import { errorText, explainCodes, jobTitle } from '../../lib/errors'
import { floorLabel, fmtEur, fmtSlot } from '../../lib/format'
import { locale, t } from '../../lib/i18n'
import { useStream } from '../../lib/stream'
import { useDebounced } from '../../lib/useResource'

// ---------- job groups (status → portal tab) ----------
export const NEW = ['requested']
export const WIP = ['accepted', 'reopened', 'slots_proposed', 'awaiting_technician', 'scheduled', 'in_progress']
export const DONE = ['completed', 'invoiced', 'closed']
export const isNew = (j: JobSummary) => NEW.includes(j.status)
export const isWip = (j: JobSummary) => WIP.includes(j.status)
export const isDone = (j: JobSummary) => DONE.includes(j.status)
/** Accepted but no times sent yet: Debye needs times from the partner. */
export const needsTimes = (j: JobDetail) => (j.status === 'accepted' || j.status === 'reopened') && !j.proposed_slots?.length

/** WIP progress strip: our statuses mapped onto the mockup's five steps. */
export const TRACK: { key: string; label: string }[] = [
  { key: 'times', label: 'Time proposed' },
  { key: 'picked', label: 'Tenant picked' },
  { key: 'booked', label: 'Booked' },
  { key: 'site', label: 'On site' },
  { key: 'done', label: 'Completed' },
]
export function trackIndex(status: string): number {
  if (status === 'accepted' || status === 'reopened' || status === 'slots_proposed') return 0
  if (status === 'awaiting_technician') return 1
  if (status === 'scheduled') return 2
  if (status === 'in_progress') return 3
  return 4
}
export function stageLabel(j: JobSummary): string {
  if ((j.status === 'accepted' || j.status === 'reopened') && !j.slot) return t('Pick times')
  return t(TRACK[trackIndex(j.status)].label)
}

// ---------- data: summaries + details of every job, live via SSE ----------
export function usePartnerJobs(pid: string) {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null)
  const [details, setDetails] = useState<Record<string, JobDetail>>({})
  const [error, setError] = useState<string | null>(null)
  const alive = useRef(true)
  const load = async () => {
    try {
      const list = await api.jobs(pid)
      if (!alive.current) return
      setJobs(list)
      setError(null)
      const shown = list.filter((j) => j.status !== 'declined' && j.status !== 'partner_declined')
      const got = await Promise.all(shown.map((j) => api.job(pid, j.case_id).catch(() => null)))
      if (!alive.current) return
      const map: Record<string, JobDetail> = {}
      got.forEach((d) => d && (map[d.case_id] = d))
      setDetails(map)
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e))
    }
  }
  useEffect(() => {
    alive.current = true
    setJobs(null)
    setDetails({})
    load()
    return () => {
      alive.current = false
    }
  }, [pid]) // eslint-disable-line react-hooks/exhaustive-deps
  const refetch = useDebounced(load, 300)
  useStream(() => refetch())
  const put = (d: JobDetail) => {
    setDetails((m) => ({ ...m, [d.case_id]: d }))
    setJobs((l) => (l ? l.map((j) => (j.case_id === d.case_id ? { ...j, ...d } : j)) : l))
    refetch()
  }
  return { jobs, details, error, reload: load, put }
}

// ---------- formatting ----------
export const eur0 = (n?: number | null) => (n == null ? '–' : fmtEur(n))
export const eur2 = (n?: number | null) => (n == null ? '–' : fmtEur(n, true))
export const title = (j: JobSummary) => jobTitle(j.title, j.error_code, j.error_label)
export const firstName = (n?: string | null) => (n ?? '').split(' ')[0]
export function shortAddress(j: JobSummary) {
  return [(j.address ?? j.postcode ?? '').split(',')[0], j.floor != null ? floorLabel(j.floor) : null].filter(Boolean).join(' · ')
}
export function tradeOf(j: JobSummary): string {
  const ty = (j.type ?? '').replace(/^repair\./, '')
  const map: Record<string, string> = { heating: 'Heating', plumbing: 'Plumbing', electrical: 'Electrical', hot_water: 'Hot water' }
  return t(map[ty] ?? (ty ? ty.charAt(0).toUpperCase() + ty.slice(1).replace(/_/g, ' ') : 'Repair'))
}
export function urgencyPill(priority: string) {
  return priority === 'urgent' || priority === 'high'
    ? { cls: 'bg-wine-tint text-wine', text: t('High urgency · within 24 h') }
    : { cls: '', text: t('Normal') }
}
/** "received Today, 09:02" / "received Thu" */
export function received(iso?: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  const today = new Date()
  const tm = d.toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Berlin' })
  if (d.toDateString() === today.toDateString()) return `${t('Today')}, ${tm}`
  return d.toLocaleDateString(locale(), { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Europe/Berlin' })
}
/** Cost cap: the estimate rounded up with ~7 % headroom, as in the mockup. */
export const costCap = (est?: number | null) => (est == null ? null : Math.ceil((est * 1.07) / 10) * 10)

// ---------- price check (invoice) ----------
export function priceCheck(pc: unknown): 'ok' | 'flagged' | 'unknown' {
  if (!pc) return 'unknown'
  if (typeof pc === 'string') return pc.toLowerCase().startsWith('ok') ? 'ok' : 'flagged'
  const o = pc as Record<string, unknown>
  const r = String(o.result ?? o.status ?? (o.ok === true ? 'ok' : ''))
  return r === 'ok' ? 'ok' : r === 'flagged' ? 'flagged' : 'unknown'
}

// ---------- small UI ----------
export function Pill({ cls = '', children }: { cls?: string; children: ReactNode }) {
  return <span className={`pill ${cls}`}>{children}</span>
}

export function Head({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-[22px] flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-page font-bold">{title}</h1>
        {sub && <p className="mt-1 text-[15px] leading-[22px] text-secondary">{sub}</p>}
      </div>
      {right}
    </div>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`card ${className}`}>{children}</section>
}

export function CardTitle({ children, right, className = '' }: { children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <h3 className={`mb-3 flex items-center justify-between gap-2 text-[17px] font-semibold ${className}`}>
      <span className="min-w-0">{children}</span>
      {right}
    </h3>
  )
}

export function Empty({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`p-8 text-center text-muted ${className}`}>{children}</div>
}

/** Photo area: the tenant's photo if shared, else the boiler with its display (the mockup's "shot"). */
export function Shot({ job, className = 'h-[130px]' }: { job: JobDetail; className?: string }) {
  const photo = job.photos?.find((p) => !p.filename.startsWith('after'))
  const code = job.error_code ?? job.asset?.error_code
  return (
    <div className={`relative grid place-items-center overflow-hidden rounded-tile bg-beige-d shadow-ring ${className}`}>
      {photo ? (
        <img src={photo.url} alt={photo.filename} className="absolute inset-0 h-full w-full object-cover" />
      ) : code ? (
        // TODO(slop:F13) deliberate boiler illustration, or use public/demo-media/boiler_display_F28.jpg; tokens swapped in as stopgap
        <div className="grid h-[76px] w-[110px] place-items-center rounded-[10px] bg-cream shadow-card">
          <div className="rounded-[6px] border-[3px] border-muted bg-photo-display px-[9px] py-[3px] font-mono text-[18px] font-bold tracking-[2px] text-photo-bg">{code}</div>
        </div>
      ) : (
        <div className="h-[88px] w-[88px] rounded-full bg-cream shadow-card" /> /* TODO(slop:F13) placeholder tile: flat beige-d with boiler <Icon>, no blob */
      )}
    </div>
  )
}

/** Key/value list in the job card (dt 130px). */
export function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="m-0 grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-2 sm:grid-cols-[130px_minmax(0,1fr)]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="m-0 font-medium [overflow-wrap:anywhere]">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

/** The job facts block (device, display, address, contact, time, cost cap). */
export function jobRows(job: JobDetail, opts: { time?: ReactNode } = {}): [string, ReactNode][] {
  const a = job.asset
  const code = job.error_code ?? a?.error_code
  const rows: [string, ReactNode][] = []
  if (a) rows.push([t('Device'), `${a.make} ${a.model}${a.installed ? ` (${a.installed.slice(0, 4)})` : ''}`])
  if (code) rows.push([t('Display'), errorText(code, job.error_label ?? a?.error_label, a?.error_meaning, true) ?? code])
  rows.push([
    t('Address'),
    job.address ? (
      `${job.address}${job.floor != null ? `, ${floorLabel(job.floor)}` : ''}`
    ) : (
      <span className="text-muted">{t("Shared after the tenant's consent")}</span>
    ),
  ])
  if (job.tenant?.name || job.tenant?.phone)
    rows.push([
      t('Contact'),
      <>
        {firstName(job.tenant?.name) || t('Tenant')}
        {job.tenant?.phone && (
          <>
            {' · '}
            <a className="text-wine hover:underline" href={`tel:${job.tenant.phone}`}>
              {job.tenant.phone}
            </a>
          </>
        )}
      </>,
    ])
  if (opts.time !== undefined) rows.push([t('Time'), opts.time])
  if (job.approval?.granted) rows.push([t('Approved'), approvalLine(job)])
  const cap = costCap(job.estimated_cost_eur)
  if (cap != null) rows.push([t('Cost cap'), `${eur2(cap)} ${t('incl. VAT')}`])
  return rows
}

export function approvalLine(job: JobDetail): string {
  const a = job.approval
  if (!a?.granted) return ''
  const staff = a.text?.match(/\(([^)]+)\)/)?.[1] ?? a.granted_by
  if (a.text?.startsWith('Approved automatically')) return t('Approved automatically (under the owner’s limit)')
  return staff ? t('Repair approved by the property manager ({name})', { name: staff }) : t('Repair approved by the property manager')
}

/** "What the tenant told us" + "How we got to the diagnosis" (from the case summary and events). */
export function Story({ job, bordered = true }: { job: JobDetail; bordered?: boolean }) {
  const lines = [job.summary, job.symptoms, job.description]
    .filter((x): x is string => !!x)
    .flatMap((x) => x.split(/(?<=[.!?])\s+/))
    .map((x) => explainCodes(x.trim()))
    .filter(Boolean)
  const uniq = [...new Set(lines)].slice(0, 5)
  const code = job.error_code ?? job.asset?.error_code
  const label = job.error_label ?? job.asset?.error_label
  const events = (job.events ?? []).filter((e) => e.actor === 'debye' || e.actor === 'tenant').slice(-8)
  if (!uniq.length && !code && !events.length) return null
  return (
    <div className={`grid grid-cols-1 gap-6 px-5 py-[18px] lg:grid-cols-2 ${bordered ? 'border-t border-line' : ''}`}>
      <div className="min-w-0">
        <h4 className="mb-2.5 text-[15px] font-semibold">{t('What the tenant told us')}</h4>
        {uniq.length ? (
          <ul className="m-0 list-disc pl-[18px] leading-[1.55] text-secondary">
            {uniq.map((s) => (
              <li key={s} className="mt-1 first:mt-0">
                {s}
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-muted">{t('No summary yet.')}</p>
        )}
        {events.length > 0 && (
          <details className="group mt-3">
            <summary className="cursor-pointer list-none font-medium text-wine">
              <Icon name="chevron" className="mr-2 inline-block h-4 w-4 align-[-3px] transition-transform group-open:rotate-90" />
              {t('Show the case history ({n} steps)', { n: events.length })}
            </summary>
            <div className="mt-2.5 flex max-h-[300px] flex-col gap-[5px] overflow-y-auto rounded-tile bg-chat-bg p-3">
              {events.map((e, i) => (
                <div key={i} className={`max-w-[85%] rounded-[16px] px-[11px] py-[7px] leading-[1.4] shadow-bubble ${e.actor === 'tenant' ? 'self-end bg-chat-out' : 'bg-surface'}`}>
                  <span className="block text-[10px] font-medium text-muted">{e.actor === 'tenant' ? t('Tenant') : 'Debye'}</span>
                  {e.summary}
                </div>
              ))}
            </div>
          </details>
        )}
      </div>
      <div className="min-w-0">
        <h4 className="mb-2.5 text-[15px] font-semibold">{t('How we got to the diagnosis')}</h4>
        <div className="mb-2.5 flex items-center justify-between gap-2.5 rounded-[12px] bg-bg px-3.5 py-3">
          <b className="min-w-0">{code ? (errorText(code, label, job.asset?.error_meaning) ?? code) : title(job)}</b>
        </div>
        <ol className="m-0 list-none p-0">
          {code && <Reason ok head={t('Display shows {code}', { code })} body={errorText(code, label, job.asset?.error_meaning) ?? ''} />}
          {job.asset && <Reason ok head={t('Device known from the records')} body={`${job.asset.make} ${job.asset.model}`} />}
          {(job.photos?.length ?? 0) > 0 && <Reason ok head={t('Photo from the tenant')} body={t('Shared with the job')} />}
          {job.approval?.granted && <Reason ok head={t('Approved')} body={approvalLine(job)} />}
        </ol>
      </div>
    </div>
  )
}

function Reason({ ok, head, body }: { ok: boolean; head: string; body: string }) {
  return (
    <li className="grid grid-cols-[24px_1fr] gap-2.5 border-t border-line py-2 leading-[1.4] text-secondary first:border-t-0">
      <span className={`grid h-5 w-5 place-items-center rounded-full text-[10px] font-bold ${ok ? 'bg-ok text-cream' : 'bg-beige text-muted'}`}>{ok ? <Icon name="check" className="h-3 w-3" /> : <span aria-hidden>{/* TODO(slop:F9) icon: close (new path in icons.tsx) */}–</span>}</span>
      <span>
        <b className="font-semibold text-ink">{head}</b>
        {body && (
          <>
            <br />
            {body}
          </>
        )}
      </span>
    </li>
  )
}

/** Slot label for chips: "Sun 22 Nov 10:00–12:00". */
export const slotText = (s: Slot) => fmtSlot(s)

/** Small toast at the bottom, as in the mockup. */
export function useToast(): [ReactNode, (s: string) => void] {
  const [msg, setMsg] = useState<string | null>(null)
  const timer = useRef<number>()
  const show = (s: string) => {
    setMsg(s)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setMsg(null), 2400)
  }
  const node = (
    <div
      role="status"
      className={`pointer-events-none fixed bottom-7 left-1/2 z-50 max-w-[90vw] -translate-x-1/2 rounded-tile bg-ink px-5 py-3 font-medium text-cream shadow-pop transition-opacity duration-200 ${msg ? 'opacity-100' : 'opacity-0'}`}
    >
      {msg}
    </div>
  )
  return [node, show]
}

/** Check-pill (the mockup's .cb). */
export function CheckPill({ on, onClick, children, disabled }: { on: boolean; onClick: () => void; children: ReactNode; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={on}
      className={`flex items-center gap-2 rounded-full px-3.5 py-2 font-medium transition-colors disabled:cursor-default disabled:opacity-50 ${on ? 'bg-wine text-cream' : 'bg-beige text-ink hover:bg-beige-d'}`}
    >
      {children}
    </button>
  )
}

// ---------- demo login ----------
export type Session = { pid: string; name?: string }
const SKEY = 'debye-partner-session'
export function getSession(): Session | null {
  try {
    return JSON.parse(sessionStorage.getItem(SKEY) ?? 'null')
  } catch {
    return null
  }
}
export function setSession(s: Session | null) {
  try {
    if (s) sessionStorage.setItem(SKEY, JSON.stringify(s))
    else sessionStorage.removeItem(SKEY)
  } catch {
    /* private mode */
  }
}

/** Locally saved registration/profile details (VAT, IBAN, …) that the backend manifest does not keep. */
const PKEY = (pid: string) => `debye-partner-profile:${pid}`
export function loadLocalProfile(pid: string): Record<string, unknown> | null {
  try {
    return JSON.parse(localStorage.getItem(PKEY(pid)) ?? 'null')
  } catch {
    return null
  }
}
export function saveLocalProfile(pid: string, p: Record<string, unknown>) {
  try {
    localStorage.setItem(PKEY(pid), JSON.stringify(p))
  } catch {
    /* private mode */
  }
}
