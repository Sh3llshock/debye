import { useMemo, useState, type ReactNode } from 'react'
import { api, DEMO } from '../api/client'
import type { JobDetail, Slot } from '../api/types'
import { InvoiceFields, PriorityBadge, priceCheckOk } from '../components/case/CasePanels'
import { Icon } from '../components/icons'
import { DebyeMark, ErrorBox, Field, Loading, StatusPill } from '../components/ui'
import { floorLabel, fmtDateTime, fmtEur, fmtSlot, fmtTime, maskPhone } from '../lib/format'
import { useStream } from '../lib/stream'
import { useDebounced, useResource } from '../lib/useResource'

const FIELD_LABEL: Record<string, string> = { name: 'name', phone: 'phone', address: 'address', unit_floor: 'floor', photos: 'photo' }

export function JobPanel({ partnerId, caseId, staffName }: { partnerId: string; caseId: string; staffName?: string }) {
  const { data: job, setData, error, reload } = useResource(() => api.job(partnerId, caseId), [partnerId, caseId])
  const refetch = useDebounced(reload, 250)
  useStream((m) => {
    if (!m.case_id || m.case_id === caseId) refetch()
  })
  if (error && !job) return <ErrorBox error={error} onRetry={reload} />
  if (!job) return <Loading what="Loading job" />
  return <JobView job={job} partnerId={partnerId} staffName={staffName} onChange={setData} />
}

function JobView({ job, partnerId, staffName, onChange }: { job: JobDetail; partnerId: string; staffName?: string; onChange: (j: JobDetail) => void }) {
  const asset = job.asset
  const errorCode = job.error_code ?? asset?.error_code
  const tenantPhoto = job.photos?.find((p) => !p.filename.startsWith('after'))
  const fields = job.consented_fields ?? []
  const title = errorCode && !job.title.includes(errorCode) ? `${job.title.split(' – ')[0]} – error ${errorCode}` : job.title

  return (
    <section className="rounded-card border border-line bg-surface p-5 shadow-card lg:p-card">
      <div className="font-mono text-sm text-plum-60">
        {job.case_id} · from reltix via Debye{job.created_at ? ` · ${fmtDateTime(job.created_at)}` : ''}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <h2 className="text-2xl lg:text-3xl">{title}</h2>
        <StatusPill status={job.status} big />
        <PriorityBadge priority={job.priority} />
      </div>
      {(job.summary || job.description) && <p className="mt-3 text-body leading-relaxed">Debye: {job.summary ?? job.description}</p>}

      <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-[minmax(0,1fr)_260px]">
        <div className="flex flex-col gap-5">
          <div className="grid grid-cols-2 gap-x-6 gap-y-5">
            <Field label="Address">
              <span className="text-body lg:text-lg">{job.address ? job.address.split(',')[0] : <span className="text-muted">shared after consent</span>}</span>
              {(job.address?.split(',')[1] || job.postcode) && <div className="text-sm text-muted">{job.address?.split(',')[1]?.trim() ?? job.postcode}</div>}
            </Field>
            <Field label="Floor">
              <span className="text-body lg:text-lg">{floorLabel(job.floor)}</span>
            </Field>
            {asset && (
              <Field label="Boiler">
                <span className="text-body lg:text-lg">
                  {asset.make} {asset.model?.split(' VC')[0]}
                </span>
                <div className="text-sm text-muted">
                  {[
                    asset.model?.includes(' VC') ? 'VC' + asset.model.split(' VC')[1] : null,
                    asset.installed?.slice(0, 4),
                    asset.last_service ? `serviced ${new Date(asset.last_service).toLocaleDateString('en-GB', { month: 'short', year: '2-digit' })}` : null,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </div>
              </Field>
            )}
            {errorCode && (
              <Field label="Error">
                <span className="text-body lg:text-lg">{errorCode}</span>
                {asset?.error_meaning && <div className="text-sm text-muted">{asset.error_meaning}</div>}
              </Field>
            )}
          </div>
          {job.tenant && (
            <div className="flex items-center gap-4 rounded-lg bg-surface-alt p-4">
              <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-success text-on-plum">
                <Icon name="phone" className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <div className="font-semibold">{job.tenant.name ?? 'Tenant'} · tenant</div>
                {job.tenant.phone && (
                  <a href={`tel:${job.tenant.phone}`} className="text-body-sm text-muted hover:text-plum">
                    {maskPhone(job.tenant.phone)}
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
        <div className="relative flex aspect-[4/3] items-center justify-center overflow-hidden rounded-lg bg-error-screen md:aspect-auto md:min-h-[200px]">
          {tenantPhoto ? (
            <img src={tenantPhoto.url} alt={tenantPhoto.filename} className="absolute inset-0 h-full w-full object-cover" />
          ) : (
            <span className="font-mono text-stat text-error-glow">{errorCode ?? '—'}</span>
          )}
          <span className="absolute bottom-0 left-0 right-0 bg-plum-dark/70 py-1.5 text-center text-sm text-on-plum">{tenantPhoto ? 'Photo from tenant' : 'No photo shared'}</span>
        </div>
      </div>

      <div className="mt-6 flex items-start gap-3 rounded-lg border border-success p-4 text-body-sm font-medium text-success">
        <Icon name="shield" className="mt-0.5 h-6 w-6 shrink-0" />
        <span>
          {fields.length ? `Shared with the tenant's consent (WhatsApp): ${fields.map((f) => FIELD_LABEL[f] ?? f).join(', ')}. Nothing else.` : 'No personal data shared yet. Debye asks the tenant first.'}
        </span>
      </div>

      <hr className="my-6 border-line" />
      <Actions job={job} partnerId={partnerId} staffName={staffName} onChange={onChange} />
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
  return err ? <div className="mt-3 rounded bg-danger-soft p-3 text-danger">{err}</div> : null
}

function Hint({ children }: { children: ReactNode }) {
  return <span className="text-body-sm text-muted">{children}</span>
}

type ActionProps = { job: JobDetail; partnerId: string; staffName?: string; onChange: (j: JobDetail) => void }

function Actions(props: ActionProps) {
  const { job } = props
  const s = job.status
  if (s === 'requested') return <AcceptDecline {...props} />
  if (s === 'accepted' || s === 'reopened') return job.proposed_slots?.length ? <ProposedSlots job={job} /> : <SlotPicker {...props} />
  if (s === 'slots_proposed') return <ProposedSlots job={job} />
  if (s === 'scheduled' || s === 'in_progress') return <CompleteForm {...props} />
  if (s === 'completed' || s === 'invoiced' || s === 'closed') return <Done {...props} />
  if (s === 'declined' || s === 'partner_declined') return <div className="rounded-lg bg-surface-alt p-4 text-muted">You declined this job. Debye passed it to the next partner.</div>
  return null
}

const DECLINE_REASONS = ['Fully booked', 'Outside service area', 'Not our device type']

function AcceptDecline({ job, partnerId, onChange }: ActionProps) {
  const { busy, err, run } = useAction(onChange)
  const [declining, setDeclining] = useState(false)
  if (declining)
    return (
      <div className="flex flex-col gap-3">
        <h3 className="text-xl">Why not? One tap.</h3>
        <div className="flex flex-wrap gap-3">
          {DECLINE_REASONS.map((r) => (
            <button key={r} className="btn-secondary" disabled={busy} onClick={() => run(() => api.decline(partnerId, job.case_id, r))}>
              {r}
            </button>
          ))}
          <button className="btn-ghost" onClick={() => setDeclining(false)}>
            Cancel
          </button>
        </div>
        <Err err={err} />
      </div>
    )
  return (
    <div>
      <div className="flex flex-wrap items-center gap-4">
        <button className="btn-primary" disabled={busy} onClick={() => run(() => api.accept(partnerId, job.case_id))}>
          {busy ? 'Accepting…' : 'Accept job'} <Icon name="arrow" className="h-5 w-5" />
        </button>
        <button className="btn-secondary" disabled={busy} onClick={() => setDeclining(true)}>
          Decline
        </button>
        {job.estimated_cost_eur != null && <Hint>Framework job · estimate {fmtEur(job.estimated_cost_eur)}, auto-approved</Hint>}
      </div>
      <Err err={err} />
    </div>
  )
}

// ---- slot picker ----
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

function SlotPicker({ job, partnerId, onChange }: ActionProps) {
  const { busy, err, run } = useAction(onChange)
  const [picked, setPicked] = useState<Slot[]>([])
  const days = useMemo(() => {
    const out: { label: string; slots: Slot[] }[] = []
    for (let i = 1; out.length < 3 && i < 10; i++) {
      const d = new Date(Date.now() + i * 86400_000)
      const wd = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Berlin', weekday: 'short' }).format(d)
      if (wd === 'Sun') continue
      const date = berlinDate(d)
      const off = berlinOffset(d)
      const date_ = d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Europe/Berlin' })
      const label = i === 1 ? `Tomorrow · ${date_}` : i === 2 ? `Day after · ${date_}` : date_
      out.push({ label, slots: WINDOWS.map(([a, b]) => ({ start: `${date}T${a}:00${off}`, end: `${date}T${b}:00${off}`, label: `${label} · ${a}–${b}` })) })
    }
    return out
  }, [])
  const toggle = (s: Slot) => setPicked((p) => (p.some((x) => x.start === s.start) ? p.filter((x) => x.start !== s.start) : p.length >= 3 ? p : [...p, s]))

  return (
    <div>
      <h3 className="text-xl lg:text-2xl">When can you go? Tap 2–3 slots.</h3>
      <div className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-3">
        {days.map((d) => (
          <div key={d.label}>
            <div className="label mb-2">{d.label}</div>
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-1 sm:gap-3">
              {d.slots.map((s) => {
                const on = picked.some((x) => x.start === s.start)
                const time = s.label!.split(' · ').pop()!
                return (
                  <button
                    key={s.start}
                    onClick={() => toggle(s)}
                    className={`flex items-center justify-center gap-2 rounded-lg border-[1.5px] px-2 py-4 text-body font-medium transition-colors sm:justify-start sm:px-5 sm:text-lg ${
                      on ? 'border-plum bg-plum text-on-plum' : 'border-line bg-surface text-ink hover:border-plum'
                    }`}
                  >
                    {on && <Icon name="check" className="hidden h-5 w-5 sm:block" />}
                    <span className="sm:hidden">{time.replace(/:00/g, '')}</span>
                    <span className="hidden sm:inline">{time}</span>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-4">
        <button className="btn-primary" disabled={busy || picked.length === 0} onClick={() => run(() => api.slots(partnerId, job.case_id, [...picked].sort((a, b) => a.start.localeCompare(b.start))))}>
          {busy ? 'Sending…' : picked.length ? `Send ${picked.length} slot${picked.length > 1 ? 's' : ''} to tenant` : 'Pick a slot'} <Icon name="arrow" className="h-5 w-5" />
        </button>
        <Hint>Debye asks {job.tenant?.name?.split(' ')[0] ?? 'the tenant'} on WhatsApp. No phone calls.</Hint>
      </div>
      <Err err={err} />
    </div>
  )
}

function ProposedSlots({ job }: { job: JobDetail }) {
  const name = job.tenant?.name?.split(' ')[0] ?? 'the tenant'
  return (
    <div>
      <h3 className="text-xl lg:text-2xl">Proposed slots</h3>
      <div className="mt-4 flex flex-wrap gap-3">
        {job.proposed_slots.map((p) => (
          <span key={p.start} className="inline-flex items-center gap-3 rounded-lg border-[1.5px] border-plum px-5 py-3 text-lg font-medium">
            <Icon name="calendar" className="h-5 w-5" /> {fmtSlot({ start: p.start, end: p.end })}
          </span>
        ))}
      </div>
      <div className="mt-4 flex items-center gap-4 rounded-lg bg-violet-soft p-4 text-body">
        <DebyeMark size={44} />
        <span>Waiting for {name} to pick a slot on WhatsApp…</span>
      </div>
    </div>
  )
}

// ---- complete ----
function FileTile({ label, sub, accept, capture, file, onFile, icon }: { label: string; sub: string; accept: string; capture?: boolean; file: File | null; onFile: (f: File | null) => void; icon: string }) {
  return (
    <label className={`flex cursor-pointer items-center gap-4 rounded-lg border-[1.5px] p-4 transition-colors ${file ? 'border-success bg-success-soft' : 'border-dashed border-line hover:border-plum'}`}>
      <span className={`inline-flex h-14 w-14 shrink-0 items-center justify-center rounded-lg ${file ? (icon === 'camera' ? 'bg-ink text-on-plum' : 'bg-plum text-on-plum') : 'bg-surface-alt text-plum-80'}`}>
        <Icon name={file ? icon : 'upload'} className="h-6 w-6" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-semibold">{file ? file.name : label}</span>
        <span className={`block truncate text-sm ${file ? 'text-success' : 'text-muted'}`}>{file ? `${sub} · ${(file.size / 1024).toFixed(0)} KB` : 'Tap to add'}</span>
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
  const name = job.tenant?.name?.split(' ')[0] ?? 'the tenant'
  return (
    <div className="flex flex-col gap-5">
      {slot && (
        <div className="flex items-center gap-4 rounded-lg bg-info-soft p-5 text-info">
          <Icon name="calendar" className="h-8 w-8 shrink-0" />
          <div>
            <div className="text-xl font-semibold lg:text-2xl">{fmtSlot(slot)}</div>
            <div className="text-body-sm">Confirmed by {name} on WhatsApp</div>
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h3 className="text-xl lg:text-2xl">Mark as done</h3>
        {DEMO && (
          <button
            className="text-sm font-semibold text-link"
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
        <FileTile label="Invoice (PDF)" sub="Invoice PDF" accept="application/pdf,.pdf" icon="file" file={invoice} onFile={setInvoice} />
      </div>
      <input
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="What did you do? e.g. Ignition electrode replaced"
        className="w-full rounded border-[1.5px] border-line px-4 py-3.5 text-body-sm focus:border-plum focus:outline-none"
      />
      <div className="flex flex-wrap items-center gap-4">
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
          {busy ? 'Uploading…' : 'Mark as done'} <Icon name="arrow" className="h-5 w-5" />
        </button>
        <Hint>Debye reads the invoice and asks {name} if it is warm again.</Hint>
      </div>
      <Err err={err} />
    </div>
  )
}

function Done({ job, staffName }: ActionProps) {
  const invoice = job.documents.find((d) => d.kind === 'invoice')
  const after = job.photos?.find((p) => p.filename.startsWith('after'))
  const x = (invoice?.extracted ?? {}) as Record<string, unknown>
  const ok = priceCheckOk(job.price_check)
  const [fields, setFields] = useState(false)
  const confirmed = job.events?.find((e) => e.kind === 'tenant.confirmed_fixed' || e.kind === 'case.closed')
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-5 rounded-lg bg-success-soft p-5 text-success">
        <span className="inline-flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-success text-on-plum">
          <Icon name="check" className="h-7 w-7" />
        </span>
        <div>
          <div className="text-xl font-semibold lg:text-2xl">Job done. Thank you{staffName ? `, ${staffName.split(' ')[0]}` : ''}.</div>
          <div className="text-body-sm">
            {job.status === 'closed' ? 'Invoice sent to reltix' : 'Debye is checking the invoice'}
            {ok ? ' · price check ok' : ''} · paid within 14 days per framework
          </div>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {invoice && (
          <div className="rounded-lg border border-line p-4">
            <a href={invoice.url} target="_blank" rel="noreferrer" className="flex items-center gap-4">
              <span className="inline-flex h-12 w-12 items-center justify-center rounded-lg bg-surface-alt text-plum-80">
                <Icon name="file" className="h-6 w-6" />
              </span>
              <span className="min-w-0">
                <span className="block truncate font-semibold">{invoice.filename}</span>
                <span className="block text-sm text-muted">{typeof x.gross_eur === 'number' ? `${fmtEur(x.gross_eur as number, true)} gross · read by Debye` : 'Reading…'}</span>
              </span>
            </a>
            {Object.keys(x).length > 0 && (
              <button className="mt-2 text-sm font-semibold text-link" onClick={() => setFields(!fields)}>
                {fields ? 'Hide' : 'Show'} extracted fields
              </button>
            )}
            {fields && <InvoiceFields x={x} />}
          </div>
        )}
        {after && (
          <a href={after.url} target="_blank" rel="noreferrer" className="flex items-center gap-4 rounded-lg border border-line p-4">
            <img src={after.url} alt="" className="h-12 w-12 rounded-lg object-cover" />
            <span className="min-w-0">
              <span className="block truncate font-semibold">{after.filename}</span>
              <span className="block text-sm text-muted">Attached to the unit</span>
            </span>
          </a>
        )}
      </div>
      {confirmed && job.status === 'closed' && <div className="text-body-sm text-muted">Tenant confirmed on WhatsApp it is warm again · {fmtTime(confirmed.ts)}</div>}
    </div>
  )
}
