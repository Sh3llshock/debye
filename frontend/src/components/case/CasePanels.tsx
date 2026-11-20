import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { CaseDetail, CaseEvent, Consent, DocumentItem, RankingEntry, ThreadMessage, UnitDetail } from '../../api/types'
import { actorColors } from '../../theme'
import { fmtDateTime, fmtEur, fmtSlot, fmtTime, humanize, LIFECYCLE, lifecycleDone } from '../../lib/format'
import { eventKey, messageKey } from '../../lib/keys'
import { useNewKeys } from '../../lib/useNewKeys'
import { ActorIcon, Card, Empty, Field, JsonView, StatusPill } from '../ui'
import { Icon } from '../icons'

// ---------- small bits ----------
export function LivePill({ label = 'Live' }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-pill bg-success-soft px-3 py-0.5 text-sm font-semibold text-success">
      <span className="animate-pulse-dot h-2 w-2 rounded-full bg-success" />
      {label}
    </span>
  )
}

export function Chip({ children, tone = 'neutral', mono }: { children: ReactNode; tone?: 'neutral' | 'bad' | 'violet'; mono?: boolean }) {
  const cls = tone === 'bad' ? 'bg-danger-soft text-danger' : tone === 'violet' ? 'bg-violet-soft text-violet' : 'bg-surface-alt text-plum-80'
  return <span className={`inline-flex items-center rounded-pill px-3 py-1 text-sm ${mono ? 'font-mono' : ''} ${cls}`}>{children}</span>
}

const NEGATIVE = /\b(not|no|booked|declined|outside|expensive)\b/i

// ---------- unit card ----------
export function UnitCard({ u, unitId }: { u: UnitDetail | null; unitId: string }) {
  const label = unitId.replace('unit_', '')
  if (!u)
    return (
      <Card title={`Unit ${label}`}>
        <div className="text-muted">Loading…</div>
      </Card>
    )
  const p = u.property
  const [street, city] = (p?.address ?? '').split(',').map((x) => x.trim())
  const energy = p?.energy_class ?? p?.energy_certificate?.class
  const energyUntil = p?.energy_valid_until ?? p?.energy_certificate?.valid_until
  const boiler = u.assets.find((a) => a.type?.includes('boiler')) ?? u.assets[0]
  const facts = [u.unit.floor != null ? `Floor ${u.unit.floor}` : null, u.unit.size_sqm ? `${u.unit.size_sqm} m²` : null, u.unit.rooms ? `${u.unit.rooms} rooms` : null]
    .filter(Boolean)
    .join(' · ')
  return (
    <Card title={`Unit ${label}`} action={facts && <Chip>{facts}</Chip>}>
      <div className="text-lg leading-snug">
        {street}
        {city && <div>{city}</div>}
      </div>
      <div className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4">
        <Field label="Built">{p?.building_year ?? '—'}</Field>
        <Field label="Heating">{p?.heating_type ? humanize(p.heating_type.replace('gas central heating', 'gas, central')) : '—'}</Field>
        <Field label="Energy class">
          {energy ? (
            <span className="flex items-center gap-2">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-sm bg-warning-soft font-semibold text-warning">{energy}</span>
              {energyUntil && <span className="text-muted">until {energyUntil.slice(0, 4)}</span>}
            </span>
          ) : (
            '—'
          )}
        </Field>
        <Field label="Tenant">{u.tenant?.name ?? '—'}</Field>
      </div>
      {boiler && (
        <div className="mt-4">
          <Field label="Boiler">
            {boiler.make} {boiler.model}
          </Field>
          <div className="mt-1 text-sm text-muted">
            {boiler.installed && `Installed ${boiler.installed.slice(0, 4)}`}
            {boiler.last_service && ` · last service ${new Date(boiler.last_service).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })}`}
          </div>
        </div>
      )}
    </Card>
  )
}

// ---------- case card ----------
export function PriorityBadge({ priority }: { priority: string }) {
  if (priority === 'urgent')
    return (
      <span className="inline-flex items-center gap-2 rounded-pill bg-danger px-3 py-0.5 text-sm font-semibold text-on-plum">
        <span className="h-2 w-2 rounded-full bg-surface" />
        Urgent
      </span>
    )
  const tone = priority === 'high' ? 'bg-warning-soft text-warning' : 'bg-plum-soft text-plum-80'
  return <span className={`inline-flex items-center rounded-pill px-3 py-0.5 text-sm font-semibold ${tone}`}>{humanize(priority)}</span>
}

export function CaseCard({ c }: { c: CaseDetail }) {
  const done = lifecycleDone(c.status)
  const approved = c.approval && !c.approval.required
  return (
    <Card title="Case" action={<StatusPill status={c.status} />}>
      <div className="flex gap-1.5">
        {LIFECYCLE.map((s, i) => (
          <span key={s} className={`h-1.5 flex-1 rounded-full transition-colors duration-700 ${i < done ? 'bg-plum' : 'bg-line'}`} />
        ))}
      </div>
      <div className="mt-2 hidden text-xs text-muted 2xl:block">{LIFECYCLE.join(' → ')}</div>
      <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
        <Field label="Priority">
          <span className="flex items-center gap-3">
            <PriorityBadge priority={c.priority} />
            <span className="hidden text-muted 2xl:inline">{humanize(c.type.split('.').pop())}</span>
          </span>
        </Field>
        <Field label="Cost bearer">{humanize(c.cost_bearer)}</Field>
        <Field label="Partner">{c.partner?.name ?? <span className="text-muted">not assigned yet</span>}</Field>
        <Field label="Visit">
          {c.slot ? fmtSlot(c.slot) : c.proposed_slots?.length ? <span className="text-muted">{c.proposed_slots.length} slots proposed</span> : <span className="text-muted">not scheduled</span>}
        </Field>
        <div className="col-span-2">
        <Field label="Approval">
          {c.approval?.required ? (
            <span className="font-semibold text-warning">Waiting for you · {fmtEur(c.estimated_cost_eur)} est.</span>
          ) : approved && c.approval?.rule !== 'not evaluated yet' ? (
            <span className="flex items-start gap-2 text-success">
              <Icon name="check" className="mt-1 h-5 w-5 shrink-0" />
              <span>
                {c.estimated_cost_eur != null && `${fmtEur(c.estimated_cost_eur)} est. · `}
                {c.approval?.rule ?? 'approved'}
              </span>
            </span>
          ) : (
            <span className="text-muted">not evaluated yet</span>
          )}
        </Field>
        </div>
      </div>
    </Card>
  )
}

// ---------- zero forms ----------
export function zeroForms(c: CaseDetail) {
  const zf = c.zero_forms
  if (!zf) return null
  const inputs = zf.tenant_inputs.map((t) => t.toLowerCase())
  const taps = inputs.filter((t) => t.startsWith('tap')).length
  const voice = inputs.filter((t) => t.includes('voice')).length
  const photos = inputs.filter((t) => !t.startsWith('tap') && t.includes('photo')).length
  const texts = inputs.length - taps - voice - photos
  const parts = [
    voice && `${voice} voice note${voice > 1 ? 's' : ''}`,
    photos && `${photos} photo${photos > 1 ? 's' : ''}`,
    texts > 0 && `${texts} message${texts > 1 ? 's' : ''}`,
    taps && `${taps} tap${taps > 1 ? 's' : ''}`,
  ].filter(Boolean) as string[]
  return { prefilled: zf.prefilled.length, inputs: parts.join(' · ') || 'nothing yet' }
}

export function ZeroFormsCard({ c }: { c: CaseDetail }) {
  const z = zeroForms(c)
  if (!z) return null
  const name = c.reporters[0]?.name.split(' ')[0] ?? 'The resident'
  return (
    <section className="rounded-card bg-plum p-card-sm text-on-plum shadow-card" title={c.zero_forms?.prefilled.join(', ')}>
      <div className="text-eyebrow font-semibold uppercase text-on-plum-muted">Zero forms</div>
      <div className="mt-2 flex items-end gap-4">
        <span className="font-sans text-stat font-medium">{z.prefilled}</span>
        <span className="pb-1 text-body-sm leading-tight">
          fields pre-filled
          <br />
          from centrix
        </span>
      </div>
      <div className="mt-3 border-t border-line-on-plum pt-3 text-lg font-medium">{z.inputs}</div>
      <p className="mt-1 text-sm text-on-plum-muted">That is all {name} did. No address, name, phone or boiler model was asked.</p>
    </section>
  )
}

// ---------- approval ----------
export function ApprovalCard({ c, onApprove }: { c: CaseDetail; onApprove: () => Promise<void> }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const needs = c.approval?.required || c.status === 'awaiting_approval'
  if (!needs) return null
  const amount = c.approval?.amount_eur ?? c.estimated_cost_eur
  return (
    <Card tone="inverse" className="animate-rise">
      <div className="text-eyebrow font-semibold uppercase text-lilac">Needs your approval</div>
      <div className="mt-2 font-serif text-2xl font-semibold">Approve {fmtEur(amount)} repair?</div>
      <div className="mt-2 text-body-sm text-on-plum-muted">
        {c.partner ? `${c.partner.name}. ` : ''}
        {c.approval?.rule ?? 'Estimate is above the auto-approval limit, so Debye paused and asked you.'}
      </div>
      <button
        className="btn-inverse mt-5 w-full"
        disabled={busy}
        onClick={async () => {
          setBusy(true)
          setErr(null)
          try {
            await onApprove()
          } catch (e) {
            setErr(e instanceof Error ? e.message : String(e))
          } finally {
            setBusy(false)
          }
        }}
      >
        {busy ? (
          'Approving…'
        ) : (
          <>
            Approve {fmtEur(amount)} <Icon name="arrow" className="h-5 w-5" />
          </>
        )}
      </button>
      {err && <div className="mt-2 rounded bg-danger-soft p-2 text-danger">{err}</div>}
    </Card>
  )
}

// ---------- timeline ----------
export function actorName(c: CaseDetail, e: CaseEvent) {
  const d = (e.data ?? {}) as Record<string, unknown>
  switch (e.actor) {
    case 'debye':
      return 'Debye'
    case 'tenant':
      return (d.contact_name as string) ?? c.reporters[0]?.name ?? 'Resident'
    case 'partner':
      return c.partner?.name.replace(/ GmbH$/, '') ?? 'Partner'
    case 'staff':
    case 'pm':
      return 'Property manager'
    default:
      return 'System'
  }
}

export function Timeline({ c }: { c: CaseDetail }) {
  const shown = c.events.filter((e) => !e.kind.startsWith('message.'))
  const isNew = useNewKeys(shown.map(eventKey), 6000)
  const list = useRef<HTMLOListElement>(null)
  useEffect(() => {
    // scroll only the list, never the page (the page must stay put on the projector)
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: 'smooth' })
  }, [shown.length])
  return (
    <Card title="Live timeline" action={<LivePill />}>
      {shown.length === 0 ? (
        <div className="flex h-[calc(100vh-350px)] min-h-[380px] items-center justify-center rounded-lg border border-dashed border-line text-center text-muted">Waiting for the first WhatsApp message…</div>
      ) : (
        <ol ref={list} className="-mx-3 flex h-[calc(100vh-350px)] min-h-[380px] flex-col gap-1 overflow-y-auto px-1">
          {shown.map((e) => {
            const fresh = isNew(eventKey(e))
            const color = (actorColors[e.actor] ?? actorColors.system).bg
            return (
              <li key={eventKey(e)} className={`flex gap-4 rounded-lg px-3 py-3 ${fresh ? 'animate-enter bg-violet-soft' : ''}`}>
                <ActorIcon actor={e.actor} size={44} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-3">
                    <span className={`text-sm font-semibold ${e.actor === 'system' ? 'text-ink' : ''}`} style={e.actor === 'system' ? undefined : { color }}>
                      {actorName(c, e)}
                    </span>
                    <span className="font-mono text-sm text-muted">{fmtTime(e.ts)}</span>
                    {fresh && (
                      <span className="inline-flex items-center gap-1 text-sm font-semibold text-violet">
                        <span className="h-2 w-2 rounded-full bg-violet" /> New
                      </span>
                    )}
                  </div>
                  <div className="text-body-sm leading-snug">{e.summary}</div>
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </Card>
  )
}

// ---------- WhatsApp thread ----------
function Waveform() {
  const bars = [6, 12, 8, 16, 10, 18, 7, 14, 9, 15, 6, 11, 8]
  return (
    <span className="flex items-center gap-[3px]">
      {bars.map((h, i) => (
        <span key={i} className="w-[3px] rounded-full bg-wa-meta" style={{ height: h }} />
      ))}
    </span>
  )
}

function MessageMedia({ m, docs }: { m: ThreadMessage; docs: DocumentItem[] }) {
  return (
    <>
      {m.media.map((x, i) => {
        const doc = x.document_id ? docs.find((d) => d.document_id === x.document_id) : undefined
        const mime = doc?.mime ?? ''
        const kind = x.kind ?? (mime.startsWith('audio') ? 'audio' : mime.startsWith('image') ? 'photo' : doc?.kind ?? 'file')
        const url = x.url ?? doc?.url
        if (kind === 'audio')
          return (
            <div key={i} className="mb-1 flex items-center gap-2 text-wa-header">
              <Icon name="mic" className="h-5 w-5" />
              <Waveform />
            </div>
          )
        if ((kind === 'photo' || kind === 'image') && !url) return <div key={i} className="mb-1 flex items-center gap-2 text-sm text-wa-meta"><Icon name="camera" className="h-5 w-5" /> Photo</div>
        if ((kind === 'photo' || kind === 'image') && url) return <img key={i} src={url} alt={doc?.filename ?? 'photo'} className="mb-1 max-h-48 w-full rounded object-cover" />
        return (
          <div key={i} className="mb-1 flex items-center gap-2 text-sm">
            <Icon name="file" className="h-5 w-5" /> {doc?.filename ?? 'Document'}
          </div>
        )
      })}
    </>
  )
}

/** The agent logs interactive messages as "Text [Option A] · [Option B]" or "Text [A | B | C]". Split those into buttons. */
export function splitButtons(text: string): { body: string; buttons: string[] } {
  const m = text.match(/^(.*?)\s*((?:\[[^\]]+\]\s*(?:·\s*)?)+)$/s)
  if (!m) return { body: text, buttons: [] }
  const buttons = [...m[2].matchAll(/\[([^\]]+)\]/g)].flatMap((x) => x[1].split('|').map((b) => b.trim())).filter(Boolean)
  return { body: m[1].trim(), buttons }
}

export function WhatsAppThread({ c }: { c: CaseDetail }) {
  const messages = c.messages
  const isNew = useNewKeys(messages.map(messageKey))
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length])
  const who = c.reporters[0]?.name.split(' ')[0] ?? 'Resident'
  return (
    <Card title="WhatsApp" action={<span className="rounded-pill bg-success-soft px-3 py-0.5 text-sm font-semibold text-wa-header">{who} ↔ Debye</span>}>
      <div ref={box} className="flex h-[calc(100vh-350px)] min-h-[380px] flex-col gap-2 overflow-y-auto rounded-lg bg-wa-bg p-3">
        {messages.length === 0 && <div className="m-auto p-4 text-center text-muted">No messages yet</div>}
        {messages.map((m) => {
          const out = m.direction === 'out'
          const voice = m.media?.some((x) => x.kind === 'audio' || docs(c, x.document_id)?.mime?.startsWith('audio'))
          return (
            <div
              key={messageKey(m)}
              className={`max-w-[85%] rounded-lg px-3 py-2 shadow-card ${out ? 'self-end bg-wa-out' : 'self-start bg-wa-in'} ${isNew(messageKey(m)) ? 'animate-enter' : ''}`}
            >
              {!out && c.reporters.length > 1 && m.contact && <div className="text-xs font-semibold text-wa-header">{m.contact}</div>}
              {m.media?.length > 0 && <MessageMedia m={m} docs={c.documents} />}
              {m.text &&
                (() => {
                  const { body, buttons } = out ? splitButtons(m.text) : { body: m.text, buttons: [] as string[] }
                  return (
                    <>
                      {body && <div className={`text-body-sm leading-snug ${voice ? 'italic' : ''}`}>{body}</div>}
                      {buttons.length > 0 && (
                        <div className="mt-2 flex flex-col gap-1.5">
                          {buttons.map((b) => (
                            <span key={b} className="rounded border border-line bg-wa-in px-3 py-1.5 text-center text-sm font-medium text-wa-header">
                              {b}
                            </span>
                          ))}
                        </div>
                      )}
                    </>
                  )
                })()}
              <div className="text-right text-xs text-wa-meta">
                {fmtTime(m.ts)}
                {out && <span className="ml-1 text-wa-tick">✓✓</span>}
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}
const docs = (c: CaseDetail, id?: string) => (id ? c.documents.find((d) => d.document_id === id) : undefined)

// ---------- ranking ----------
export function Ranking({ ranking, chosen }: { ranking: RankingEntry[]; chosen?: string | null }) {
  return (
    <Card title="Why this partner" action={ranking.length > 0 && <Chip>{ranking.length} eligible</Chip>}>
      {ranking.length === 0 ? (
        <Empty>Ranking appears once Debye has triaged the case</Empty>
      ) : (
        <ol className="flex flex-col gap-4">
          {ranking.map((r, i) => {
            const win = chosen ? r.partner_id === chosen : i === 0
            return (
              <li key={r.partner_id} className={`rounded-card p-4 ${win ? 'border-2 border-plum' : 'border border-line'}`}>
                <div className="flex items-center gap-3">
                  <span className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${win ? 'bg-plum text-on-plum' : 'bg-surface-alt text-plum-80'}`}>{i + 1}</span>
                  <span className="min-w-0 flex-1 text-lg font-semibold leading-tight">{r.name}</span>
                  <span className="font-mono text-lg">{r.score.toFixed(2)}</span>
                </div>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-line">
                  <div className={`h-full rounded-full transition-all duration-700 ${win ? 'bg-plum' : 'bg-plum-60'}`} style={{ width: `${Math.round(r.score * 100)}%` }} />
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {r.reasons.map((x) => (
                    <Chip key={x} tone={NEGATIVE.test(x) ? 'bad' : 'neutral'}>
                      {x}
                    </Chip>
                  ))}
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </Card>
  )
}

// ---------- consent ----------
export function ConsentRecord({ c, partnerName }: { c: CaseDetail; partnerName: (id: string) => string }) {
  const [json, setJson] = useState(false)
  const consents: Consent[] = c.consents
  const contactName = (k: Consent) => c.reporters.find((r) => r.contact_id === k.contact_id)?.name ?? c.reporters[0]?.name ?? 'Resident'
  return (
    <Card title="Consent record" action={<Icon name="shield" className={`h-7 w-7 ${consents.length ? 'text-success' : 'text-muted'}`} />}>
      {consents.length === 0 ? (
        <Empty>Nothing shared yet. No data leaves centrix without the resident's tap.</Empty>
      ) : (
        <div className="flex flex-col gap-6">
          {consents.map((k) => (
            <div key={(k.consent_id ?? k.partner_id) + k.given_at} className="flex flex-col gap-4">
              <div className="text-lg font-semibold leading-snug">
                {contactName(k)} → {partnerName(k.partner_id)}
              </div>
              <Field label="Data shared">
                <div className="mt-1 flex flex-wrap gap-2">
                  {k.data_shared.map((f) => (
                    <Chip key={f} mono>
                      {f}
                    </Chip>
                  ))}
                </div>
              </Field>
              <Field label="Given">{fmtDateTime(k.given_at)}</Field>
              <Field label="Channel">{k.channel === 'whatsapp' ? 'WhatsApp · button "Ja, teilen"' : humanize(k.channel)}</Field>
              <Field label="Purpose">{humanize(k.purpose)}</Field>
              {k.revoked_at && <div className="font-semibold text-danger">Revoked {fmtDateTime(k.revoked_at)}</div>}
              <div className="text-sm text-muted">Not shared: rent, lease, other tenants</div>
              <button className="self-start text-sm font-semibold text-link" onClick={() => setJson(!json)}>
                {json ? 'Hide' : 'Show'} JSON
              </button>
              {json && <JsonView value={{ data_shared: k.data_shared, given_at: k.given_at, channel: k.channel }} />}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

// ---------- documents ----------
export function priceCheckOk(pc: unknown): boolean {
  if (!pc) return false
  if (typeof pc === 'string') return pc.toLowerCase().startsWith('ok')
  if (typeof pc === 'object') {
    const o = pc as Record<string, unknown>
    return o.ok === true || o.status === 'ok' || o.result === 'ok'
  }
  return false
}

/** Normalises backend price_check ({result: ok|flagged|no_framework, flags: [...]}) and older string forms. */
export function priceCheckInfo(pc: unknown): { status: 'ok' | 'flagged' | 'none' | 'unknown'; flags: string[] } {
  if (!pc) return { status: 'unknown', flags: [] }
  if (typeof pc === 'string') return { status: pc.toLowerCase().startsWith('ok') ? 'ok' : 'flagged', flags: [] }
  if (typeof pc === 'object') {
    const o = pc as Record<string, unknown>
    const flags = Array.isArray(o.flags) ? (o.flags as unknown[]).map(String) : []
    const r = String(o.result ?? o.status ?? (o.ok === true ? 'ok' : ''))
    if (r === 'ok') return { status: 'ok', flags }
    if (r === 'flagged') return { status: 'flagged', flags }
    if (r === 'no_framework') return { status: 'none', flags }
  }
  return { status: 'unknown', flags: [] }
}

export function PriceCheck({ pc, compact }: { pc: unknown; compact?: boolean }) {
  const { status, flags } = priceCheckInfo(pc)
  if (status === 'unknown') return null
  const label = status === 'ok' ? 'Price check ok' : status === 'flagged' ? `Price check flagged · ${flags.length} line${flags.length === 1 ? '' : 's'}` : 'No framework prices'
  const cls = status === 'ok' ? 'bg-success-soft text-success' : status === 'flagged' ? 'bg-warning-soft text-warning' : 'bg-surface-alt text-muted'
  return (
    <div className="mt-3">
      <span className={`inline-flex items-center gap-2 rounded-pill px-3 py-0.5 text-sm font-semibold ${cls}`}>
        {status === 'ok' && <Icon name="check" className="h-4 w-4" />}
        {label}
      </span>
      {!compact && status !== 'ok' && flags.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-sm text-warning">
          {flags.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function docSubtitle(d: DocumentItem, pc: unknown) {
  const x = (d.extracted ?? {}) as Record<string, unknown>
  if (d.kind === 'invoice') {
    const gross = typeof x.gross_eur === 'number' ? fmtEur(x.gross_eur as number, true) : null
    const st = priceCheckInfo(x.price_check ?? pc).status
    return ['Invoice', gross, st === 'ok' ? 'price check ok' : st === 'flagged' ? 'price check flagged' : null].filter(Boolean).join(' · ')
  }
  const date = d.created_at ? new Date(d.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''
  if (d.kind === 'photo') return ['Photo', date].filter(Boolean).join(' · ')
  if (d.kind === 'report') return 'Service report'
  if (d.kind === 'voice_note') return ['Voice note', date].filter(Boolean).join(' · ')
  return [humanize(d.kind), date].filter(Boolean).join(' · ')
}

export function InvoiceFields({ x }: { x: Record<string, unknown> }) {
  const items = Array.isArray(x.line_items) ? (x.line_items as { desc: string; qty: number; unit_price: number }[]) : []
  const num = (k: string) => (typeof x[k] === 'number' ? fmtEur(x[k] as number, true) : '—')
  return (
    <div className="mt-3 rounded-lg bg-surface-alt p-4">
      <div className="grid grid-cols-3 gap-2">
        <Field label="Net">{num('net_eur')}</Field>
        <Field label="VAT">{num('vat_eur')}</Field>
        <Field label="Gross">
          <span className="font-semibold">{num('gross_eur')}</span>
        </Field>
      </div>
      {items.length > 0 && (
        <table className="mt-3 w-full text-sm">
          <tbody>
            {items.map((l, i) => (
              <tr key={i} className="border-t border-line">
                <td className="py-1 pr-2">{l.desc}</td>
                <td className="py-1 text-right text-muted">{l.qty}×</td>
                <td className="py-1 text-right font-mono">{fmtEur(l.unit_price, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <PriceCheck pc={x.price_check} />
    </div>
  )
}

export function Documents({ docs, title, priceCheck }: { docs: DocumentItem[]; title: string; priceCheck?: unknown }) {
  const isNew = useNewKeys(
    docs.map((d) => d.document_id),
    8000,
  )
  const [open, setOpen] = useState<string | null>(null)
  return (
    <Card title={title}>
      {docs.length === 0 ? (
        <Empty>No documents yet</Empty>
      ) : (
        <ul className="flex flex-col gap-2">
          {docs.map((d) => {
            const fresh = isNew(d.document_id)
            const hasFields = d.kind === 'invoice' && !!d.extracted && Object.keys(d.extracted).length > 0
            const st = d.kind === 'invoice' ? priceCheckInfo((d.extracted as Record<string, unknown> | null)?.price_check ?? priceCheck).status : 'unknown'
            return (
              <li key={d.document_id} className={`rounded-lg p-3 ${fresh ? 'animate-enter bg-violet-soft' : ''}`}>
                <div className="flex items-center gap-4">
                  <span className={`inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-lg ${d.kind === 'invoice' ? 'bg-plum text-on-plum' : 'bg-surface-alt text-plum-80'}`}>
                    <Icon name={d.kind === 'photo' ? 'camera' : d.kind === 'voice_note' || d.mime?.startsWith('audio') ? 'mic' : 'file'} className="h-6 w-6" />
                  </span>
                  <a href={d.url} target="_blank" rel="noreferrer" className="min-w-0 flex-1">
                    <div className="truncate text-body-sm font-semibold">{d.filename}</div>
                    <div className={`truncate text-sm ${st === 'ok' ? 'text-success' : st === 'flagged' ? 'text-warning' : 'text-muted'}`}>{docSubtitle(d, priceCheck)}</div>
                  </a>
                  {fresh && (
                    <span className="inline-flex items-center gap-1 text-sm font-semibold text-violet">
                      <span className="h-2 w-2 rounded-full bg-violet" /> New
                    </span>
                  )}
                  {hasFields && (
                    <button className="text-sm font-semibold text-link" onClick={() => setOpen(open === d.document_id ? null : d.document_id)}>
                      {open === d.document_id ? 'Hide' : 'Fields'}
                    </button>
                  )}
                </div>
                {hasFields && open === d.document_id && <InvoiceFields x={d.extracted!} />}
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

// ---------- result ----------
export function ResultPayload({ result }: { result: Record<string, unknown> | null }) {
  if (!result) return null
  return (
    <Card title="Written back to centrix" action={<span className="rounded-pill bg-success-soft px-3 py-0.5 text-sm font-semibold text-success">Case closed</span>} className="animate-enter">
      <JsonView value={result} />
    </Card>
  )
}
