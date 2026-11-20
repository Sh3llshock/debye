import { useMemo, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { JobDetail, Slot } from '../api/types'
import { InvoiceFields } from '../components/case/CasePanels'
import { PartnerLayout } from '../components/Layout'
import { Card, ErrorBox, Field, Loading, Pill, PriorityPill, StatusPill } from '../components/ui'
import { fmtEur, fmtSlot, humanize } from '../lib/format'
import { useStream } from '../lib/stream'
import { useDebounced, useResource } from '../lib/useResource'
import { usePartner } from './PartnerInbox'

export default function PartnerJob() {
  const { partnerId = '', caseId = '' } = useParams()
  const partner = usePartner(partnerId)
  const { data: job, setData, error, reload } = useResource(() => api.job(partnerId, caseId), [partnerId, caseId])
  const refetch = useDebounced(reload, 250)
  useStream((m) => {
    if (!m.case_id || m.case_id === caseId) refetch()
  })

  return (
    <PartnerLayout partnerId={partnerId} partnerName={partner?.name}>
      <Link to={`/partner/${partnerId}`} className="font-semibold text-plum">← All jobs</Link>
      {error && !job && <div className="mt-4"><ErrorBox error={error} onRetry={reload} /></div>}
      {!job && !error && <Loading what="Loading job" />}
      {job && <JobView job={job} partnerId={partnerId} onChange={setData} />}
    </PartnerLayout>
  )
}

function JobView({ job, partnerId, onChange }: { job: JobDetail; partnerId: string; onChange: (j: JobDetail) => void }) {
  const asset = job.asset
  const errorCode = job.error_code ?? asset?.error_code
  return (
    <div className="mt-3 flex flex-col gap-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill status={job.status} big />
          <PriorityPill priority={job.priority} />
        </div>
        <h1 className="mt-2 text-2xl">{job.title}</h1>
        <div className="text-lg">{job.address}{job.floor != null ? ` · Floor ${job.floor}` : ''}</div>
      </div>

      <Actions job={job} partnerId={partnerId} onChange={onChange} />

      <Card title="Job details">
        <div className="grid grid-cols-2 gap-4">
          {asset && <Field label="Device">{asset.make} {asset.model}</Field>}
          {errorCode && (
            <Field label="Error code">
              <span className="rounded-sm bg-danger-soft px-2 font-mono text-lg font-semibold text-danger">{errorCode}</span>
            </Field>
          )}
          {job.estimated_cost_eur != null && <Field label="Approved up to">{fmtEur(job.estimated_cost_eur)}</Field>}
          {(job.confirmed_slot ?? job.slot) && <Field label="Visit">{fmtSlot(job.confirmed_slot ?? job.slot)}</Field>}
        </div>
        {job.description && <p className="mt-4">{job.description}</p>}
        {job.tenant_contact && (
          <div className="mt-4 rounded bg-surface-alt p-3">
            <div className="label">Resident</div>
            <div className="font-semibold">{job.tenant_contact.name}</div>
            {job.tenant_contact.phone && (
              <a className="text-plum underline" href={`tel:${job.tenant_contact.phone.replace(/\s/g, '')}`}>{job.tenant_contact.phone}</a>
            )}
          </div>
        )}
        {job.photos?.length > 0 && (
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {job.photos.map((p) => (
              <a key={p.document_id} href={p.url} target="_blank" rel="noreferrer" className="block aspect-square overflow-hidden rounded bg-surface-alt">
                <img src={p.url} alt={p.filename} className="h-full w-full object-cover" onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')} />
              </a>
            ))}
          </div>
        )}
        {job.consented_fields && (
          <div className="mt-4 text-sm text-muted">
            🔒 Shared with the resident's consent: {job.consented_fields.length ? job.consented_fields.map(humanize).join(', ') : 'nothing yet'}
          </div>
        )}
      </Card>

      {job.documents?.length > 0 && (
        <Card title="Your documents">
          {job.documents.map((d) => (
            <div key={d.document_id} className="mb-3">
              <a href={d.url} target="_blank" rel="noreferrer" className="font-semibold text-plum underline">{d.filename}</a>
              {d.kind === 'invoice' && d.extracted && Object.keys(d.extracted).length > 0 && <InvoiceFields x={d.extracted} />}
            </div>
          ))}
        </Card>
      )}
    </div>
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

function ActionCard({ title, children, err }: { title: ReactNode; children: ReactNode; err?: string | null }) {
  return (
    <section className="rounded-card border-2 border-plum bg-surface p-4 shadow-card">
      <h2 className="mb-3 text-xl">{title}</h2>
      {children}
      {err && <div className="mt-3 rounded bg-danger-soft p-2 text-danger">{err}</div>}
    </section>
  )
}

function Actions({ job, partnerId, onChange }: { job: JobDetail; partnerId: string; onChange: (j: JobDetail) => void }) {
  const s = job.status
  if (s === 'requested' || s === 'dispatched') return <AcceptDecline job={job} partnerId={partnerId} onChange={onChange} />
  if (s === 'accepted') {
    if (job.proposed_slots?.length)
      return (
        <ActionCard title="Waiting for the resident to pick a time">
          <ul className="flex flex-col gap-2">
            {job.proposed_slots.map((p) => (
              <li key={p.start} className="rounded-pill bg-plum-soft px-4 py-2 font-semibold text-plum">{fmtSlot(p)}</li>
            ))}
          </ul>
          <p className="mt-3 text-muted">Debye sent these to the resident on WhatsApp. You'll see the confirmed slot here.</p>
        </ActionCard>
      )
    return <SlotPicker job={job} partnerId={partnerId} onChange={onChange} />
  }
  if (s === 'scheduled' || s === 'in_progress') return <CompleteForm job={job} partnerId={partnerId} onChange={onChange} />
  if (s === 'completed' || s === 'invoiced')
    return (
      <section className="rounded-card border border-success bg-success-soft p-4 text-success">
        <div className="text-xl font-semibold">✓ Done — thank you!</div>
        <div>Debye is checking the invoice and asking the resident if it's warm again.</div>
      </section>
    )
  if (s === 'closed')
    return (
      <section className="rounded-card border border-success bg-success-soft p-4 text-success">
        <div className="text-xl font-semibold">✓ Job closed</div>
        <div>The resident confirmed the fix. Invoice passed to the property manager.</div>
      </section>
    )
  if (s === 'declined') return <section className="rounded-card border border-line bg-surface-alt p-4 text-muted">You declined this job.</section>
  return null
}

const DECLINE_REASONS = ['Fully booked', 'Outside service area', 'Not our device type']

function AcceptDecline({ job, partnerId, onChange }: { job: JobDetail; partnerId: string; onChange: (j: JobDetail) => void }) {
  const { busy, err, run } = useAction(onChange)
  const [declining, setDeclining] = useState(false)
  return (
    <ActionCard title="New job from Debye" err={err}>
      {!declining ? (
        <div className="grid grid-cols-2 gap-3">
          <button className="btn-primary text-lg" disabled={busy} onClick={() => run(() => api.accept(partnerId, job.case_id))}>
            {busy ? '…' : '✓ Accept'}
          </button>
          <button className="btn-secondary text-lg" disabled={busy} onClick={() => setDeclining(true)}>Decline</button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="text-muted">Why? (one tap)</div>
          {DECLINE_REASONS.map((r) => (
            <button key={r} className="btn-secondary justify-start" disabled={busy} onClick={() => run(() => api.decline(partnerId, job.case_id, r))}>{r}</button>
          ))}
          <button className="btn-ghost" onClick={() => setDeclining(false)}>Cancel</button>
        </div>
      )}
    </ActionCard>
  )
}

// ---- slot picker ----
function berlinOffset(d: Date): string {
  const part = new Intl.DateTimeFormat('en-US', { timeZone: 'Europe/Berlin', timeZoneName: 'shortOffset' }).formatToParts(d).find((p) => p.type === 'timeZoneName')?.value ?? 'GMT+1'
  const m = part.match(/GMT([+-])(\d+)/)
  return m ? `${m[1]}${m[2].padStart(2, '0')}:00` : '+01:00'
}
function berlinDate(d: Date): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Berlin' }).format(d) // YYYY-MM-DD
}

const WINDOWS: [number, number][] = [[8, 10], [10, 12], [12, 14], [14, 16], [16, 18]]

function SlotPicker({ job, partnerId, onChange }: { job: JobDetail; partnerId: string; onChange: (j: JobDetail) => void }) {
  const { busy, err, run } = useAction(onChange)
  const [picked, setPicked] = useState<Slot[]>([])
  const days = useMemo(() => {
    const out: { label: string; slots: Slot[] }[] = []
    const base = new Date()
    for (let i = 0; i < 3; i++) {
      const d = new Date(base.getTime() + i * 86400_000)
      const date = berlinDate(d)
      const off = berlinOffset(d)
      const label = i === 0 ? 'Today' : i === 1 ? 'Tomorrow' : d.toLocaleDateString('en-GB', { weekday: 'long', timeZone: 'Europe/Berlin' })
      const hourNow = Number(new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Berlin', hour: '2-digit', hour12: false }).format(base))
      const slots = WINDOWS.filter(([a]) => i > 0 || a > hourNow + 1).map(([a, b]) => ({
        start: `${date}T${String(a).padStart(2, '0')}:00:00${off}`,
        end: `${date}T${String(b).padStart(2, '0')}:00:00${off}`,
        label: `${label} ${a}–${b}`,
      }))
      if (slots.length) out.push({ label, slots })
    }
    return out
  }, [])
  const toggle = (s: Slot) =>
    setPicked((p) => (p.some((x) => x.start === s.start) ? p.filter((x) => x.start !== s.start) : p.length >= 3 ? p : [...p, s]))

  return (
    <ActionCard title="When can you come? Tap 2–3 slots" err={err}>
      <div className="flex flex-col gap-4">
        {days.map((d) => (
          <div key={d.label}>
            <div className="label mb-2">{d.label}</div>
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
              {d.slots.map((s) => {
                const on = picked.some((x) => x.start === s.start)
                return (
                  <button
                    key={s.start}
                    onClick={() => toggle(s)}
                    className={`rounded-button border-[1.5px] px-2 py-4 text-body font-semibold transition-colors ${on ? "border-plum bg-plum text-on-plum" : "border-line bg-surface text-ink hover:border-plum"}`}
                  >
                    {s.label!.split(' ').pop()}
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>
      <button
        className="btn-primary mt-4 w-full text-lg"
        disabled={busy || picked.length === 0}
        onClick={() => run(() => api.slots(partnerId, job.case_id, [...picked].sort((a, b) => a.start.localeCompare(b.start))))}
      >
        {busy ? 'Sending…' : picked.length ? `Send ${picked.length} slot${picked.length > 1 ? 's' : ''} to resident` : 'Pick at least one slot'}
      </button>
    </ActionCard>
  )
}

// ---- complete ----
function FilePick({ label, accept, capture, file, onFile, icon }: { label: string; accept: string; capture?: boolean; file: File | null; onFile: (f: File | null) => void; icon: string }) {
  return (
    <label className={`flex cursor-pointer items-center gap-3 rounded border-2 border-dashed p-4 ${file ? 'border-success bg-success-soft' : 'border-line hover:border-plum'}`}>
      <span className="text-2xl">{file ? '✓' : icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">{label}</span>
        <span className="block truncate text-sm text-muted">{file ? file.name : 'Tap to choose'}</span>
      </span>
      <input type="file" className="sr-only" accept={accept} {...(capture ? { capture: 'environment' } : {})} onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
    </label>
  )
}

function CompleteForm({ job, partnerId, onChange }: { job: JobDetail; partnerId: string; onChange: (j: JobDetail) => void }) {
  const { busy, err, run } = useAction(onChange)
  const [notes, setNotes] = useState('')
  const [photo, setPhoto] = useState<File | null>(null)
  const [invoice, setInvoice] = useState<File | null>(null)
  const QUICK = ['Ignition electrode replaced, boiler restarted', 'Water pressure topped up', 'Part ordered, second visit needed']
  return (
    <ActionCard title={<span className="flex items-center gap-2">Mark as done {(job.confirmed_slot ?? job.slot) && <Pill tone="plum">{fmtSlot(job.confirmed_slot ?? job.slot)}</Pill>}</span>} err={err}>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-2">
          {QUICK.map((q) => (
            <button key={q} type="button" onClick={() => setNotes(q)} className={`rounded-pill border px-3 py-1 text-sm ${notes === q ? 'border-plum bg-plum-soft text-plum' : 'border-line'}`}>{q}</button>
          ))}
        </div>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} placeholder="What did you do? (optional)" className="w-full rounded border border-line p-3 text-body focus:border-plum focus:outline-none" />
        <FilePick label="Photo of the fixed device" accept="image/*" capture icon="📷" file={photo} onFile={setPhoto} />
        <FilePick label="Invoice (PDF)" accept="application/pdf,.pdf" icon="🧾" file={invoice} onFile={setInvoice} />
        <button
          className="btn-success w-full text-lg"
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
          {busy ? 'Uploading…' : '✓ Mark as done'}
        </button>
      </div>
    </ActionCard>
  )
}
