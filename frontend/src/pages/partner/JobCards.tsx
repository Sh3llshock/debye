// v3 job cards: New job (accept + technician + times), Work in progress (track + report), invoice panel.
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Icon } from '../../components/icons'
import { api, DEMO } from '../../api/client'
import type { JobDetail, Slot, Technician } from '../../api/types'
import { fmtSlot } from '../../lib/format'
import { t } from '../../lib/i18n'
import { useResource } from '../../lib/useResource'
import { costCap, eur0, eur2, firstName, jobRows, KV, needsTimes, priceCheck, received, Shot, Story, title, TRACK, trackIndex, tradeOf, urgencyPill } from './shared'

type Put = (j: JobDetail) => void
type Toast = (s: string) => void

// ---------- technicians + their free slots ----------
export function useTechs(pid: string) {
  return useResource(() => api.technicians(pid).catch(() => [] as Technician[]), [pid])
}

/** Free slots of one technician from now on (sorted, max n). */
export function freeSlots(tech: Technician | null | undefined, n = 8): Slot[] {
  if (!tech) return []
  const now = Date.now()
  return [...tech.free_slots].filter((s) => new Date(s.end).getTime() > now).sort((a, b) => a.start.localeCompare(b.start)).slice(0, n)
}

/** Technician matching the device make, else the first one. */
export function bestTech(techs: Technician[], job?: JobDetail | null): Technician | null {
  if (!techs.length) return null
  const make = job?.asset?.make?.toLowerCase()
  return techs.find((x) => make && x.skills.some((s) => s.toLowerCase().includes(make))) ?? techs.find((x) => x.free_slots.length) ?? techs[0]
}

/** "Technician [select]  Propose times [pills]" — shared by New jobs, WIP and Availability. */
export function TimePicker({ techs, techId, setTechId, picked, setPicked, disabled }: { techs: Technician[]; techId: string | null; setTechId: (id: string) => void; picked: Slot[]; setPicked: (s: Slot[]) => void; disabled?: boolean }) {
  const tech = techs.find((x) => x.tech_id === techId) ?? null
  const slots = freeSlots(tech)
  const toggle = (s: Slot) => setPicked(picked.some((x) => x.start === s.start) ? picked.filter((x) => x.start !== s.start) : picked.length >= 3 ? picked : [...picked, s])
  return (
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2.5">
      {techs.length > 0 && (
        <>
          <span className="text-muted">{t('Technician')}</span>
          <select
            className="rounded-[8px] bg-surface px-2.5 py-[7px] shadow-ring"
            value={techId ?? ''}
            disabled={disabled}
            onChange={(e) => {
              setTechId(e.target.value)
              setPicked([])
            }}
          >
            {techs.map((x) => (
              <option key={x.tech_id} value={x.tech_id}>
                {x.name}
              </option>
            ))}
          </select>
        </>
      )}
      <span className="text-muted">{t('Propose times')}</span>
      {slots.length ? (
        <div className="flex flex-wrap gap-1.5">
          {slots.map((s) => {
            const on = picked.some((x) => x.start === s.start)
            return (
              <button
                key={s.start}
                type="button"
                disabled={disabled}
                aria-pressed={on}
                onClick={() => toggle(s)}
                className={`rounded-full px-3 py-1.5 text-label font-medium transition-colors ${on ? 'bg-wine text-cream' : 'bg-surface text-ink shadow-ring hover:bg-beige'}`}
              >
                {on && <Icon name="check" className="mr-1 inline h-3.5 w-3.5 align-[-2px]" />}
                {fmtSlot(s)}
              </button>
            )
          })}
        </div>
      ) : (
        <span className="text-label text-muted">{tech ? t('{name} has no free slots in the next days', { name: firstName(tech.name) }) : t('No technician yet')}</span>
      )}
    </div>
  )
}

const DECLINE_REASONS = ['No capacity', 'Outside my area', 'Not my trade']

function useRun(put: Put) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const run = async (fn: () => Promise<JobDetail>, ok?: () => void) => {
    setBusy(true)
    setErr(null)
    try {
      put(await fn())
      ok?.()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return { busy, err, run }
}

function ErrLine({ err }: { err: string | null }) {
  return err ? <div className="mx-5 mb-4 rounded-[12px] bg-red-tint px-3.5 py-3 text-red">{err}</div> : null
}

// ---------- card frame ----------
function JobTop({ job, pills, meta }: { job: JobDetail; pills: ReactNode; meta: ReactNode }) {
  const cap = costCap(job.estimated_cost_eur)
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-[18px]">
      <div className="min-w-0">
        <div className="flex flex-wrap gap-1.5">{pills}</div>
        <h3 className="mt-1.5 text-[20px] font-semibold leading-tight">{title(job)}</h3>
        <div className="mt-[3px] text-muted">{meta}</div>
      </div>
      {cap != null && (
        <div className="flex-none text-right">
          <div className="text-meta text-muted">{t('Cost cap')}</div>
          <div className="text-[22px] font-semibold tracking-[-0.02em]">{eur0(cap)}</div>
        </div>
      )}
    </div>
  )
}

function JobBody({ job, time, className = '' }: { job: JobDetail; time?: ReactNode; className?: string }) {
  return (
    <div className={`grid grid-cols-1 gap-5 px-5 py-[18px] md:grid-cols-[200px_minmax(0,1fr)] ${className}`}>
      <Shot job={job} />
      <KV rows={jobRows(job, { time })} />
    </div>
  )
}

function ActBar({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2.5 border-t border-line bg-bg px-5 py-3.5">{children}</div>
}

export const caseRef = (j: JobDetail) => `${t('Case')} ${j.case_id.replace(/^case_0*/, '')}`

// ---------- New job ----------
export function NewJobCard({ job, pid, techs, put, toast, onAccepted }: { job: JobDetail; pid: string; techs: Technician[]; put: Put; toast: Toast; onAccepted?: () => void }) {
  const { busy, err, run } = useRun(put)
  const [techId, setTechId] = useState<string | null>(null)
  const [picked, setPicked] = useState<Slot[]>([])
  const [why, setWhy] = useState('')
  useEffect(() => {
    if (!techId && techs.length) setTechId(bestTech(techs, job)?.tech_id ?? null)
  }, [techs, techId, job])
  const u = urgencyPill(job.priority)
  const who = firstName(job.tenant?.name) || t('the tenant')
  return (
    <article className="overflow-hidden rounded-panel bg-surface shadow-card [&+&]:mt-[18px]">
      <JobTop
        job={job}
        pills={
          <>
            <span className={`pill ${u.cls}`}>{u.text}</span>
            <span className="pill">{tradeOf(job)}</span>
            <span className="pill bg-blue-tint text-blue">{t('Live')}</span>
          </>
        }
        meta={`${caseRef(job)} · ${t('received {when}', { when: received(job.created_at) })}`}
      />
      <JobBody job={job} />
      <Story job={job} />
      <ErrLine err={err} />
      <ActBar>
        <TimePicker techs={techs} techId={techId} setTechId={setTechId} picked={picked} setPicked={setPicked} disabled={busy} />
        <div className="ml-auto flex flex-wrap items-center gap-2.5">
          <select className="rounded-[8px] bg-surface px-2.5 py-[7px] shadow-ring" value={why} onChange={(e) => setWhy(e.target.value)} aria-label={t('Decline reason…')}>
            <option value="">{t('Decline reason…')}</option>
            {DECLINE_REASONS.map((r) => (
              <option key={r} value={r}>
                {t(r)}
              </option>
            ))}
          </select>
          <button
            className="btn-secondary"
            disabled={busy}
            onClick={() => {
              if (!why) return toast(t('Pick a reason first'))
              run(() => api.decline(pid, job.case_id, why), () => toast(t('Declined · offered to the next partner')))
            }}
          >
            {t('Decline')}
          </button>
          <button
            className="btn-success"
            disabled={busy}
            onClick={() =>
              run(
                async () => {
                  const acc = await api.accept(pid, job.case_id)
                  if (!picked.length) return acc
                  return api.slots(pid, job.case_id, [...picked].sort((a, b) => a.start.localeCompare(b.start)), techId ?? undefined)
                },
                () => {
                  toast(picked.length ? t('Accepted · {n} times sent · {who} picks one on WhatsApp', { n: picked.length, who }) : t('Accepted · now pick a technician and times'))
                  onAccepted?.()
                },
              )
            }
          >
            {busy ? t('Accepting…') : t('Accept job')}
          </button>
        </div>
      </ActBar>
    </article>
  )
}

// ---------- Work in progress ----------
export function WipCard({ job, pid, techs, put, toast, onCompleted }: { job: JobDetail; pid: string; techs: Technician[]; put: Put; toast: Toast; onCompleted?: (j: JobDetail) => void }) {
  const { busy, err, run } = useRun(put)
  const idx = trackIndex(job.status)
  const pick = needsTimes(job)
  const [techId, setTechId] = useState<string | null>(null)
  const [picked, setPicked] = useState<Slot[]>([])
  const [report, setReport] = useState(false)
  const [notes, setNotes] = useState('')
  const [photo, setPhoto] = useState<File | null>(null)
  useEffect(() => {
    if (pick && !techId && techs.length) setTechId(bestTech(techs, job)?.tech_id ?? null)
  }, [pick, techs, techId, job])
  const who = firstName(job.tenant?.name) || t('the tenant')
  const tech = job.technician
  const slot = job.confirmed_slot ?? job.slot
  const time = slot ? (
    <>
      {fmtSlot(slot)}
      {job.status === 'awaiting_technician' && <span className="pill ml-1.5 bg-wine-tint text-wine">{t('waiting for {tech} to confirm', { tech: firstName(tech?.name) || t('the technician') })}</span>}
    </>
  ) : job.proposed_slots?.length ? (
    <>
      {job.proposed_slots.map((s) => fmtSlot(s)).join(' · ')} <span className="pill ml-1.5 bg-wine-tint text-wine">{t('waiting for tenant to pick')}</span>
    </>
  ) : (
    <span className="text-muted">{t('No time yet')}</span>
  )
  return (
    <article className="overflow-hidden rounded-panel bg-surface shadow-card [&+&]:mt-[18px]">
      <JobTop
        job={job}
        pills={
          <>
            <span className="pill bg-blue-tint text-blue">{pick ? t('Pick times') : t(TRACK[idx].label)}</span>
            <span className="pill">{tradeOf(job)}</span>
          </>
        }
        meta={[caseRef(job), slot ? fmtSlot(slot) : null, tech?.name].filter(Boolean).join(' · ')}
      />
      <div className="mx-5 mb-4 mt-3.5 grid grid-cols-5 gap-[3px] rounded-[11px] bg-beige p-[3px]">
        {TRACK.map((s, i) => (
          <div
            key={s.key}
            className={`truncate rounded-[8px] px-1 py-[7px] text-center text-meta font-semibold sm:px-2.5 ${i < idx ? 'text-ok' : i === idx ? 'bg-surface text-ink shadow-[0_1px_3px_rgba(0,0,0,.12)]' : 'text-muted'}`}
            title={t(s.label)}
          >
            {i < idx && <Icon name="check" className="mr-1 inline h-3.5 w-3.5 align-[-2px]" />}
            {t(s.label)}
          </div>
        ))}
      </div>
      <JobBody job={job} time={time} className="pt-0" />
      <details className="group border-t border-line">
        <summary className="cursor-pointer list-none px-5 py-[13px] font-medium text-wine">
          <Icon name="chevron" className="mr-2 inline-block h-4 w-4 align-[-3px] transition-transform group-open:rotate-90" />
          {t('Chat summary and how we got to the diagnosis')}
        </summary>
        <Story job={job} bordered={false} />
      </details>
      {report && (
        <div className="grid grid-cols-1 gap-x-4 gap-y-3 border-t border-line px-5 py-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <label className="text-label font-medium text-secondary">{t('Work done')}</label>
            <textarea className="field" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder={t('e.g. ignition electrode replaced, test run OK')} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-label font-medium text-secondary">{t('Photo after the repair')}</label>
            <label className={`btn-secondary min-h-0 cursor-pointer self-start px-3 py-1.5 text-label ${photo ? 'bg-ok-tint text-ok' : ''}`}>
              <Icon name="camera" className="mr-1.5 inline h-4 w-4 align-[-3px]" />
              {photo ? photo.name : t('Add photo')}
              <input type="file" accept="image/*" capture="environment" className="sr-only" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
            </label>
          </div>
          {DEMO && (
            <div className="flex items-end">
              <button
                type="button"
                className="link-btn"
                onClick={async () => {
                  setPhoto(await demoFile('/demo-media/repair_done.jpg', 'after_repair.jpg', 'image/jpeg'))
                  setNotes('Repair done, tested with the tenant, everything works again.')
                }}
              >
                {t('Use demo files')}
              </button>
            </div>
          )}
        </div>
      )}
      <ErrLine err={err} />
      <ActBar>
        {job.tenant?.phone && (
          <a className="btn-ghost min-h-0 px-3 py-1.5 text-label" href={`tel:${job.tenant.phone}`}>
            {t('Call tenant')}
          </a>
        )}
        {pick ? (
          <>
            <TimePicker techs={techs} techId={techId} setTechId={setTechId} picked={picked} setPicked={setPicked} disabled={busy} />
            <button
              className="btn-primary ml-auto"
              disabled={busy || !picked.length}
              onClick={() => run(() => api.slots(pid, job.case_id, [...picked].sort((a, b) => a.start.localeCompare(b.start)), techId ?? undefined), () => toast(t('{n} times sent · {who} picks one on WhatsApp', { n: picked.length, who })))}
            >
              {busy ? t('Sending…') : picked.length ? t('Send {n} times to {who}', { n: picked.length, who }) : t('Pick a time')}
            </button>
          </>
        ) : (
          <>
            <span className="flex-1" />
            {job.status === 'slots_proposed' && <span className="text-muted">{t('Waiting for {who} to pick one of the times on WhatsApp', { who })}</span>}
            {job.status === 'awaiting_technician' && (
              <>
                <span className="text-muted">{t('{who} picked {slot}. Waiting for {tech} to confirm.', { who, slot: slot ? fmtSlot(slot) : '', tech: firstName(tech?.name) || t('the technician') })}</span>
                {tech && (
                  <Link to={`/tech/${tech.tech_id}`} className="btn-secondary min-h-0 px-3 py-1.5 text-label">
                    {t('Open as {name}', { name: firstName(tech.name) })} →
                  </Link>
                )}
              </>
            )}
            {(job.status === 'scheduled' || job.status === 'in_progress') &&
              (report ? (
                <button
                  className="btn-success"
                  disabled={busy}
                  onClick={() =>
                    run(
                      () => {
                        const f = new FormData()
                        f.append('notes', notes)
                        if (photo) f.append('photo', photo)
                        return api.complete(pid, job.case_id, f)
                      },
                      () => {
                        setReport(false)
                        toast(t('Job report sent · now add the invoice'))
                        onCompleted?.(job)
                      },
                    )
                  }
                >
                  {busy ? t('Sending…') : t('Submit job report')}
                </button>
              ) : (
                <button className="btn-success" onClick={() => setReport(true)}>
                  {t('Mark job done')}
                </button>
              ))}
          </>
        )}
      </ActBar>
    </article>
  )
}

async function demoFile(url: string, name: string, type: string) {
  const blob = await fetch(url).then((r) => r.blob())
  return new File([blob], name, { type })
}

// ---------- invoice ----------
export function invoiceOf(job: JobDetail) {
  const doc = job.documents?.find((d) => d.kind === 'invoice')
  const x = (doc?.extracted ?? {}) as Record<string, unknown>
  const num = (k: string) => (typeof x[k] === 'number' ? (x[k] as number) : null)
  return { doc, no: (x.invoice_number ?? x.number ?? doc?.filename ?? '') as string, gross: num('gross_eur'), net: num('net_eur'), vat: num('vat_eur'), date: (x.invoice_date ?? x.date ?? '') as string, check: priceCheck(x.price_check ?? job.price_check) }
}

/** The mockup's invoice panel: upload a photo/PDF, Debye reads the numbers and checks them against the cap. */
export function InvoicePanel({ job, pid, put, toast, onClose }: { job: JobDetail; pid: string; put: Put; toast: Toast; onClose: () => void }) {
  const { busy, err, run } = useRun(put)
  const [file, setFile] = useState<File | null>(null)
  const cap = costCap(job.estimated_cost_eur)
  const notes = String((job.completion as { notes?: string } | null)?.notes ?? '')
  const send = (f: File) =>
    run(
      () => {
        const fd = new FormData()
        fd.append('notes', notes)
        fd.append('invoice', f)
        return api.complete(pid, job.case_id, fd)
      },
      () => {
        toast(t('Invoice submitted · Debye read it'))
        onClose()
      },
    )
  return (
    <div className="mt-[18px] rounded-[18px] bg-wine-tint p-5 shadow-[0_0_0_1.5px_rgba(107,31,51,.35)]">
      <h3 className="mb-1 text-[17px] font-semibold">{t('Invoice for {title}', { title: title(job) })}</h3>
      <p className="m-0 text-muted">{t('Upload a PDF or a photo of the paper invoice. We read the numbers for you.')}</p>
      {cap != null && <p className="mb-0 mt-1 text-muted">{t('Cost cap {eur} incl. VAT. Within the cap it is approved automatically; paid within 14 days.', { eur: eur2(cap) })}</p>}
      {err && <div className="mt-3 rounded-[12px] bg-red-tint px-3.5 py-3 text-red">{err}</div>}
      <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
        <label className="btn-primary cursor-pointer">
          <Icon name="upload" className="mr-1.5 inline h-4 w-4 align-[-3px]" />
          {file ? file.name : t('Upload invoice photo / PDF')}
          <input type="file" accept="image/*,.pdf,application/pdf" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        {DEMO && !file && (
          <button type="button" className="link-btn" onClick={async () => setFile(await demoFile('/demo-media/invoice_RE-2026-1187.pdf', 'RE-2026-1187.pdf', 'application/pdf'))}>
            {t('Use demo invoice')}
          </button>
        )}
        {file && (
          <button className="btn-success" disabled={busy} onClick={() => send(file)}>
            {busy ? t('Reading…') : t('Submit invoice')}
          </button>
        )}
        <button className="btn-ghost" onClick={onClose}>
          {t('Cancel')}
        </button>
      </div>
    </div>
  )
}

/** After upload: what Debye read + the cap check (the mockup's check-row). */
export function InvoiceRead({ job }: { job: JobDetail }) {
  const inv = invoiceOf(job)
  const cap = costCap(job.estimated_cost_eur)
  const within = inv.gross != null && cap != null ? inv.gross <= cap : null
  const tone = inv.check === 'flagged' || within === false ? 'warn' : 'ok'
  return useMemo(
    () =>
      inv.doc ? (
        <div className={`mt-2 flex items-start gap-2 rounded-[12px] px-3.5 py-3 font-medium ${tone === 'ok' ? 'bg-ok-tint text-ok' : 'bg-warn-tint text-warn'}`}>
          <Icon name={tone === 'ok' ? 'check' : 'alert'} className={`mt-0.5 h-4 w-4 flex-none ${tone === 'ok' ? 'text-ok' : 'text-warn'}`} />
          <span>
            {inv.gross != null
              ? tone === 'ok'
                ? `${t('{eur} read from {file}', { eur: eur2(inv.gross), file: inv.doc.filename })}${cap != null ? ` · ${t('within the {cap} cost cap', { cap: eur2(cap) })}` : ''} · ${t('paid within 14 days')}`
                : `${t('{eur} read from {file}', { eur: eur2(inv.gross), file: inv.doc.filename })} · ${t('the property manager checks the difference')}`
              : `${inv.doc.filename} · ${t('Reading…')}`}
          </span>
        </div>
      ) : null,
    [inv.doc, inv.gross, tone, cap], // eslint-disable-line react-hooks/exhaustive-deps
  )
}
