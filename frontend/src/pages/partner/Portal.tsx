// v3 partner portal (docs/design/v3/partner-portal1.html): Overview, New jobs, Work in progress,
// Availability, Done jobs & invoices, Profile, and a single job at /partner/:pid/jobs/:caseId.
// Real data: /api/partner/{pid}, /jobs, /jobs/{id}, /technicians; live via SSE.
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import type { JobDetail, PartnerProfile, Slot, Technician } from '../../api/types'
import { PartnerLayout } from '../../components/Layout'
import { ErrorBox, Loading } from '../../components/ui'
import { fmtSlot } from '../../lib/format'
import { locale, t } from '../../lib/i18n'
import { useResource } from '../../lib/useResource'
import { bestTech, caseRef, freeSlots, InvoicePanel, InvoiceRead, invoiceOf, NewJobCard, useTechs, WipCard } from './JobCards'
import { EMPTY_PROFILE, ProfileField, STEPS, type Profile } from './Welcome'
import {
  Card,
  CardTitle,
  CheckPill,
  costCap,
  Empty,
  eur0,
  eur2,
  firstName,
  Head,
  isDone,
  isNew,
  isWip,
  loadLocalProfile,
  needsTimes,
  saveLocalProfile,
  setSession,
  stageLabel,
  title,
  usePartnerJobs,
  useToast,
} from './shared'
import { needsReviewGate, ReviewStatus } from './ReviewStatus'

export type Tab = 'overview' | 'new' | 'wip' | 'availability' | 'done' | 'profile'

/** /partner/:partnerId[/new|/wip|/availability|/done|/profile] and /partner/:partnerId/jobs/:caseId */
export default function PartnerPortal({ tab = 'overview' }: { tab?: Tab }) {
  const { partnerId = '', caseId } = useParams()
  const nav = useNavigate()
  const partner = useResource(() => api.partner(partnerId), [partnerId])
  const { jobs, details, error, reload, put } = usePartnerJobs(partnerId)
  const techs = useTechs(partnerId)
  const [toastNode, toast] = useToast()
  const [invoiceOpen, setInvoiceOpen] = useState<string | null>(null)

  const local = useMemo(() => loadLocalProfile(partnerId), [partnerId])
  const p = partner.data
  const contact = (local?.contact_name as string | undefined) || p?.staff?.[0]?.name || ''
  const all = (jobs ?? []).map((j) => details[j.case_id]).filter((d): d is JobDetail => !!d)
  const nNew = all.filter(isNew).length
  const nWip = all.filter(isWip).length
  const nInv = all.filter((j) => j.status === 'completed').length
  const nReq = all.filter(needsTimes).length

  const ctx: Ctx = { pid: partnerId, partner: p ?? null, contact, all, techs: techs.data ?? [], put, toast, nav, invoiceOpen, setInvoiceOpen, loading: !jobs }
  let body: ReactNode
  if (partner.error && !p) body = <ErrorBox error={partner.error} onRetry={partner.reload} />
  else if (p && needsReviewGate(p) && tab !== 'profile') body = <ReviewStatus p={p} />
  else if (error && !jobs) body = <ErrorBox error={error} onRetry={reload} />
  else if (caseId) body = <OneJob ctx={ctx} caseId={caseId} />
  else
    body = {
      overview: <Overview ctx={ctx} />,
      new: <NewJobs ctx={ctx} />,
      wip: <Wip ctx={ctx} />,
      availability: <Availability ctx={ctx} />,
      done: <DoneJobs ctx={ctx} />,
      profile: <ProfileView ctx={ctx} local={local} />,
    }[tab]

  return (
    <PartnerLayout partnerId={partnerId} partnerName={p?.name} contact={contact} counts={{ new: nNew, wip: nWip, availability: nReq, done: nInv }} crumbs={caseId ? [{ label: t('Jobs'), to: `/partner/${partnerId}` }, { label: caseId }] : []}>
      {body}
      {toastNode}
    </PartnerLayout>
  )
}

type Ctx = {
  pid: string
  partner: PartnerProfile | null
  contact: string
  all: JobDetail[]
  techs: Technician[]
  put: (j: JobDetail) => void
  toast: (s: string) => void
  nav: ReturnType<typeof useNavigate>
  invoiceOpen: string | null
  setInvoiceOpen: (id: string | null) => void
  loading: boolean
}

const slotSoon = (j: JobDetail) => (j.confirmed_slot ?? j.slot)?.start ?? j.proposed_slots?.[0]?.start ?? '9999'

// ---------------------------------------------------------------- overview

function Overview({ ctx }: { ctx: Ctx }) {
  const { all, pid, partner, contact } = ctx
  const fresh = all.filter(isNew)
  const wip = all.filter(isWip).sort((a, b) => slotSoon(a).localeCompare(slotSoon(b)))
  const waitInv = all.filter((j) => j.status === 'completed')
  const invoiced = all.filter((j) => j.status === 'invoiced' || j.status === 'closed')
  const monthSum = invoiced.reduce((a, j) => a + (invoiceOf(j).gross ?? 0), 0)
  const payout = all.filter((j) => j.status === 'invoiced').reduce((a, j) => a + (invoiceOf(j).gross ?? 0), 0)
  const next = wip.find((j) => j.confirmed_slot ?? j.slot) ?? wip[0]
  const reqs = all.filter(needsTimes)
  const waitTenant = all.filter((j) => j.status === 'slots_proposed')
  const att: [string, string | number, string, string, string, string][] = []
  if (fresh.length) att.push(['hot', fresh.length, fresh.length > 1 ? t('New job requests') : t('New job request'), t('Accept within 2 hours, or it goes to the next partner'), 'new', t('Review')])
  if (reqs.length) att.push(['hot', reqs.length, reqs.length > 1 ? t('Slot requests') : t('Slot request'), t('Debye needs times for an accepted job'), 'availability', t('Answer')])
  if (waitInv.length) att.push(['', waitInv.length, waitInv.length > 1 ? t('Jobs without an invoice') : t('Job without an invoice'), t('Upload a photo of the invoice to get paid'), 'done', t('Add invoice')])
  if (waitTenant.length) att.push(['wait', waitTenant.length, t('Waiting for the tenant'), t('They pick one of your times on WhatsApp'), 'wip', t('View')])
  const go = (k: string) => ctx.nav(`/partner/${pid}${k === 'overview' ? '' : `/${k}`}`)
  const slot = next ? (next.confirmed_slot ?? next.slot) : null
  const d = slot ? new Date(slot.start) : null
  return (
    <>
      <Head
        title={t('Hello, {name}', { name: firstName(contact) || partner?.name || t('there') })}
        sub={`${new Date().toLocaleDateString(locale(), { weekday: 'long', day: 'numeric', month: 'long' })} · ${partner?.name ?? pid}`}
        right={<span className="pill bg-ok-tint text-ok">✓ {t('Verified partner')}</span>}
      />
      <div className="mb-[18px] grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        <Kpi label={t('New job requests')} value={fresh.length} onClick={() => go('new')} />
        <Kpi label={t('Work in progress')} value={wip.length} onClick={() => go('wip')} />
        <Kpi label={t('Waiting for your invoice')} value={waitInv.length} onClick={() => go('done')} />
        <Kpi label={t('Invoiced this month')} value={eur0(monthSum)} onClick={() => go('done')} />
      </div>
      {ctx.loading && <Loading what={t('Loading jobs')} />}
      <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-2">
        <OvCard title={t('Next appointment')} right={next ? <span className={`pill ${next.status === 'scheduled' ? 'bg-blue-tint text-blue' : ''}`}>{stageLabel(next)}</span> : null}>
          {next ? (
            <>
              <div className="mb-4 grid grid-cols-[74px_minmax(0,1fr)] items-center gap-4">
                <div className="flex h-[74px] flex-col items-center justify-center rounded-tile bg-wine-tint text-wine">
                  <span className="text-meta font-medium uppercase tracking-[.04em]">{d ? d.toLocaleDateString(locale(), { weekday: 'short', timeZone: 'Europe/Berlin' }) : '–'}</span>
                  <b className="text-[20px] font-medium">{d ? d.toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Berlin' }) : '–'}</b>
                </div>
                <div className="min-w-0">
                  <div className="text-[18px] font-medium tracking-[-0.02em]">{title(next)}</div>
                  <div className="text-muted">{slot ? fmtSlot(slot) : t('Times offered, tenant picks')}</div>
                </div>
              </div>
              <OvKV
                rows={[
                  [t('Address'), next.address ?? next.postcode ?? '–'],
                  [t('Tenant'), next.tenant ? `${firstName(next.tenant.name)}${next.tenant.phone ? ` · ${next.tenant.phone}` : ''}` : '–'],
                  [t('Technician'), next.technician?.name ?? '–'],
                  [t('Cost cap'), eur2(costCap(next.estimated_cost_eur))],
                ]}
              />
              <div className="mt-auto flex flex-wrap gap-2 pt-[18px]">
                <Link to={`/partner/${pid}/jobs/${next.case_id}`} className="btn-primary">
                  {t('Open job')}
                </Link>
                {next.tenant?.phone && (
                  <a href={`tel:${next.tenant.phone}`} className="btn-ghost">
                    {t('Call tenant')}
                  </a>
                )}
              </div>
            </>
          ) : (
            <Empty className="px-0 py-6">{t('Nothing scheduled. Accepted jobs show up here.')}</Empty>
          )}
        </OvCard>
        <OvCard title={t('Needs your attention')} right={att.length ? <span className="pill bg-wine-tint text-wine">{att.length}</span> : null}>
          {att.length ? (
            <ul className="m-0 flex list-none flex-col p-0">
              {att.map(([k, c, head, sub, tab, b]) => (
                <li key={head} className="grid grid-cols-[34px_minmax(0,1fr)_auto] items-center gap-3 border-t border-line py-3 first:border-t-0 first:pt-0">
                  <span className={`grid h-[34px] w-[34px] place-items-center rounded-[10px] text-[14px] font-medium ${k === 'hot' ? 'bg-wine-tint text-wine' : k === 'wait' ? 'bg-blue-tint text-blue' : 'bg-beige text-ink'}`}>{c}</span>
                  <div className="min-w-0">
                    <b className="block font-medium">{head}</b>
                    <span className="text-label text-muted">{sub}</span>
                  </div>
                  <button className={`${k === 'hot' ? 'btn-primary' : 'btn-secondary'} min-h-0 px-3 py-1.5 text-label`} onClick={() => go(tab)}>
                    {b}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-1 py-4 text-center">
              <span className="mb-1 grid h-10 w-10 place-items-center rounded-full bg-ok-tint font-medium text-ok">✓</span>
              <b>{t('All caught up')}</b>
              <span className="text-muted">{t('No new jobs, requests or missing invoices.')}</span>
            </div>
          )}
        </OvCard>
        <OvCard title={t('Coming up')}>
          {wip.length ? (
            <div className="-mx-2 overflow-x-auto">
              <table className="t">
                <tbody>
                  {wip.map((j) => {
                    const s = j.confirmed_slot ?? j.slot
                    return (
                      <tr key={j.case_id} className="click" onClick={() => ctx.nav(`/partner/${pid}/jobs/${j.case_id}`)}>
                        <td className="w-[150px]">
                          <b>{s ? fmtSlot(s) : '–'}</b>
                        </td>
                        <td>
                          <b>{title(j)}</b>
                          <br />
                          <span className="text-muted">{j.address ?? j.postcode}</span>
                        </td>
                        <td className="hidden sm:table-cell">{j.technician?.name ?? ''}</td>
                        <td className="text-right">
                          <span className={`pill ${j.status === 'scheduled' ? 'bg-blue-tint text-blue' : ''}`}>{stageLabel(j)}</span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty className="px-0 py-6">{t('No upcoming jobs.')}</Empty>
          )}
        </OvCard>
        <OvCard title={t('Your record with Debye')}>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <Mini v={partner?.rating ?? '–'} l={t('Rating')} />
            <Mini v={all.filter((j) => !isDone(j)).length} l={t('Open jobs')} />
            <Mini v={all.filter(isDone).length} l={t('Jobs done')} />
            <Mini v={eur0(payout)} l={t('Being paid out')} />
          </div>
          <p className="mb-0 mt-3.5 text-muted">{t('Ranking uses brand certification, availability, framework price and rating. Keep your availability up to date to get more jobs.')}</p>
        </OvCard>
      </div>
    </>
  )
}

function Kpi({ label, value, onClick }: { label: string; value: ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className="rounded-panel bg-surface p-[18px] text-left shadow-card transition-transform hover:-translate-y-px">
      <span className="text-label text-muted">{label}</span>
      <b className="mt-1.5 block text-page font-medium">{value}</b>
    </button>
  )
}
function OvCard({ title: tt, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="card flex min-h-full min-w-0 flex-col">
      <CardTitle right={right} className="mb-4">
        {tt}
      </CardTitle>
      {children}
    </section>
  )
}
function OvKV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="m-0 grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-2">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="m-0 font-medium [overflow-wrap:anywhere]">{v}</dd>
        </div>
      ))}
    </dl>
  )
}
function Mini({ v, l }: { v: ReactNode; l: string }) {
  return (
    <div className="rounded-[12px] bg-bg px-3.5 py-3 shadow-ring">
      <b className="block text-[22px] font-medium">{v}</b>
      <span className="text-meta text-muted">{l}</span>
    </div>
  )
}

// ---------------------------------------------------------------- new jobs

function NewJobs({ ctx }: { ctx: Ctx }) {
  const list = ctx.all.filter(isNew)
  return (
    <>
      <Head title={t('New jobs')} sub={t('Only jobs that match your trades, brands and area. Accept within 2 hours, or the next partner gets it.')} />
      {ctx.loading ? (
        <Loading what={t('Loading jobs')} />
      ) : list.length ? (
        list.map((j) => <NewJobCard key={j.case_id} job={j} pid={ctx.pid} techs={ctx.techs} put={ctx.put} toast={ctx.toast} onAccepted={() => ctx.nav(`/partner/${ctx.pid}/wip`)} />)
      ) : (
        <Card>
          <Empty>{t('No new jobs right now. We’ll message you on WhatsApp when one comes in.')}</Empty>
        </Card>
      )}
    </>
  )
}

// ---------------------------------------------------------------- work in progress

function Wip({ ctx }: { ctx: Ctx }) {
  const list = ctx.all.filter(isWip).sort((a, b) => slotSoon(a).localeCompare(slotSoon(b)))
  return (
    <>
      <Head title={t('Work in progress')} sub={t('Update the status as you go. The tenant and property manager see it live.')} />
      {ctx.loading ? (
        <Loading what={t('Loading jobs')} />
      ) : list.length ? (
        list.map((j) => (
          <WipCard
            key={j.case_id}
            job={j}
            pid={ctx.pid}
            techs={ctx.techs}
            put={ctx.put}
            toast={ctx.toast}
            onCompleted={(job) => {
              ctx.setInvoiceOpen(job.case_id)
              ctx.nav(`/partner/${ctx.pid}/done`)
            }}
          />
        ))
      ) : (
        <Card>
          <Empty>{t('Nothing in progress. Accepted jobs show up here.')}</Empty>
        </Card>
      )}
    </>
  )
}

// ---------------------------------------------------------------- availability

const BLOCKS: [string, string][] = [
  ['08', '10'],
  ['10', '12'],
  ['12', '14'],
  ['14', '16'],
  ['16', '18'],
]
const isoDay = (d: Date) => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Berlin' }).format(d)
type AvailStore = { cells: Record<string, boolean>; off: { from: string; to: string; why: string }[] }
const AKEY = (pid: string) => `debye-partner-avail:${pid}`
function loadAvail(pid: string): AvailStore {
  try {
    return { cells: {}, off: [], ...JSON.parse(localStorage.getItem(AKEY(pid)) ?? '{}') }
  } catch {
    return { cells: {}, off: [] }
  }
}

function Availability({ ctx }: { ctx: Ctx }) {
  const { pid, techs } = ctx
  const [week, setWeek] = useState(0)
  const [store, setStore] = useState<AvailStore>(() => loadAvail(pid))
  const save = (s: AvailStore) => {
    setStore(s)
    try {
      localStorage.setItem(AKEY(pid), JSON.stringify(s))
    } catch {
      /* private mode */
    }
  }
  const days = useMemo(() => {
    const out: { iso: string; label: string; day: string }[] = []
    for (let i = 0; i < 7; i++) {
      const x = new Date(Date.now() + (week * 7 + i) * 86400_000)
      out.push({
        iso: isoDay(x),
        label: x.toLocaleDateString(locale(), { weekday: 'short', timeZone: 'Europe/Berlin' }),
        day: x.toLocaleDateString(locale(), { day: 'numeric', month: 'short', timeZone: 'Europe/Berlin' }),
      })
    }
    return out
  }, [week])
  // From the technicians' calendars: a block is free if any technician has a free slot overlapping it.
  const fromTechs = (iso: string, [a, b]: [string, string]) =>
    techs.some((x) => x.free_slots.some((s) => s.start.slice(0, 10) === iso && s.start.slice(11, 13) < b && s.end.slice(11, 13) > a))
  const offOn = (iso: string) => store.off.find((o) => o.from <= iso && iso <= o.to)
  const isFree = (iso: string, bi: number) => (offOn(iso) ? false : `${iso}_${bi}` in store.cells ? store.cells[`${iso}_${bi}`] : fromTechs(iso, BLOCKS[bi]))
  const nFree = days.reduce((a, x) => a + BLOCKS.filter((_, bi) => isFree(x.iso, bi)).length, 0)
  const toggleCell = (iso: string, bi: number) => save({ ...store, cells: { ...store.cells, [`${iso}_${bi}`]: !isFree(iso, bi) } })
  const toggleDay = (iso: string) => {
    const allOn = BLOCKS.every((_, bi) => isFree(iso, bi))
    const cells = { ...store.cells }
    BLOCKS.forEach((_, bi) => (cells[`${iso}_${bi}`] = !allOn))
    save({ ...store, cells })
  }
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [why, setWhy] = useState('')
  const reqs = ctx.all.filter(needsTimes)
  return (
    <>
      <Head title={t('Availability')} sub={t('Mark when you’re free. We offer tenants only these times, so you rarely get asked.')} />
      <div className="grid grid-cols-1 items-start gap-[18px] xl:grid-cols-[1.3fr_1fr]">
        <Card className="min-w-0">
          <CardTitle
            right={
              <span className="flex gap-1">
                <button className="btn-ghost min-h-0 px-3 py-1.5 text-label" disabled={week === 0} onClick={() => setWeek(Math.max(0, week - 1))} aria-label={t('Previous week')}>
                  ‹
                </button>
                {week > 0 && (
                  <button className="btn-ghost min-h-0 px-3 py-1.5 text-label" onClick={() => setWeek(0)}>
                    {t('Today')}
                  </button>
                )}
                <button className="btn-ghost min-h-0 px-3 py-1.5 text-label" onClick={() => setWeek(week + 1)} aria-label={t('Next week')}>
                  ›
                </button>
              </span>
            }
          >
            {week === 0 ? t('Next 7 days') : week === 1 ? t('The 7 days after') : t('In {n} weeks', { n: week })}{' '}
            <span className="text-[14px] font-medium text-muted">
              · {days[0].day} – {days[6].day}
            </span>
          </CardTitle>
          <div className="-mx-1 overflow-x-auto px-1">
            <div className="grid min-w-[520px] grid-cols-[56px_repeat(7,minmax(0,1fr))] gap-1">
              <div />
              {days.map((x) => (
                <button key={x.iso} className="flex flex-col items-center gap-px rounded-[8px] px-0 pb-1.5 pt-1 text-[11.5px] font-medium text-muted hover:bg-[#F3EEE7]" onClick={() => toggleDay(x.iso)} title={t('Toggle the whole day')}>
                  <b className="text-label text-ink">{x.label}</b>
                  {x.day}
                </button>
              ))}
              {BLOCKS.map(([a, b], bi) => (
                <div key={a} className="contents">
                  <div className="flex items-center text-meta text-muted">
                    {a}–{b}
                  </div>
                  {days.map((x) => {
                    const off = offOn(x.iso)
                    const on = isFree(x.iso, bi)
                    return (
                      <button
                        key={x.iso}
                        disabled={!!off}
                        onClick={() => toggleCell(x.iso, bi)}
                        className={`h-[38px] rounded-[9px] text-[11px] font-medium ${off ? 'cursor-default bg-[repeating-linear-gradient(45deg,#F3EEE7,#F3EEE7_5px,#EFE8DF_5px,#EFE8DF_10px)] text-muted' : on ? 'bg-ok text-white' : 'bg-[#F3EEE7] text-muted'}`}
                      >
                        {off ? t('Off') : on ? t('Free') : ''}
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-3.5 text-meta text-muted">
            <span>
              <i className="mr-1.5 inline-block h-3 w-3 rounded-[3px] bg-ok align-[-2px]" />
              {t('Free')}
            </span>
            <span>
              <i className="mr-1.5 inline-block h-3 w-3 rounded-[3px] bg-[#F3EEE7] align-[-2px] shadow-ring" />
              {t('Busy')}
            </span>
            <span>
              <i className="mr-1.5 inline-block h-3 w-3 rounded-[3px] bg-[repeating-linear-gradient(45deg,#F3EEE7,#F3EEE7_2px,#E2D8CB_2px,#E2D8CB_4px)] align-[-2px]" />
              {t('Time off')}
            </span>
            <span className="sm:ml-auto">{t('{n} free blocks this week · click a block or a day to toggle', { n: nFree })}</span>
          </div>
          <p className="mb-0 mt-2 text-meta text-muted">{t('Pre-filled from your technicians’ calendars. Changes here are saved in this browser only (demo).')}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              className="btn-secondary min-h-0 px-3 py-1.5 text-label"
              onClick={() => {
                const cells = { ...store.cells }
                days.forEach((x, i) => {
                  const nx = isoDay(new Date(Date.now() + ((week + 1) * 7 + i) * 86400_000))
                  BLOCKS.forEach((_, bi) => (cells[`${nx}_${bi}`] = isFree(x.iso, bi)))
                })
                save({ ...store, cells })
                setWeek(week + 1)
                ctx.toast(t('Copied to the next 7 days'))
              }}
            >
              {t('Copy this week to the next')}
            </button>
            <button
              className="btn-ghost min-h-0 px-3 py-1.5 text-label"
              onClick={() => {
                const cells = { ...store.cells }
                days.forEach((x) => BLOCKS.forEach((_, bi) => (cells[`${x.iso}_${bi}`] = false)))
                save({ ...store, cells })
              }}
            >
              {t('Clear this week')}
            </button>
          </div>
        </Card>
        <div className="min-w-0">
          {reqs.map((j) => (
            <SlotRequest key={j.case_id} job={j} ctx={ctx} />
          ))}
          <Card className={reqs.length ? 'mt-4' : ''}>
            <CardTitle>{t('Time off')}</CardTitle>
            {store.off.length ? (
              <table className="t">
                <tbody>
                  {store.off.map((o, i) => (
                    <tr key={i}>
                      <td>
                        {o.from} → {o.to}
                      </td>
                      <td>{o.why}</td>
                      <td className="text-right">
                        <button className="btn-ghost min-h-0 px-3 py-1.5 text-label" onClick={() => save({ ...store, off: store.off.filter((_, k) => k !== i) })}>
                          {t('Remove')}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="m-0 text-muted">{t('No time off planned.')}</p>
            )}
            <div className="mt-3 grid grid-cols-2 items-end gap-3 sm:grid-cols-[1fr_1fr_1fr_auto]">
              <label className="flex min-w-0 flex-col gap-1.5 text-label font-medium text-secondary">
                {t('From')}
                <input type="date" className="field px-2" value={from} onChange={(e) => setFrom(e.target.value)} />
              </label>
              <label className="flex min-w-0 flex-col gap-1.5 text-label font-medium text-secondary">
                {t('To')}
                <input type="date" className="field px-2" value={to} onChange={(e) => setTo(e.target.value)} />
              </label>
              <label className="flex min-w-0 flex-col gap-1.5 text-label font-medium text-secondary">
                {t('Reason')}
                <input className="field" value={why} onChange={(e) => setWhy(e.target.value)} placeholder={t('Holiday')} />
              </label>
              <button
                className="btn-secondary"
                onClick={() => {
                  if (!from || !to) return ctx.toast(t('Pick both dates'))
                  save({ ...store, off: [...store.off, { from, to, why: why || t('Time off') }] })
                  setFrom('')
                  setTo('')
                  setWhy('')
                }}
              >
                {t('Add')}
              </button>
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}

/** An accepted job without times: the mockup's "Slot request" card, answered with real slots (POST /slots). */
function SlotRequest({ job, ctx }: { job: JobDetail; ctx: Ctx }) {
  const tech0 = bestTech(ctx.techs, job)
  const [techId, setTechId] = useState<string | null>(tech0?.tech_id ?? null)
  useEffect(() => {
    if (!techId && tech0) setTechId(tech0.tech_id)
  }, [tech0, techId])
  const tech = ctx.techs.find((x) => x.tech_id === techId) ?? null
  const [picked, setPicked] = useState<Slot[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const who = firstName(job.tenant?.name) || t('the tenant')
  const slots = freeSlots(tech)
  return (
    <section className="card mb-4 shadow-[0_0_0_1.5px_#6B1F33]">
      <CardTitle right={<span className="pill bg-wine-tint text-wine">{t('Please answer')}</span>} className="mb-1.5">
        {t('Slot request')}
      </CardTitle>
      <p className="mb-3 mt-0 text-secondary">
        {title(job)} · {job.postcode ?? ''} · {caseRef(job)}
      </p>
      {ctx.techs.length > 1 && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="text-muted">{t('Technician')}</span>
          <select
            className="rounded-[8px] bg-surface px-2.5 py-[7px] shadow-ring"
            value={techId ?? ''}
            onChange={(e) => {
              setTechId(e.target.value)
              setPicked([])
            }}
          >
            {ctx.techs.map((x) => (
              <option key={x.tech_id} value={x.tech_id}>
                {x.name}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {slots.length ? (
          slots.map((s) => (
            <CheckPill key={s.start} on={picked.some((x) => x.start === s.start)} onClick={() => setPicked(picked.some((x) => x.start === s.start) ? picked.filter((x) => x.start !== s.start) : picked.length >= 3 ? picked : [...picked, s])}>
              {fmtSlot(s)}
            </CheckPill>
          ))
        ) : (
          <span className="text-muted">{t('No free slots in the next days')}</span>
        )}
      </div>
      {err && <p className="mb-0 mt-3 text-red">{err}</p>}
      <div className="mt-3">
        <button
          className="btn-primary"
          disabled={busy || !picked.length}
          onClick={async () => {
            setBusy(true)
            setErr(null)
            try {
              ctx.put(await api.slots(ctx.pid, job.case_id, [...picked].sort((a, b) => a.start.localeCompare(b.start)), techId ?? undefined))
              ctx.toast(t('{n} times sent · {who} picks one on WhatsApp', { n: picked.length, who }))
            } catch (e) {
              setErr(e instanceof Error ? e.message : String(e))
            } finally {
              setBusy(false)
            }
          }}
        >
          {picked.length === 1 ? t('Send 1 slot') : t('Send {n} slots', { n: picked.length || '' })}
        </button>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- done & invoices

function DoneJobs({ ctx }: { ctx: Ctx }) {
  const waiting = ctx.all.filter((j) => j.status === 'completed')
  const sent = ctx.all.filter((j) => j.status === 'invoiced' || j.status === 'closed')
  const open = waiting.find((j) => j.case_id === ctx.invoiceOpen)
  const doneAt = (j: JobDetail) => {
    const c = (j.completion as { completed_at?: string } | null)?.completed_at
    return c ? new Date(c).toLocaleDateString(locale(), { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Europe/Berlin' }) : ''
  }
  return (
    <>
      <Head title={t('Done jobs & invoices')} sub={t('Finished jobs waiting for your invoice, and what we’ve paid.')} />
      <Card>
        <CardTitle className="mb-2">{t('Waiting for your invoice')}</CardTitle>
        {waiting.length ? (
          <div className="-mx-2 overflow-x-auto">
            <table className="t min-w-[560px]">
              <thead>
                <tr>
                  <th>{t('Job')}</th>
                  <th>{t('Done')}</th>
                  <th>{t('Address')}</th>
                  <th>{t('Technician')}</th>
                  <th className="text-right">{t('Cost cap')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {waiting.map((x) => (
                  <tr key={x.case_id}>
                    <td>
                      <b>{title(x)}</b>
                      <br />
                      <span className="text-muted">{caseRef(x)}</span>
                    </td>
                    <td>{doneAt(x)}</td>
                    <td>{x.address ?? x.postcode}</td>
                    <td>{x.technician?.name ?? ''}</td>
                    <td className="text-right tabular-nums">{eur2(costCap(x.estimated_cost_eur))}</td>
                    <td className="text-right">
                      <button className="btn-primary min-h-0 px-3 py-1.5 text-label" onClick={() => ctx.setInvoiceOpen(x.case_id)}>
                        {t('Submit invoice')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>{t('All caught up.')}</Empty>
        )}
        {open && <InvoicePanel job={open} pid={ctx.pid} put={ctx.put} toast={ctx.toast} onClose={() => ctx.setInvoiceOpen(null)} />}
      </Card>
      <Card className="mt-4">
        <CardTitle className="mb-2">{t('Invoiced & paid')}</CardTitle>
        {sent.length ? (
          <div className="-mx-2 overflow-x-auto">
            <table className="t min-w-[560px]">
              <thead>
                <tr>
                  <th>{t('Job')}</th>
                  <th>{t('Invoice')}</th>
                  <th>{t('Done')}</th>
                  <th className="text-right">{t('Total')}</th>
                  <th>{t('Status')}</th>
                </tr>
              </thead>
              <tbody>
                {sent.map((x) => {
                  const inv = invoiceOf(x)
                  return (
                    <tr key={x.case_id} className="click" onClick={() => ctx.nav(`/partner/${ctx.pid}/jobs/${x.case_id}`)}>
                      <td>
                        <b>{title(x)}</b>
                        <br />
                        <span className="text-muted">{caseRef(x)}</span>
                      </td>
                      <td>
                        {inv.doc ? (
                          <a href={inv.doc.url} target="_blank" rel="noreferrer" className="text-wine hover:underline" onClick={(e) => e.stopPropagation()}>
                            {inv.no || inv.doc.filename}
                          </a>
                        ) : (
                          '–'
                        )}
                      </td>
                      <td>{doneAt(x)}</td>
                      <td className="text-right tabular-nums">{eur2(inv.gross)}</td>
                      <td>
                        {x.status === 'closed' ? (
                          <span className="pill bg-ok-tint text-ok">{t('Approved · paid within 14 days')}</span>
                        ) : inv.check === 'flagged' ? (
                          <span className="pill bg-warn-tint text-warn">{t('In review by the property manager')}</span>
                        ) : (
                          <span className="pill bg-blue-tint text-blue">{t('Checking · tenant confirms the repair')}</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>{t('No invoices yet.')}</Empty>
        )}
      </Card>
    </>
  )
}

// ---------------------------------------------------------------- profile

/** Office staff phone numbers from data/seed.json (the API's staff list has names only). */
const STAFF_PHONE: Record<string, string> = { 'heizung-schmidt': '+490000000003' }
const OUR_TRADE_TO_KEY: Record<string, string> ={ heating: 'gas_boiler', plumbing: 'plumbing', electrical: 'water_heater_electric' }

/** Profile from the API manifest (+ technicians), overlaid with what was saved locally at registration. */
function profileFrom(p: PartnerProfile | null, techs: Technician[], local: Record<string, unknown> | null): Profile {
  const tr = (p?.transport ?? {}) as { type?: string; channel?: string; address?: string; notify?: { channel?: string; address?: string } }
  const pricing = (p?.pricing ?? {}) as { callout_fee_eur?: number; hourly_eur?: number }
  const sla = (p?.sla ?? {}) as { urgent_response_hours?: number; standard_response_hours?: number }
  const area = p?.service_area ?? {}
  const addr = tr.notify?.address ?? tr.address ?? ''
  const isMail = addr.includes('@')
  const base: Profile = {
    ...EMPTY_PROFILE,
    company_name: p?.name ?? '',
    contact_name: p?.staff?.[0]?.name ?? techs[0]?.name ?? '',
    email: isMail ? addr : '',
    mobile: !isMail ? addr : (STAFF_PHONE[p?.partner_id ?? ''] ?? ''),
    trades: [...new Set((p?.capabilities?.trades ?? []).map((x) => OUR_TRADE_TO_KEY[x]).filter(Boolean))],
    brands: p?.capabilities?.brands_certified ?? [],
    base_postcode: area.base_postcode ?? '',
    radius_km: area.radius_km != null ? String(area.radius_km) : '',
    postcodes: (area.postcodes ?? []).join(', '),
    callout_eur: pricing.callout_fee_eur != null ? String(pricing.callout_fee_eur) : '',
    hourly_eur: pricing.hourly_eur != null ? String(pricing.hourly_eur) : '',
    response: sla.urgent_response_hours != null ? (sla.urgent_response_hours <= 8 ? 'Same day' : 'Within 24 hours') : '',
    jobs_via: tr.type === 'portal' ? (tr.notify?.channel === 'whatsapp' ? 'WhatsApp' : tr.notify?.channel === 'email' ? 'Email' : 'Portal only') : tr.channel === 'whatsapp' ? 'WhatsApp' : 'Email',
    team: techs.length ? techs.map((x) => ({ name: x.name, phone: x.phone_e164 ?? '', qual: x.skills.join(', ') })) : [{ name: '', phone: '', qual: '' }],
  }
  return local ? ({ ...base, ...local } as Profile) : base
}

function ProfileView({ ctx, local }: { ctx: Ctx; local: Record<string, unknown> | null }) {
  const nav = useNavigate()
  const initial = useMemo(() => profileFrom(ctx.partner, ctx.techs, local), [ctx.partner, ctx.techs, local])
  const [p, setP] = useState<Profile>(initial)
  useEffect(() => setP(initial), [initial])
  const set = (patch: Partial<Profile>) => setP((x) => ({ ...x, ...patch }) as Profile)
  const blocks = STEPS.map((s) => ({ ...s, fields: s.fields.filter((f) => (!f.custom || ['trades', 'brands', 'team'].includes(f.custom)) && !(f.sec && /^(Documents|Agreements)$/.test(f.sec))) }))
  const done = ctx.all.filter(isDone).length
  return (
    <>
      <Head
        title={t('Profile')}
        sub={t('Everything Debye knows about your business. Changes to licences are checked before they go live.')}
        right={
          <button
            className="btn-primary"
            onClick={() => {
              saveLocalProfile(ctx.pid, p as unknown as Record<string, unknown>)
              ctx.toast(t('Saved in this browser (demo)'))
            }}
          >
            {t('Save changes')}
          </button>
        }
      />
      <div className="grid grid-cols-1 items-start gap-[18px] xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0">
          {blocks.map((s) => (
            <Card key={s.t} className="[&+&]:mt-4">
              <CardTitle className="mb-3.5">{t(s.t)}</CardTitle>
              <div className="grid grid-cols-1 gap-x-[18px] gap-y-4 sm:grid-cols-2">
                {s.fields.map((f, i) => (
                  <ProfileField key={f.k ?? f.sec ?? f.custom ?? i} f={f} p={p} set={set} errors={[]} first={i === 0} />
                ))}
              </div>
            </Card>
          ))}
        </div>
        <div className="min-w-0 xl:sticky xl:top-[78px]">
          <Card>
            <CardTitle className="mb-3.5">{t('Verification')}</CardTitle>
            <table className="t">
              <tbody>
                <VRow l={t('Connector spec')} pill={<span className="pill bg-ok-tint text-ok">{t('Valid')}</span>} />
                <VRow l={t('VAT ID')} pill={p.vat_id ? <span className="pill bg-ok-tint text-ok">{t('Given')}</span> : <span className="pill">{t('Not given')}</span>} />
                <VRow l={t('Gas installer registration')} pill={p.gas_valid ? <span className="pill bg-ok-tint text-ok">{t('Until {d}', { d: String(p.gas_valid) })}</span> : <span className="pill">–</span>} />
                <VRow l={t('Liability insurance')} pill={p.ins_valid ? <span className="pill bg-ok-tint text-ok">{t('Until {d}', { d: String(p.ins_valid) })}</span> : <span className="pill">–</span>} />
              </tbody>
            </table>
            <p className="mb-0 mt-3 text-muted">{t('We remind you 30 days before anything expires.')}</p>
          </Card>
          <Card className="mt-4">
            <CardTitle className="mb-3.5">{t('Your record with us')}</CardTitle>
            <table className="t">
              <tbody>
                <VRow l={t('Jobs done for Debye')} pill={<b>{done}</b>} />
                <VRow l={t('Average rating')} pill={<b>{ctx.partner?.rating ?? '–'}</b>} />
                <VRow l={t('Open jobs')} pill={<b>{ctx.all.length - done}</b>} />
              </tbody>
            </table>
          </Card>
          <button
            className="btn-secondary mt-4"
            onClick={() => {
              setSession(null)
              nav('/partner')
            }}
          >
            {t('Log out')}
          </button>
        </div>
      </div>
    </>
  )
}
function VRow({ l, pill }: { l: string; pill: ReactNode }) {
  return (
    <tr>
      <td>{l}</td>
      <td className="text-right">{pill}</td>
    </tr>
  )
}

// ---------------------------------------------------------------- one job

function OneJob({ ctx, caseId }: { ctx: Ctx; caseId: string }) {
  const job = ctx.all.find((j) => j.case_id === caseId)
  const [inv, setInv] = useState(false)
  if (!job) return ctx.loading ? <Loading what={t('Loading job')} /> : <Card><Empty>{t('This job is not (or no longer) assigned to you.')}</Empty></Card>
  if (isNew(job)) return <NewJobCard job={job} pid={ctx.pid} techs={ctx.techs} put={ctx.put} toast={ctx.toast} />
  if (isWip(job)) return <WipCard job={job} pid={ctx.pid} techs={ctx.techs} put={ctx.put} toast={ctx.toast} onCompleted={() => setInv(true)} />
  // done / declined: summary card in the same style
  const i = invoiceOf(job)
  return (
    <Card>
      <CardTitle right={<span className={`pill ${job.status === 'closed' ? 'bg-ok-tint text-ok' : job.status.includes('declined') ? '' : 'bg-blue-tint text-blue'}`}>{job.status === 'closed' ? t('Closed') : job.status === 'invoiced' ? t('Invoice sent') : job.status === 'completed' ? t('Completed') : t('Declined')}</span>}>
        {title(job)}
      </CardTitle>
      <p className="mt-0 text-muted">
        {caseRef(job)} · {job.address ?? job.postcode}
        {job.technician ? ` · ${job.technician.name}` : ''}
      </p>
      {job.status.includes('declined') && <p className="text-secondary">{t('You declined this job. Debye passed it to the next partner.')}</p>}
      {(job.completion as { notes?: string } | null)?.notes && (
        <p className="text-secondary">
          <b className="text-ink">{t('Work done')}:</b> {(job.completion as { notes?: string }).notes}
        </p>
      )}
      {i.doc && <InvoiceRead job={job} />}
      {job.status === 'completed' && !inv && (
        <button className="btn-primary mt-3" onClick={() => setInv(true)}>
          {t('Submit invoice')}
        </button>
      )}
      {job.status === 'completed' && inv && <InvoicePanel job={job} pid={ctx.pid} put={ctx.put} toast={ctx.toast} onClose={() => setInv(false)} />}
      {job.photos?.filter((ph) => ph.filename.startsWith('after')).map((ph) => (
        <img key={ph.document_id} src={ph.url} alt={ph.filename} className="mt-3 h-24 w-24 rounded object-cover" />
      ))}
    </Card>
  )
}
