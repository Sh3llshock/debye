import { useMemo, useState, type ReactNode } from 'react'
import { api, DEMO } from '../api/client'
import type { JobDetail, JobSummary, Slot } from '../api/types'
import { InvoiceFields, priceCheckInfo, ServiceLine } from '../components/case/CasePanels'
import { Icon } from '../components/icons'
import { Chip, ErrorBox, Loading, Mascot } from '../components/ui'
import { errorLabel, errorText, explainCodes, jobTitle } from '../lib/errors'
import { floorLabel, fmtDateTime, fmtEur, fmtSlot, fmtTime, maskPhone } from '../lib/format'
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
  if (!job) return <div className="panel"><Loading what="Loading job" /></div>
  return <JobView job={job} partnerId={partnerId} staffName={staffName} jobs={jobs} onChange={setData} />
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-4 border-b border-line py-3 last:border-b-0">
      <dt className="text-label text-muted">{label}</dt>
      <dd className="[overflow-wrap:anywhere]">{children}</dd>
    </div>
  )
}

type ActionProps = { job: JobDetail; partnerId: string; staffName?: string; jobs: JobSummary[]; onChange: (j: JobDetail) => void }

function JobView(props: ActionProps) {
  const { job } = props
  const asset = job.asset
  const code = job.error_code ?? asset?.error_code
  const label = job.error_label ?? asset?.error_label
  const tenantPhoto = job.photos?.find((p) => !p.filename.startsWith('after'))
  const fields = job.consented_fields ?? []
  const who = job.tenant?.name?.split(' ')[0] ?? 'the resident'
  const line = lineState(PARTNER_STATIONS, job.status, job.events ?? [], true)
  const [street, city] = (job.address ?? '').split(',').map((x) => x.trim())

  return (
    <section className="panel overflow-hidden">
      <div className="border-b border-line px-5 pb-6 pt-8 lg:px-work">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-page">{jobTitle(job.title, code, label, asset?.error_meaning)}</h1>
            {job.priority === 'urgent' && <Chip tone="negative">Urgent</Chip>}
          </div>
          <div className="text-body-sm text-secondary">
            {job.case_id}
            {job.created_at ? ` · ${fmtDateTime(job.created_at)}` : ''}
          </div>
        </div>
        <div className="mt-8 overflow-x-auto">
          <div className="min-w-[520px]">
            <ServiceLine line={line} />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 border-b border-line px-5 py-6 md:grid-cols-[minmax(0,1fr)_240px] lg:px-work">
        <div className="min-w-0">
          {(job.summary || job.description) && <p className="mb-3 text-body text-secondary">{explainCodes(job.summary ?? job.description ?? '')}</p>}
          <dl>
            <Row label="Address">{job.address ? [street, city].filter(Boolean).join(', ') : <span className="text-muted">shared after the resident's consent</span>}</Row>
            <Row label="Where">{floorLabel(job.floor)}</Row>
            {asset && (
              <Row label="Boiler">
                {asset.make} {asset.model}
                {asset.installed ? `, ${asset.installed.slice(0, 4)}` : ''}
                {asset.last_service ? `, last serviced ${new Date(asset.last_service).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })}` : ''}
              </Row>
            )}
            {code && (
              <Row label="Error">
                <span className="font-semibold">{errorText(code, label, asset?.error_meaning)}</span>
                {asset?.error_meaning && !asset.error_meaning.toLowerCase().startsWith((errorLabel(code, label) ?? '~').toLowerCase()) && <span className="text-secondary"> · {asset.error_meaning}</span>}
              </Row>
            )}
            {job.tenant && (
              <Row label="Resident">
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
          </dl>
          <div className="mt-3 flex items-start gap-2 text-label text-secondary">
            <Icon name="shield" className="mt-0.5 h-4 w-4 shrink-0 text-positive" />
            <span>
              {fields.length
                ? `Shared with ${who}'s consent on WhatsApp: ${fields.map((f) => FIELD_LABEL[f] ?? f).join(', ')}. Nothing beyond these fields.`
                : 'No personal data shared yet. Debye asks the resident first.'}
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
            {tenantPhoto ? `Photo from ${who}` : 'No photo shared'}
            {code ? ` · display shows ${errorText(code, label, asset?.error_meaning)}` : ''}
          </figcaption>
        </figure>
      </div>

      <div className="px-5 py-6 lg:px-work">
        <Actions {...props} />
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

function Err({ err }: { err: string | null }) {
  return err ? <div className="mt-3 rounded border border-negative bg-negative-soft p-3 text-negative">{err}</div> : null
}

function Actions(props: ActionProps) {
  const { job } = props
  const s = job.status
  if (s === 'requested') return <AcceptDecline {...props} />
  if (s === 'accepted' || s === 'reopened') return job.proposed_slots?.length ? <TimesOffered job={job} /> : <WeekGrid {...props} />
  if (s === 'slots_proposed') return <TimesOffered job={job} />
  if (s === 'scheduled' || s === 'in_progress') return <CompleteForm {...props} />
  if (s === 'completed' || s === 'invoiced' || s === 'closed') return <Done {...props} />
  if (s === 'declined' || s === 'partner_declined') return <p className="text-secondary">You declined this job. Debye passed it to the next partner.</p>
  return null
}

const DECLINE_REASONS = ['Fully booked', 'Outside service area', 'Not our device type']

function DeclineChoices({ busy, onPick, onCancel }: { busy: boolean; onPick: (r: string) => void; onCancel: () => void }) {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <span className="text-label text-muted">Reason:</span>
      {DECLINE_REASONS.map((r) => (
        <button key={r} className="btn-secondary" disabled={busy} onClick={() => onPick(r)}>
          {r}
        </button>
      ))}
      <button className="btn-ghost" onClick={onCancel}>
        Cancel
      </button>
    </div>
  )
}

function AcceptDecline({ job, partnerId, onChange }: ActionProps) {
  const { busy, err, run } = useAction(onChange)
  const [declining, setDeclining] = useState(false)
  return (
    <div>
      <h2 className="text-panel">New job from Debye</h2>
      <p className="mt-1 text-body-sm text-secondary">
        Framework job{job.estimated_cost_eur != null ? `, estimate ${fmtEur(job.estimated_cost_eur)}, approved automatically` : ''}. Accept and offer visit times next.
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <button className="btn-primary" disabled={busy} onClick={() => run(() => api.accept(partnerId, job.case_id))}>
          {busy ? 'Accepting…' : 'Accept job'}
        </button>
        <button className="btn-secondary" disabled={busy} onClick={() => setDeclining(true)}>
          Decline job
        </button>
      </div>
      {declining && <DeclineChoices busy={busy} onPick={(r) => run(() => api.decline(partnerId, job.case_id, r))} onCancel={() => setDeclining(false)} />}
      <Err err={err} />
    </div>
  )
}

// ---- week grid for visit times ----
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

function WeekGrid({ job, partnerId, jobs, onChange }: ActionProps) {
  const { busy, err, run } = useAction(onChange)
  const [picked, setPicked] = useState<Slot[]>([])
  const [declining, setDeclining] = useState(false)
  const who = job.tenant?.name?.split(' ')[0] ?? 'the resident'

  // Next four working days from tomorrow (no Sundays).
  const days = useMemo(() => {
    const out: { date: string; label: string; off: string }[] = []
    for (let i = 1; out.length < 4 && i < 10; i++) {
      const d = new Date(Date.now() + i * 86400_000)
      if (new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Berlin', weekday: 'short' }).format(d) === 'Sun') continue
      out.push({ date: berlinDate(d), label: d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Europe/Berlin' }), off: berlinOffset(d) })
    }
    return out
  }, [])

  // Busy = the installer's other booked visits (real data from the jobs list).
  const busySlots = jobs.filter((j) => j.case_id !== job.case_id && j.slot).map((j) => j.slot!)
  const isBusy = (s: Slot) => busySlots.some((b) => new Date(b.start) < new Date(s.end) && new Date(b.end) > new Date(s.start))
  const toggle = (s: Slot) => setPicked((p) => (p.some((x) => x.start === s.start) ? p.filter((x) => x.start !== s.start) : p.length >= 3 ? p : [...p, s]))

  return (
    <div>
      <h2 className="text-panel">Offer visit times</h2>
      <p className="mt-1 text-body-sm text-secondary">Choose two or three. Debye sends them to {who} on WhatsApp and books the one {who === 'the resident' ? 'they pick' : 'she picks'}.</p>
      <div className="mt-4 overflow-x-auto rounded border border-line">
        <table className="w-full min-w-[560px] table-fixed text-left">
          <thead className="bg-sub">
            <tr className="text-label text-muted">
              <th className="w-[140px] px-4 py-3 font-medium">Time</th>
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
                  const s: Slot = { start: `${d.date}T${a}:00${d.off}`, end: `${d.date}T${b}:00${d.off}` }
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
                        {busyCell ? 'Busy' : on ? 'Offered' : 'Free'}
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
        <button className="btn-primary" disabled={busy || picked.length === 0} onClick={() => run(() => api.slots(partnerId, job.case_id, [...picked].sort((x, y) => x.start.localeCompare(y.start))))}>
          {busy ? 'Sending…' : picked.length ? `Send ${picked.length} time${picked.length > 1 ? 's' : ''} to ${who}` : 'Pick a time'}
        </button>
        <button className="btn-secondary" disabled={busy} onClick={() => setDeclining(true)}>
          Decline job
        </button>
      </div>
      {declining && <DeclineChoices busy={busy} onPick={(r) => run(() => api.decline(partnerId, job.case_id, r))} onCancel={() => setDeclining(false)} />}
      <Err err={err} />
    </div>
  )
}

function TimesOffered({ job }: { job: JobDetail }) {
  const who = job.tenant?.name?.split(' ')[0] ?? 'the resident'
  return (
    <div className="flex flex-wrap items-center gap-6">
      <div className="min-w-0 flex-1">
        <h2 className="text-panel">Times offered</h2>
        <ul className="mt-3 flex flex-wrap gap-2">
          {job.proposed_slots.map((p) => (
            <li key={p.start} className="inline-flex items-center gap-2 rounded border border-line px-4 py-2">
              <Icon name="calendar" className="h-4 w-4 text-secondary" /> {fmtSlot({ start: p.start, end: p.end })}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-body-sm text-secondary">Waiting for {who} to pick one on WhatsApp. You will see the booked time here.</p>
      </div>
      <Mascot pose="thinking" alt="Debye waiting" className="h-24 w-24" />
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
        <span className="block truncate text-meta text-muted">{file ? `${sub} · ${(file.size / 1024).toFixed(0)} KB` : 'Tap to add'}</span>
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
  const who = job.tenant?.name?.split(' ')[0] ?? 'the resident'
  return (
    <div className="flex flex-col gap-4">
      {slot && (
        <div className="flex items-center gap-3 rounded border border-line bg-action-soft px-4 py-3">
          <Icon name="calendar" className="h-5 w-5 text-action" />
          <span>
            <span className="font-semibold">Visit booked: {fmtSlot(slot)}</span>
            <span className="text-secondary"> · confirmed by {who} on WhatsApp</span>
          </span>
        </div>
      )}
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-panel">Mark as done</h2>
        {DEMO && (
          <button
            className="text-label font-semibold text-action hover:underline"
            onClick={async () => {
              setPhoto(await demoFile('/demo-media/repair_done.jpg', 'after_repair.jpg', 'image/jpeg'))
              setInvoice(await demoFile('/demo-media/invoice_RE-2026-1187.pdf', 'RE-2026-1187.pdf', 'application/pdf'))
              setNotes('Ignition electrode replaced, boiler restarted, test run OK.')
            }}
          >
            Use demo files
          </button>
        )}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FileTile label="Photo after repair" sub="Photo" accept="image/*" capture icon="camera" file={photo} onFile={setPhoto} />
        <FileTile label="Invoice (PDF)" sub="Invoice" accept="application/pdf,.pdf" icon="file" file={invoice} onFile={setInvoice} />
      </div>
      <input
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="What did you do? e.g. ignition electrode replaced"
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
          {busy ? 'Uploading…' : 'Mark as done'}
        </button>
        <span className="text-body-sm text-secondary">Debye reads the invoice and asks {who} if it is warm again.</span>
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
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-panel">Job done. Thank you{staffName ? `, ${staffName.split(' ')[0]}` : ''}.</h2>
          <p className="mt-1 text-body-sm text-secondary">
            {job.status === 'closed' ? 'Invoice sent to reltix' : 'Debye is checking the invoice'}
            {pc.status === 'ok' ? ' · price check passed' : pc.status === 'flagged' ? ' · price check flagged, reltix will review' : ''} · paid within 14 days per framework
          </p>
        </div>
        {job.status === 'closed' && <Mascot pose="thumbs-up" alt="Debye: done" className="h-20 w-20" />}
      </div>
      <ul className="divide-y divide-line rounded border border-line">
        {invoice && (
          <li className="px-4 py-3">
            <div className="flex items-center gap-3">
              <Icon name="file" className="h-5 w-5 text-action" />
              <div className="min-w-0 flex-1">
                <div className="truncate font-semibold">{invoice.filename}</div>
                <div className={`text-meta ${pc.status === 'ok' ? 'text-positive' : pc.status === 'flagged' ? 'text-warning' : 'text-muted'}`}>
                  {typeof x.gross_eur === 'number' ? `${fmtEur(x.gross_eur as number, true)} gross, read by Debye` : 'Reading…'}
                  {pc.status === 'ok' ? ' · price check passed' : pc.status === 'flagged' ? ' · price check flagged' : ''}
                </div>
              </div>
              {Object.keys(x).length > 0 && (
                <button className="text-label font-semibold text-action hover:underline" onClick={() => setFields(!fields)}>
                  {fields ? 'Hide fields' : 'Fields'}
                </button>
              )}
              <a href={invoice.url} target="_blank" rel="noreferrer" className="text-secondary hover:text-action" aria-label="Download invoice">
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
              <div className="text-meta text-muted">Photo after repair, filed on the unit</div>
            </div>
          </li>
        )}
      </ul>
      {confirmed && job.status === 'closed' && <p className="text-body-sm text-secondary">The resident confirmed on WhatsApp that it is warm again · {fmtTime(confirmed.ts)}</p>}
    </div>
  )
}
