import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, DEMO } from '../api/client'
import type { JobDetail, JobSummary, Slot, Technician } from '../api/types'
import { InvoiceFields, priceCheckInfo, ServiceLine } from '../components/case/CasePanels'
import { Icon } from '../components/icons'
import { Chip, ErrorBox, Loading, Mascot } from '../components/ui'
import { errorLabel, errorText, explainCodes, jobTitle } from '../lib/errors'
import { floorLabel, fmtDateTime, fmtEur, fmtSlot, fmtTime, maskPhone } from '../lib/format'
import { locale, t } from '../lib/i18n'
import { lineState, PARTNER_STATIONS } from '../lib/lifecycle'
import { useStream } from '../lib/stream'
import { useDebounced, useResource } from '../lib/useResource'

const FIELD_LABEL: Record<string, string> = { name: 'name', phone: 'phone', address: 'address', unit_floor: 'floor', photos: 'photo' }

export function JobPanel({ partnerId, caseId, staffName, jobs }: { partnerId: string; caseId: string; staffName?: string; jobs: JobSummary[] }) {
  const { data: job, setData, error, reload } = useResource(() => api.job(partnerId, caseId), [partnerId, caseId])
  const refetch = useDebounced(reload, 250)
  useStream((m) => {
    if (!m.case_id || m.case_id === caseId) refetch()
  })
  if (error && !job) return <ErrorBox error={error} onRetry={reload} />
  if (!job)
    return (
      <div className="panel">
        <Loading what={t('Loading job')} />
      </div>
    )
  return <JobView job={job} partnerId={partnerId} staffName={staffName} jobs={jobs} onChange={setData} />
}

export function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-4 border-b border-line py-3 last:border-b-0">
      <dt className="text-label text-muted">{label}</dt>
      <dd className="[overflow-wrap:anywhere]">{children}</dd>
    </div>
  )
}

/** Job facts shared by the partner (dispatcher) and technician pages: only what the API returns. */
export function JobFacts({ job, extra }: { job: JobDetail; extra?: ReactNode }) {
  const asset = job.asset
  const code = job.error_code ?? asset?.error_code
  const label = job.error_label ?? asset?.error_label
  const tenantPhoto = job.photos?.find((p) => !p.filename.startsWith('after'))
  const fields = job.consented_fields ?? []
  const who = job.tenant?.name?.split(' ')[0] ?? t('the resident')
  const [street, city] = (job.address ?? '').split(',').map((x) => x.trim())
  const short = errorText(code, label, asset?.error_meaning, true)
  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-[minmax(0,1fr)_240px]">
      <div className="min-w-0">
        {(job.summary || job.description) && <p className="mb-3 text-body text-secondary">{explainCodes(job.summary ?? job.description ?? '')}</p>}
        <dl>
          <Row label={t('Address')}>{job.address ? [street, city].filter(Boolean).join(', ') : <span className="text-muted">{t("shared after the resident's consent")}</span>}</Row>
          <Row label={t('Where')}>{floorLabel(job.floor)}</Row>
          {asset && (
            <Row label={t('Boiler')}>
              {asset.make} {asset.model}
              {asset.installed ? `, ${asset.installed.slice(0, 4)}` : ''}
              {asset.last_service ? `, ${t('last serviced {date}', { date: new Date(asset.last_service).toLocaleDateString(locale(), { month: 'short', year: 'numeric' }) })}` : ''}
            </Row>
          )}
          {code && (
            <Row label={t('Error')}>
              <span className="font-semibold">{errorText(code, label, asset?.error_meaning)}</span>
              {asset?.error_meaning && !asset.error_meaning.toLowerCase().startsWith((errorLabel(code, label) ?? '~').toLowerCase()) && <span className="text-secondary"> · {asset.error_meaning}</span>}
            </Row>
          )}
          {job.tenant && (
            <Row label={t('Resident')}>
              {job.tenant.name}
              {job.tenant.phone && (
                <>
                  {' · '}
                  <a href={`tel:${job.tenant.phone}`} className="text-action hover:underline">
                    {maskPhone(job.tenant.phone)}
                  </a>
                </>
              )}
            </Row>
          )}
          {extra}
        </dl>
        <div className="mt-3 flex items-start gap-2 text-label text-secondary">
          <Icon name="shield" className="mt-0.5 h-4 w-4 shrink-0 text-positive" />
          <span>
            {fields.length
              ? t("Shared with {who}'s consent on WhatsApp: {fields}. Nothing beyond these fields.", { who, fields: fields.map((f) => t(FIELD_LABEL[f] ?? f)).join(', ') })
              : t('No personal data shared yet. Debye asks the resident first.')}
          </span>
        </div>
      </div>
      <figure>
        <div className="relative flex aspect-[4/3] items-center justify-center overflow-hidden rounded bg-photo-bg">
          {tenantPhoto ? (
            <img src={tenantPhoto.url} alt={tenantPhoto.filename} className="absolute inset-0 h-full w-full object-cover" />
          ) : (
            code && <span className="rounded bg-photo-display px-4 py-2 text-stat font-semibold text-ink">{code}</span>
          )}
        </div>
        <figcaption className="mt-2 text-meta text-muted">
          {tenantPhoto ? t('Photo from {who}', { who }) : t('No photo shared')}
          {short ? ` · ${t('display shows {error}', { error: short })}` : ''}
        </figcaption>
      </figure>
    </div>
  )
}

type ActionProps = { job: JobDetail; partnerId: string; staffName?: string; jobs: JobSummary[]; onChange: (j: JobDetail) => void }

function JobView(props: ActionProps) {
  const { job } = props
  const asset = job.asset
  const code = job.error_code ?? asset?.error_code
  const label = job.error_label ?? asset?.error_label
  const line = lineState(PARTNER_STATIONS, job.status, job.events ?? [], true)
  const tech = job.technician

  return (
    <section className="panel overflow-hidden">
      <div className="border-b border-line px-5 pb-6 pt-8 lg:px-work">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-page">{jobTitle(job.title, code, label, asset?.error_meaning)}</h1>
            {job.priority === 'urgent' && <Chip tone="negative">{t('Urgent')}</Chip>}
          </div>
          <div className="text-body-sm text-secondary">
            {job.case_id}
            {job.created_at ? ` · ${fmtDateTime(job.created_at)}` : ''}
          </div>
        </div>
        <div className="mt-6 sm:mt-8">
          <ServiceLine line={line} />
        </div>
      </div>

      <div className="flex flex-col">
        <div className="order-2 border-b border-line px-5 py-6 md:order-none lg:px-work">
          <JobFacts
            job={job}
            extra={
              tech && (
                <Row label={t('Technician')}>
                  {tech.name}{' '}
                  <Link to={`/tech/${tech.tech_id}`} className="ml-2 text-label font-semibold text-action hover:underline">
                    {t('Open as {name}', { name: tech.name.split(' ')[0] })} →
                  </Link>
                </Row>
              )
            }
          />
        </div>
        <div className="order-1 border-b border-line px-5 py-6 md:order-none md:border-b-0 lg:px-work">
          <Actions {...props} />
        </div>
      </div>
    </section>
  )
}

function useAction(onChange: (j: JobDetail) => void) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const run = async (fn: () => Promise<JobDetail>) => {
    setBusy(true)
    setErr(null)
    try {
      onChange(await fn())
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return { busy, err, run }
}

export function Err({ err }: { err: string | null }) {
  return err ? <div className="mt-3 rounded border border-negative bg-negative-soft p-3 text-negative">{err}</div> : null
}

function Actions(props: ActionProps) {
  const { job } = props
  const s = job.status
  if (s === 'requested') return <AcceptDecline {...props} />
  if (s === 'accepted' || s === 'reopened') return job.proposed_slots?.length ? <TimesOffered job={job} /> : <Dispatch {...props} />
  if (s === 'slots_proposed') return <TimesOffered job={job} />
  if (s === 'awaiting_technician') return <AwaitingTechnician job={job} />
  if (s === 'scheduled' || s === 'in_progress') return <CompleteForm {...props} />
  if (s === 'completed' || s === 'invoiced' || s === 'closed') return <Done {...props} />
  if (s === 'declined' || s === 'partner_declined') return <p className="text-secondary">{t('You declined this job. Debye passed it to the next partner.')}</p>
  return null
}

const DECLINE_REASONS = ['Fully booked', 'Outside service area', 'Not our device type']

function DeclineChoices({ busy, onPick, onCancel }: { busy: boolean; onPick: (r: string) => void; onCancel: () => void }) {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <span className="text-label text-muted">{t('Reason:')}</span>
      {DECLINE_REASONS.map((r) => (
        <button key={r} className="btn-secondary" disabled={busy} onClick={() => onPick(r)}>
          {t(r)}
        </button>
      ))}
      <button className="btn-ghost" onClick={onCancel}>
        {t('Cancel')}
      </button>
    </div>
  )
}

function AcceptDecline({ job, partnerId, onChange }: ActionProps) {
  const { busy, err, run } = useAction(onChange)
  const [declining, setDeclining] = useState(false)
  return (
    <div>
      <h2 className="text-panel">{t('New job from Debye')}</h2>
      <p className="mt-1 text-body-sm text-secondary">
        {job.estimated_cost_eur != null ? t('Framework job, estimate {eur}, approved automatically.', { eur: fmtEur(job.estimated_cost_eur) }) : t('Framework job.')} {t('Accept, then pick a technician and offer visit times.')}
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <button className="btn-primary" disabled={busy} onClick={() => run(() => api.accept(partnerId, job.case_id))}>
          {busy ? t('Accepting…') : t('Accept job')}
        </button>
        <button className="btn-secondary" disabled={busy} onClick={() => setDeclining(true)}>
          {t('Decline job')}
        </button>
      </div>
      {declining && <DeclineChoices busy={busy} onPick={(r) => run(() => api.decline(partnerId, job.case_id, r))} onCancel={() => setDeclining(false)} />}
      <Err err={err} />
    </div>
  )
}

// ---- dispatcher: pick a technician, then 2–3 of HIS free slots ----
function berlinOffset(d: Date): string {
  const part = new Intl.DateTimeFormat('en-US', { timeZone: 'Europe/Berlin', timeZoneName: 'shortOffset' }).formatToParts(d).find((p) => p.type === 'timeZoneName')?.value ?? 'GMT+1'
  const m = part.match(/GMT([+-])(\d+)/)
  return m ? `${m[1]}${m[2].padStart(2, '0')}:00` : '+01:00'
}
const berlinDate = (d: Date) => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Berlin' }).format(d) // YYYY-MM-DD
const WINDOWS: [string, string][] = [
  ['08:00', '10:00'],
  ['10:00', '12:00'],
  ['14:00', '16:00'],
]
const overlaps = (a: Slot, b: Slot) => new Date(a.start) < new Date(b.end) && new Date(a.end) > new Date(b.start)

function Dispatch({ job, partnerId, jobs, onChange }: ActionProps) {
  const { busy, err, run } = useAction(onChange)
  const techs = useResource(() => api.technicians(partnerId).catch(() => [] as Technician[]), [partnerId])
  const [techId, setTechId] = useState<string | null>(null)
  const [picked, setPicked] = useState<Slot[]>([])
  const [declining, setDeclining] = useState(false)
  const who = job.tenant?.name?.split(' ')[0] ?? t('the resident')
  const list = techs.data ?? []

  // Preselect the technician whose skills match the device make, else the first one.
  useEffect(() => {
    if (techId || !list.length) return
    const make = job.asset?.make?.toLowerCase()
    setTechId((list.find((x) => make && x.skills.some((s) => s.toLowerCase().includes(make))) ?? list[0]).tech_id)
  }, [list, techId, job.asset?.make])
  const tech = list.find((x) => x.tech_id === techId) ?? null

  // Grid days: the days the technicians have free slots on (from the API), else the next four working days.
  const freeKey = list.map((x) => x.free_slots.map((f) => f.start).join()).join('|')
  const days = useMemo(() => {
    const dayOf = (d: Date) => ({ date: berlinDate(d), label: d.toLocaleDateString(locale(), { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Europe/Berlin' }), off: berlinOffset(d) })
    const fromApi = [...new Set(list.flatMap((x) => x.free_slots.map((f) => f.start.slice(0, 10))))].sort().slice(0, 4)
    if (fromApi.length) return fromApi.map((date) => dayOf(new Date(`${date}T12:00:00${list[0].free_slots[0].start.slice(19) || '+01:00'}`)))
    const out: ReturnType<typeof dayOf>[] = []
    for (let i = 1; out.length < 4 && i < 10; i++) {
      const d = new Date(Date.now() + i * 86400_000)
      if (new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Berlin', weekday: 'short' }).format(d) === 'Sun') continue
      out.push(dayOf(d))
    }
    return out
  }, [freeKey]) // eslint-disable-line react-hooks/exhaustive-deps

  // With technicians: free = the technician's free slots. Without (older backend): busy = other booked jobs.
  const otherBooked = jobs.filter((j) => j.case_id !== job.case_id && j.slot).map((j) => j.slot!)
  const isBusy = (s: Slot) => (tech ? !tech.free_slots.some((f) => new Date(f.start) <= new Date(s.start) && new Date(f.end) >= new Date(s.end)) : otherBooked.some((b) => overlaps(b, s)))
  const toggle = (s: Slot) => setPicked((p) => (p.some((x) => x.start === s.start) ? p.filter((x) => x.start !== s.start) : p.length >= 3 ? p : [...p, s]))
  const cell = (d: { date: string; off: string }, a: string, b: string): Slot => ({ start: `${d.date}T${a}:00${d.off}`, end: `${d.date}T${b}:00${d.off}` })
  const stateText = (busyCell: boolean, on: boolean) => (busyCell ? t('Busy') : on ? t('Offered') : t('Free'))

  return (
    <div>
      <h2 className="text-panel">{list.length ? t('Pick a technician and visit times') : t('Offer visit times')}</h2>
      <p className="mt-1 text-body-sm text-secondary">{t('Choose two or three times. Debye sends them to {who} on WhatsApp and books the one {who} picks.', { who })}</p>

      {techs.data === null && <Loading what={t('Loading technicians')} />}
      {list.length > 0 && (
        <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2" role="radiogroup" aria-label={t('Technician')}>
          {list.map((x) => {
            const on = x.tech_id === techId
            return (
              <button
                key={x.tech_id}
                role="radio"
                aria-checked={on}
                onClick={() => {
                  setTechId(x.tech_id)
                  setPicked([])
                }}
                className={`flex items-start gap-3 rounded border p-3 text-left transition-colors ${on ? 'border-action bg-action-soft' : 'border-line bg-surface hover:border-action'}`}
              >
                <span className={`mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 ${on ? 'border-action' : 'border-life-upcoming'}`}>{on && <span className="h-2 w-2 rounded-full bg-action" />}</span>
                <span className="min-w-0">
                  <span className="block font-semibold">{x.name}</span>
                  <span className="block text-meta text-secondary">{x.skills.join(' · ')}</span>
                  <span className="block text-meta text-muted">{t('{n} free slots in the next days', { n: x.free_slots.length })}</span>
                </span>
              </button>
            )
          })}
        </div>
      )}

      {/* phone: one row per day, three times each */}
      <div className="mt-4 flex flex-col gap-3 sm:hidden">
        {days.map((d) => (
          <div key={d.date}>
            <div className="mb-1.5 text-label font-medium">{d.label}</div>
            <div className="grid grid-cols-3 gap-2">
              {WINDOWS.map(([a, b]) => {
                const s = cell(d, a, b)
                const busyCell = isBusy(s)
                const on = picked.some((x) => x.start === s.start)
                return (
                  <button
                    key={a}
                    disabled={busyCell}
                    onClick={() => toggle(s)}
                    aria-pressed={on}
                    className={`flex h-14 flex-col items-center justify-center rounded text-label leading-tight transition-colors ${
                      busyCell ? 'cursor-not-allowed bg-sub text-muted' : on ? 'bg-action font-semibold text-on-action' : 'border border-line bg-surface text-ink hover:border-action'
                    }`}
                  >
                    <span className="font-medium">
                      {a.slice(0, 2)}–{b.slice(0, 2)}
                    </span>
                    <span className="text-meta">{stateText(busyCell, on)}</span>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>
      {/* tablet and up: week grid table */}
      <div className="mt-4 hidden overflow-x-auto rounded border border-line sm:block">
        <table className="w-full min-w-[560px] table-fixed text-left">
          <thead className="bg-sub">
            <tr className="text-label text-muted">
              <th className="w-[140px] px-4 py-3 font-medium">{tech ? tech.name.split(' ')[0] : t('Time')}</th>
              {days.map((d) => (
                <th key={d.date} className="px-2 py-3 font-medium text-ink">
                  {d.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {WINDOWS.map(([a, b]) => (
              <tr key={a} className="border-t border-line">
                <td className="whitespace-nowrap px-4 py-2 font-medium">
                  {a}–{b}
                </td>
                {days.map((d) => {
                  const s = cell(d, a, b)
                  const busyCell = isBusy(s)
                  const on = picked.some((x) => x.start === s.start)
                  return (
                    <td key={d.date} className="px-2 py-2">
                      <button
                        disabled={busyCell}
                        onClick={() => toggle(s)}
                        aria-pressed={on}
                        className={`flex h-10 w-full items-center justify-center gap-1.5 rounded text-label transition-colors ${
                          busyCell ? 'cursor-not-allowed bg-sub text-muted' : on ? 'bg-action font-semibold text-on-action' : 'border border-line bg-surface text-secondary hover:border-action'
                        }`}
                      >
                        {on && <Icon name="check" className="h-4 w-4" />}
                        {stateText(busyCell, on)}
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 flex flex-wrap gap-3">
        <button
          className="btn-primary"
          disabled={busy || picked.length === 0 || (list.length > 0 && !tech)}
          onClick={() => run(() => api.slots(partnerId, job.case_id, [...picked].sort((x, y) => x.start.localeCompare(y.start)), tech?.tech_id))}
        >
          {busy
            ? t('Sending…')
            : picked.length
              ? tech
                ? t('Send {n} times to {who} · {tech}', { n: picked.length, who, tech: tech.name.split(' ')[0] })
                : t('Send {n} times to {who}', { n: picked.length, who })
              : t('Pick a time')}
        </button>
        <button className="btn-secondary" disabled={busy} onClick={() => setDeclining(true)}>
          {t('Decline job')}
        </button>
      </div>
      {declining && <DeclineChoices busy={busy} onPick={(r) => run(() => api.decline(partnerId, job.case_id, r))} onCancel={() => setDeclining(false)} />}
      <Err err={err} />
    </div>
  )
}

function TimesOffered({ job }: { job: JobDetail }) {
  const who = job.tenant?.name?.split(' ')[0] ?? t('the resident')
  return (
    <div className="flex flex-wrap items-center gap-6">
      <div className="min-w-0 flex-1">
        <h2 className="text-panel">{t('Times offered')}</h2>
        {job.technician && <p className="mt-1 text-body-sm text-secondary">{t('Technician: {name}', { name: job.technician.name })}</p>}
        <ul className="mt-3 flex flex-wrap gap-2">
          {job.proposed_slots.map((p) => (
            <li key={p.start} className="inline-flex items-center gap-2 rounded border border-line px-4 py-2">
              <Icon name="calendar" className="h-4 w-4 text-secondary" /> {fmtSlot({ start: p.start, end: p.end })}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-body-sm text-secondary">{t('Waiting for {who} to pick one on WhatsApp. You will see the choice here.', { who })}</p>
      </div>
      <Mascot pose="thinking" alt={t('Debye waiting')} className="h-24 w-24" />
    </div>
  )
}

function AwaitingTechnician({ job }: { job: JobDetail }) {
  const who = job.tenant?.name?.split(' ')[0] ?? t('the resident')
  const tech = job.technician
  const first = tech?.name.split(' ')[0] ?? t('the technician')
  return (
    <div className="flex flex-wrap items-center gap-6">
      <div className="min-w-0 flex-1">
        <h2 className="text-panel">{t('{who} picked a time', { who })}</h2>
        {job.slot && (
          <p className="mt-2 inline-flex items-center gap-2 rounded border border-line bg-action-soft px-4 py-2 font-semibold">
            <Icon name="calendar" className="h-4 w-4 text-action" /> {fmtSlot(job.slot)}
          </p>
        )}
        <p className="mt-3 text-body-sm text-secondary">{t('Waiting for {tech} to confirm on the technician page. Then Debye confirms the visit to {who}.', { tech: first, who })}</p>
        {tech && (
          <Link to={`/tech/${tech.tech_id}`} className="btn-secondary mt-3">
            {t('Open as {name}', { name: first })} →
          </Link>
        )}
      </div>
      <Mascot pose="thinking" alt={t('Debye waiting')} className="h-24 w-24" />
    </div>
  )
}

// ---- mark as done ----
function FileTile({ label, sub, accept, capture, file, onFile, icon }: { label: string; sub: string; accept: string; capture?: boolean; file: File | null; onFile: (f: File | null) => void; icon: string }) {
  return (
    <label className={`flex cursor-pointer items-center gap-3 rounded border p-3 transition-colors ${file ? 'border-positive bg-positive-soft' : 'border-dashed border-line hover:border-action'}`}>
      <Icon name={file ? icon : 'upload'} className={`h-5 w-5 shrink-0 ${file ? 'text-positive' : 'text-secondary'}`} />
      <span className="min-w-0 flex-1">
        <span className="block truncate font-semibold">{file ? file.name : label}</span>
        <span className="block truncate text-meta text-muted">{file ? `${sub} · ${(file.size / 1024).toFixed(0)} KB` : t('Tap to add')}</span>
      </span>
      <input type="file" className="sr-only" accept={accept} {...(capture ? { capture: 'environment' } : {})} onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
    </label>
  )
}

async function demoFile(url: string, name: string, type: string) {
  const blob = await fetch(url).then((r) => r.blob())
  return new File([blob], name, { type })
}

function CompleteForm({ job, partnerId, onChange }: ActionProps) {
  const { busy, err, run } = useAction(onChange)
  const [notes, setNotes] = useState('')
  const [photo, setPhoto] = useState<File | null>(null)
  const [invoice, setInvoice] = useState<File | null>(null)
  const slot = job.confirmed_slot ?? job.slot
  const who = job.tenant?.name?.split(' ')[0] ?? t('the resident')
  return (
    <div className="flex flex-col gap-4">
      {slot && (
        <div className="flex items-center gap-3 rounded border border-line bg-action-soft px-4 py-3">
          <Icon name="calendar" className="h-5 w-5 shrink-0 text-action" />
          <span>
            <span className="font-semibold">{t('Visit booked: {slot}', { slot: fmtSlot(slot) })}</span>
            <span className="text-secondary"> · {job.technician ? t('{tech} confirmed, {who} knows', { tech: job.technician.name, who }) : t('confirmed by {who} on WhatsApp', { who })}</span>
          </span>
        </div>
      )}
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-panel">{t('Mark as done')}</h2>
        {DEMO && (
          <button
            className="text-label font-semibold text-action hover:underline"
            onClick={async () => {
              setPhoto(await demoFile('/demo-media/repair_done.jpg', 'after_repair.jpg', 'image/jpeg'))
              setInvoice(await demoFile('/demo-media/invoice_RE-2026-1187.pdf', 'RE-2026-1187.pdf', 'application/pdf'))
              setNotes('Ignition electrode replaced, boiler restarted, test run OK.')
            }}
          >
            {t('Use demo files')}
          </button>
        )}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FileTile label={t('Photo after repair')} sub={t('Photo')} accept="image/*" capture icon="camera" file={photo} onFile={setPhoto} />
        <FileTile label={t('Invoice (PDF)')} sub={t('Invoice')} accept="application/pdf,.pdf" icon="file" file={invoice} onFile={setInvoice} />
      </div>
      <input
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder={t('What did you do? e.g. ignition electrode replaced')}
        className="h-11 w-full rounded border border-line px-3 text-body focus:border-action focus:outline-none"
      />
      <div className="flex flex-wrap items-center gap-3">
        <button
          className="btn-primary"
          disabled={busy}
          onClick={() =>
            run(() => {
              const f = new FormData()
              f.append('notes', notes)
              if (photo) f.append('photo', photo)
              if (invoice) f.append('invoice', invoice)
              return api.complete(partnerId, job.case_id, f)
            })
          }
        >
          {busy ? t('Uploading…') : t('Mark as done')}
        </button>
        <span className="text-body-sm text-secondary">{t('Debye reads the invoice and asks {who} if it is warm again.', { who })}</span>
      </div>
      <Err err={err} />
    </div>
  )
}

function Done({ job, staffName }: ActionProps) {
  const invoice = job.documents.find((d) => d.kind === 'invoice')
  const after = job.photos?.find((p) => p.filename.startsWith('after'))
  const x = (invoice?.extracted ?? {}) as Record<string, unknown>
  const pc = priceCheckInfo(x.price_check ?? job.price_check)
  const [fields, setFields] = useState(false)
  const confirmed = job.events?.find((e) => e.kind === 'tenant.confirmed_fixed' || e.kind === 'case.closed')
  const pcText = pc.status === 'ok' ? ` · ${t('price check passed')}` : pc.status === 'flagged' ? ` · ${t('price check flagged, reltix will review')}` : ''
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-panel">{staffName ? t('Job done. Thank you, {name}.', { name: staffName.split(' ')[0] }) : t('Job done. Thank you.')}</h2>
          <p className="mt-1 text-body-sm text-secondary">
            {job.status === 'closed' ? t('Invoice sent to reltix') : t('Debye is checking the invoice')}
            {pcText} · {t('paid within 14 days per framework')}
          </p>
        </div>
        {job.status === 'closed' && <Mascot pose="thumbs-up" alt={t('Debye: done')} className="h-20 w-20" />}
      </div>
      <ul className="divide-y divide-line rounded border border-line">
        {invoice && (
          <li className="px-4 py-3">
            <div className="flex items-center gap-3">
              <Icon name="file" className="h-5 w-5 text-action" />
              <div className="min-w-0 flex-1">
                <div className="truncate font-semibold">{invoice.filename}</div>
                <div className={`text-meta ${pc.status === 'ok' ? 'text-positive' : pc.status === 'flagged' ? 'text-warning' : 'text-muted'}`}>
                  {typeof x.gross_eur === 'number' ? t('{eur} gross, read by Debye', { eur: fmtEur(x.gross_eur as number, true) }) : t('Reading…')}
                  {pc.status === 'ok' ? ` · ${t('price check passed')}` : pc.status === 'flagged' ? ` · ${t('price check flagged')}` : ''}
                </div>
              </div>
              {Object.keys(x).length > 0 && (
                <button className="text-label font-semibold text-action hover:underline" onClick={() => setFields(!fields)}>
                  {fields ? t('Hide fields') : t('Fields')}
                </button>
              )}
              <a href={invoice.url} target="_blank" rel="noreferrer" className="text-secondary hover:text-action" aria-label={t('Download invoice')}>
                <Icon name="download" className="h-5 w-5" />
              </a>
            </div>
            {fields && <InvoiceFields x={x} />}
          </li>
        )}
        {after && (
          <li className="flex items-center gap-3 px-4 py-3">
            <img src={after.url} alt="" className="h-10 w-10 rounded object-cover" />
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold">{after.filename}</div>
              <div className="text-meta text-muted">{t('Photo after repair, filed on the unit')}</div>
            </div>
          </li>
        )}
      </ul>
      {confirmed && job.status === 'closed' && <p className="text-body-sm text-secondary">{t('The resident confirmed on WhatsApp that it is warm again · {time}', { time: fmtTime(confirmed.ts) })}</p>}
    </div>
  )
}
