import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { CaseDetail, CaseEvent, DocumentItem, RankingEntry, ThreadMessage, UnitDetail } from '../../api/types'
import { errorText, explainCodes } from '../../lib/errors'
import { fmtDateTime, fmtEur, fmtSlot, fmtTime, humanize } from '../../lib/format'
import { eventKey, messageKey } from '../../lib/keys'
import { STATUS_TEXT, type LineState } from '../../lib/lifecycle'
import { useNewKeys } from '../../lib/useNewKeys'
import { Icon } from '../icons'
import { ActorIcon, Empty, JsonView, Mascot, Panel, Prop } from '../ui'

// ---------- service line (the signature move) ----------
function shortTs(iso?: string) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.toLocaleDateString('en-GB', { weekday: 'short', timeZone: 'Europe/Berlin' })} ${fmtTime(iso)}`
}

/** Full service line with a label and timestamp under each station. `waiting` is shown under the next station. */
export function ServiceLine({ line, waiting }: { line: LineState; waiting?: string | null }) {
  const n = line.stations.length
  return (
    <ol className="grid" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
      {line.stations.map((s, i) => {
        const current = i === line.reached - 1
        const next = i === line.reached
        const trackDone = i < line.reached - 1
        return (
          <li key={s.label} className="relative pr-2">
            <div className="relative flex h-[18px] items-center">
              {i < n - 1 && <span className={`absolute left-[6px] right-0 top-1/2 h-[3px] -translate-y-1/2 transition-colors duration-700 ${trackDone ? 'bg-life-done' : 'bg-life-track'}`} />}
              {current ? (
                <span key={`cur-${line.reached}`} className="animate-station relative z-10 -ml-[3px] h-[18px] w-[18px] rounded-full border-[3px] border-surface bg-life-current ring-1 ring-life-current" />
              ) : (
                <span className={`relative z-10 h-3 w-3 rounded-full ${s.reached ? 'bg-life-done' : 'border-2 border-life-upcoming bg-surface'}`} />
              )}
            </div>
            <div className={`mt-2 text-label ${s.reached ? 'font-medium text-ink' : 'text-muted'}`}>{s.label}</div>
            <div className="text-meta text-muted">{s.reached ? shortTs(s.ts) : next && waiting ? waiting : ''}</div>
          </li>
        )
      })}
    </ol>
  )
}

/** Compact service line for table rows: dots only, plus the status in words. */
export function MiniLine({ total, reached, status }: { total: number; reached: number; status: string }) {
  return (
    <div>
      <div className="flex items-center">
        {Array.from({ length: total }).map((_, i) => {
          const current = i === reached - 1
          return (
            <span key={i} className="flex items-center">
              {i > 0 && <span className={`h-[2px] w-[18px] ${i < reached ? 'bg-life-done' : 'bg-life-track'}`} />}
              <span className={`h-2.5 w-2.5 rounded-full ${current ? 'bg-life-current' : i < reached ? 'bg-life-done' : 'border-[1.5px] border-life-upcoming bg-surface'}`} />
            </span>
          )
        })}
      </div>
      <div className="mt-1 text-meta text-secondary">{STATUS_TEXT[status] ?? humanize(status)}</div>
    </div>
  )
}

// ---------- zero forms (our strongest pitch number) ----------
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
  return { prefilled: zf.prefilled.length, inputs: parts.join(', ') || 'nothing yet' }
}

export function ZeroFormsStrip({ c }: { c: CaseDetail }) {
  const z = zeroForms(c)
  if (!z) return null
  const name = c.reporters[0]?.name.split(' ')[0] ?? 'the resident'
  return (
    <div
      className="relative grid grid-cols-1 gap-3 rounded-panel border border-line bg-sub px-5 py-4 sm:grid-cols-[auto_auto_minmax(0,1fr)] sm:items-center sm:gap-10"
      title={c.zero_forms?.prefilled.join(', ')}
    >
      <div className="flex items-baseline gap-3">
        <span className="text-stat font-semibold text-ink">0</span>
        <span className="text-secondary">fields typed by {name}</span>
      </div>
      <div className="flex items-baseline gap-3">
        <span className="text-stat font-semibold text-ink">{z.prefilled}</span>
        <span className="text-secondary">filled from centrix</span>
      </div>
      <div className="flex items-baseline gap-3 lg:pr-28">
        <span className="shrink-0 text-secondary">{name} did:</span>
        <span className="text-panel font-semibold text-ink">{z.inputs}</span>
      </div>
      {c.status === 'closed' && <Mascot pose="thumbs-up" alt="Debye: repair done" className="animate-rise pointer-events-none absolute -top-8 right-3 hidden h-24 w-24 lg:block" />}
    </div>
  )
}

// ---------- activity ----------
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

export function Activity({ c }: { c: CaseDetail }) {
  const shown = c.events.filter((e) => !e.kind.startsWith('message.'))
  const isNew = useNewKeys(shown.map(eventKey), 6000)
  const list = useRef<HTMLOListElement>(null)
  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: 'smooth' })
  }, [shown.length])
  return (
    <Panel
      title="Activity"
      meta={
        <span className="inline-flex items-center gap-2">
          <span className="animate-pulse-dot h-2 w-2 rounded-full bg-positive" /> Live
        </span>
      }
    >
      {shown.length === 0 ? (
        <Empty>Waiting for the first WhatsApp message…</Empty>
      ) : (
        <ol ref={list} className="max-h-[560px] overflow-y-auto">
          {shown.map((e, i) => {
            const fresh = isNew(eventKey(e))
            const last = i === shown.length - 1
            return (
              <li key={eventKey(e)} className={`flex gap-3 border-b border-line px-5 py-3 last:border-b-0 ${fresh ? 'animate-enter' : ''} ${last ? 'bg-action-soft' : ''}`}>
                <ActorIcon actor={e.actor} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-semibold">{actorName(c, e)}</span>
                    <span className="text-label text-muted">{fmtTime(e.ts)}</span>
                  </div>
                  <div className="text-body-sm text-secondary">{explainCodes(e.summary)}</div>
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </Panel>
  )
}

// ---------- conversation (WhatsApp) ----------
/** The agent logs interactive messages as "Text [Option A] · [Option B]" or "Text [A | B | C]". Split those into buttons. */
export function splitButtons(text: string): { body: string; buttons: string[] } {
  const m = text.match(/^(.*?)\s*((?:\[[^\]]+\]\s*(?:·\s*)?)+)$/s)
  if (!m) return { body: text, buttons: [] }
  const buttons = [...m[2].matchAll(/\[([^\]]+)\]/g)].flatMap((x) => x[1].split('|').map((b) => b.trim())).filter(Boolean)
  return { body: m[1].trim(), buttons }
}

function MessageMedia({ m, docs }: { m: ThreadMessage; docs: DocumentItem[] }) {
  return (
    <>
      {m.media.map((x, i) => {
        const doc = x.document_id ? docs.find((d) => d.document_id === x.document_id) : undefined
        const mime = doc?.mime ?? ''
        const kind = x.kind ?? (mime.startsWith('audio') ? 'audio' : mime.startsWith('image') ? 'photo' : doc?.kind ?? 'file')
        const url = x.url ?? doc?.url
        if (kind === 'audio' || kind === 'voice_note')
          return (
            <div key={i} className="mb-1 flex items-center gap-2 text-label text-secondary">
              <Icon name="mic" className="h-4 w-4" /> Voice note
            </div>
          )
        if ((kind === 'photo' || kind === 'image') && url) return <img key={i} src={url} alt={doc?.filename ?? 'photo'} className="mb-1 max-h-40 w-full rounded object-cover" />
        return (
          <div key={i} className="mb-1 flex items-center gap-2 text-label text-secondary">
            <Icon name={kind === 'photo' ? 'camera' : 'file'} className="h-4 w-4" /> {kind === 'photo' ? 'Photo' : doc?.filename ?? 'Document'}
          </div>
        )
      })}
    </>
  )
}

export function Conversation({ c }: { c: CaseDetail }) {
  const messages = c.messages
  const isNew = useNewKeys(messages.map(messageKey))
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length])
  const who = c.reporters[0]?.name.split(' ')[0] ?? 'Resident'
  return (
    <Panel
      title={
        <span className="flex items-center gap-2">
          <ActorIcon actor="debye" size={28} /> Conversation
        </span>
      }
      meta={`WhatsApp · ${who}`}
    >
      <div ref={box} className="flex max-h-[560px] flex-col gap-2 overflow-y-auto p-4">
        {messages.length === 0 && <Empty>No messages yet</Empty>}
        {messages.map((m) => {
          const out = m.direction === 'out'
          const { body, buttons } = out && m.text ? splitButtons(m.text) : { body: m.text ?? '', buttons: [] as string[] }
          return (
            <div key={messageKey(m)} className={`max-w-[85%] rounded px-3 py-2 ${out ? 'self-end bg-action-soft' : 'self-start bg-sub'} ${isNew(messageKey(m)) ? 'animate-rise' : ''}`}>
              <div className="text-meta font-medium text-secondary">{out ? 'Debye' : m.contact ?? who}</div>
              {m.media?.length > 0 && <MessageMedia m={m} docs={c.documents} />}
              {body && <div className="text-body-sm text-ink">{body}</div>}
              {buttons.length > 0 && (
                <div className="mt-2 flex flex-col gap-1">
                  {buttons.map((b) => (
                    <span key={b} className="rounded border border-line bg-surface px-3 py-1 text-center text-label font-semibold text-action">
                      {b}
                    </span>
                  ))}
                </div>
              )}
              <div className="mt-0.5 text-right text-meta text-muted">{fmtTime(m.ts)}</div>
            </div>
          )
        })}
      </div>
    </Panel>
  )
}

// ---------- price check ----------
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
export const priceCheckOk = (pc: unknown) => priceCheckInfo(pc).status === 'ok'

export function InvoiceFields({ x }: { x: Record<string, unknown> }) {
  const items = Array.isArray(x.line_items) ? (x.line_items as { desc: string; qty: number; unit_price: number }[]) : []
  const num = (k: string) => (typeof x[k] === 'number' ? fmtEur(x[k] as number, true) : '—')
  const pc = priceCheckInfo(x.price_check)
  return (
    <div className="mt-2 rounded border border-line bg-surface p-3 text-label">
      <table className="w-full">
        <tbody>
          {items.map((l, i) => (
            <tr key={i} className="border-b border-line">
              <td className="py-1 pr-2">{l.desc}</td>
              <td className="py-1 text-right text-muted">{l.qty}×</td>
              <td className="py-1 text-right">{fmtEur(l.unit_price, true)}</td>
            </tr>
          ))}
          <tr>
            <td className="pt-1 text-muted">
              Net {num('net_eur')} · VAT {num('vat_eur')}
            </td>
            <td />
            <td className="pt-1 text-right font-semibold">{num('gross_eur')}</td>
          </tr>
        </tbody>
      </table>
      {pc.status === 'flagged' && (
        <ul className="mt-2 list-disc pl-5 text-warning">
          {pc.flags.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------- inspector ----------
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-line px-5 py-4 last:border-b-0">
      <h3 className="mb-2 text-panel">{title}</h3>
      <dl>{children}</dl>
    </section>
  )
}

function docSubtitle(d: DocumentItem, pc: unknown) {
  const x = (d.extracted ?? {}) as Record<string, unknown>
  if (d.kind === 'invoice') {
    const gross = typeof x.gross_eur === 'number' ? fmtEur(x.gross_eur as number, true) : null
    const st = priceCheckInfo(x.price_check ?? pc).status
    return ['Invoice', gross, st === 'ok' ? 'price check passed' : st === 'flagged' ? 'price check flagged' : null].filter(Boolean).join(' · ')
  }
  const date = d.created_at ? new Date(d.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''
  if (d.kind === 'photo') return ['Photo', date].filter(Boolean).join(' · ')
  if (d.kind === 'voice_note') return ['Voice note', date].filter(Boolean).join(' · ')
  if (d.kind === 'report') return 'Visit report'
  if (d.kind === 'contract') return 'Lease'
  return humanize(d.kind)
}

export function Documents({ docs, priceCheck }: { docs: DocumentItem[]; priceCheck?: unknown }) {
  const isNew = useNewKeys(
    docs.map((d) => d.document_id),
    8000,
  )
  const [open, setOpen] = useState<string | null>(null)
  if (docs.length === 0) return <div className="text-body-sm text-muted">No documents yet</div>
  return (
    <ul className="-mx-2 flex flex-col">
      {docs.map((d) => {
        const st = d.kind === 'invoice' ? priceCheckInfo((d.extracted as Record<string, unknown> | null)?.price_check ?? priceCheck).status : 'unknown'
        const hasFields = d.kind === 'invoice' && !!d.extracted && Object.keys(d.extracted).length > 0
        return (
          <li key={d.document_id} className={`rounded px-2 py-2 ${isNew(d.document_id) ? 'animate-enter' : ''} ${d.kind === 'invoice' ? 'bg-action-soft' : ''}`}>
            <div className="flex items-start gap-3">
              <Icon name={d.kind === 'photo' ? 'camera' : d.kind === 'voice_note' ? 'mic' : 'file'} className={`mt-0.5 h-5 w-5 shrink-0 ${d.kind === 'invoice' ? 'text-action' : 'text-secondary'}`} />
              <div className="min-w-0 flex-1">
                <div className="truncate font-semibold">{d.filename}</div>
                <div className={`text-meta ${st === 'ok' ? 'text-positive' : st === 'flagged' ? 'text-warning' : 'text-muted'}`}>{docSubtitle(d, priceCheck)}</div>
                {hasFields && (
                  <button className="text-meta font-semibold text-action hover:underline" onClick={() => setOpen(open === d.document_id ? null : d.document_id)}>
                    {open === d.document_id ? 'Hide fields' : 'Show extracted fields'}
                  </button>
                )}
              </div>
              <a href={d.url} target="_blank" rel="noreferrer" className="text-secondary hover:text-action" aria-label={`Download ${d.filename}`}>
                <Icon name="download" className="h-5 w-5" />
              </a>
            </div>
            {hasFields && open === d.document_id && <InvoiceFields x={d.extracted!} />}
          </li>
        )
      })}
    </ul>
  )
}

export function Inspector({ c, unit, docs, partnerName }: { c: CaseDetail; unit: UnitDetail | null; docs: DocumentItem[]; partnerName: (id: string) => string }) {
  const [json, setJson] = useState(false)
  const z = zeroForms(c)
  const name = c.reporters[0]?.name.split(' ')[0] ?? 'Resident'
  const inv = c.documents.find((d) => d.kind === 'invoice')
  const gross = (inv?.extracted as Record<string, unknown> | undefined)?.gross_eur as number | undefined
  const err = errorText(c.asset?.error_code, c.asset?.error_label, c.asset?.error_meaning)
  const p = unit?.property
  const boiler = unit?.assets.find((a) => a.type?.includes('boiler')) ?? unit?.assets[0]
  const k = c.consents[0]
  return (
    <aside className="panel self-start">
      <Section title="Case">
        <Prop label="Priority">{humanize(c.priority)}</Prop>
        {err && <Prop label="Boiler error">{err}</Prop>}
        <Prop label="Cost bearer">{humanize(c.cost_bearer)}</Prop>
        <Prop label="Partner">{c.partner?.name ?? 'not assigned yet'}</Prop>
        <Prop label="Visit">{c.slot ? fmtSlot(c.slot) : c.proposed_slots?.length ? `${c.proposed_slots.length} times offered` : 'not booked'}</Prop>
        <Prop label="Cost">
          {gross != null ? `${fmtEur(gross, true)} invoiced, ` : ''}
          {c.estimated_cost_eur != null ? `${fmtEur(c.estimated_cost_eur)} estimated` : '—'}
        </Prop>
        <Prop label="Approval">{c.approval?.required ? 'Needs your decision' : c.approval?.rule && c.approval.rule !== 'not evaluated yet' ? humanize(c.approval.rule) : '—'}</Prop>
        {z && (
          <Prop label={`${name}'s input`}>
            {z.inputs}. Debye filled the other {z.prefilled} fields from centrix
          </Prop>
        )}
      </Section>
      <Section title={`Unit ${c.unit_id.replace('unit_', '')}`}>
        {unit ? (
          <>
            <Prop label="Address">{p?.address}</Prop>
            <Prop label="Floor">{[unit.unit.floor, unit.unit.size_sqm ? `${unit.unit.size_sqm} m²` : null, unit.unit.rooms ? `${unit.unit.rooms} rooms` : null].filter((x) => x != null).join(' · ')}</Prop>
            <Prop label="Building">{[p?.building_year, p?.heating_type, p?.energy_class ? `energy class ${p.energy_class}` : null].filter(Boolean).join(' · ')}</Prop>
            {boiler && (
              <Prop label="Boiler">
                {boiler.make} {boiler.model}
                {boiler.installed ? ` (${boiler.installed.slice(0, 4)})` : ''}
                {boiler.last_service ? `, serviced ${new Date(boiler.last_service).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })}` : ''}
              </Prop>
            )}
            <Prop label="Tenant">{unit.tenant?.name}</Prop>
          </>
        ) : (
          <div className="text-muted">Loading…</div>
        )}
      </Section>
      <Section title="Consent">
        {k ? (
          <>
            <Prop label="Shared with">{partnerName(k.partner_id)}</Prop>
            <Prop label="Data">{humanize(k.data_shared.map((f) => f.replace('unit_floor', 'floor').replace('photos', 'photo')).join(', '))}</Prop>
            <Prop label="When">
              {fmtDateTime(k.given_at)}, {k.channel === 'whatsapp' ? 'WhatsApp' : humanize(k.channel)}
            </Prop>
            <Prop label="Purpose">{humanize(k.purpose)}</Prop>
            {k.revoked_at && <Prop label="Revoked">{fmtDateTime(k.revoked_at)}</Prop>}
          </>
        ) : (
          <div className="text-body-sm text-muted">Nothing shared yet. No data leaves centrix without {name}'s tap.</div>
        )}
      </Section>
      <section className="border-b border-line px-5 py-4 last:border-b-0">
        <h3 className="mb-2 text-panel">Documents</h3>
        <Documents docs={docs} priceCheck={c.price_check} />
      </section>
      {c.result && (
        <section className="px-5 py-4">
          <div className="flex items-center justify-between">
            <h3 className="text-panel">Written back to centrix</h3>
            <button className="text-label font-semibold text-action hover:underline" onClick={() => setJson(!json)}>
              {json ? 'Hide' : 'Show'} JSON
            </button>
          </div>
          {json && (
            <div className="mt-2">
              <JsonView value={c.result} />
            </div>
          )}
        </section>
      )}
    </aside>
  )
}

// ---------- partner choice (table, with the approval as a "needs decision" group) ----------
export function PartnerChoice({ c, ranking, chosen, onApprove }: { c: CaseDetail; ranking: RankingEntry[]; chosen?: string | null; onApprove: () => Promise<void> }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const needs = c.approval?.required || c.status === 'awaiting_approval'
  const amount = c.approval?.amount_eur ?? c.estimated_cost_eur
  return (
    <Panel title="Partner choice" meta="Ranked by Debye from the framework list">
      {needs && (
        <div className="flex flex-wrap items-center gap-4 border-b border-line bg-warning-soft px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="font-semibold">Needs your decision</div>
            <div className="text-body-sm text-secondary">
              {c.partner?.name ?? 'The partner'} estimates {fmtEur(amount)}. {c.approval?.rule ?? 'That is over your auto-approval limit'}, so the job waits for you.
            </div>
            {err && <div className="mt-1 text-negative">{err}</div>}
          </div>
          <button
            className="btn-primary"
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
            {busy ? 'Approving…' : `Approve ${fmtEur(amount)}`}
          </button>
        </div>
      )}
      {ranking.length === 0 ? (
        <Empty>Debye ranks partners once the case is triaged.</Empty>
      ) : (
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-line text-label text-muted">
              <th className="px-5 py-3 font-medium">Partner</th>
              <th className="px-3 py-3 font-medium">Score</th>
              <th className="px-5 py-3 font-medium">Why</th>
            </tr>
          </thead>
          <tbody>
            {ranking.map((r, i) => {
              const win = chosen ? r.partner_id === chosen : i === 0
              return (
                <tr key={r.partner_id} className={`border-b border-line last:border-b-0 ${win ? 'bg-action-soft' : ''}`}>
                  <td className={`px-5 py-4 ${win ? 'font-semibold' : ''}`}>{r.name}</td>
                  <td className="px-3 py-4">{r.score.toFixed(2)}</td>
                  <td className="px-5 py-4 text-body-sm text-secondary">{r.reasons.join(' · ')}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
