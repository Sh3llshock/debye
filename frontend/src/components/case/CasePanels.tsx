import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import type { CaseDetail, CaseEvent, Consent, DocumentItem, RankingEntry, ThreadMessage } from '../../api/types'
import { fmtDateTime, fmtEur, fmtSlot, fmtTime, humanize, LIFECYCLE, lifecycleIndex, statusInfo } from '../../lib/format'
import { eventKey, messageKey } from '../../lib/keys'
import { useNewKeys } from '../../lib/useNewKeys'
import { ActorIcon, actorInfo, Card, Empty, Field, JsonView, Pill, PriorityPill, StatusPill } from '../ui'

// ---------- lifecycle stepper ----------
export function Lifecycle({ status }: { status: string }) {
  const idx = lifecycleIndex(status)
  const labels: Record<string, string> = { new: 'Reported', requested: 'Sent', accepted: 'Accepted', scheduled: 'Scheduled', completed: 'Done', closed: 'Closed' }
  return (
    <ol className="flex w-full items-center gap-2">
      {LIFECYCLE.map((s, i) => {
        const done = i < idx || status === 'closed'
        const cur = i === idx && status !== 'closed'
        return (
          <li key={s} className="flex flex-1 items-center gap-2">
            <span
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 text-sm font-bold transition-colors duration-700 ${
                done ? 'border-plum bg-plum text-on-plum' : cur ? 'border-plum bg-plum-soft text-plum' : 'border-line bg-surface text-muted'
              }`}
            >
              {done ? '✓' : i + 1}
            </span>
            <span className={`hidden text-sm font-semibold md:inline ${cur ? 'text-plum' : done ? 'text-ink' : 'text-muted'}`}>{labels[s]}</span>
            {i < LIFECYCLE.length - 1 && <span className={`h-0.5 flex-1 transition-colors duration-700 ${i < idx ? 'bg-plum' : 'bg-line'}`} />}
          </li>
        )
      })}
    </ol>
  )
}

// ---------- zero forms ----------
export function zeroFormsText(c: CaseDetail) {
  const zf = c.zero_forms
  if (!zf) return null
  const taps = zf.tenant_inputs.filter((t) => t.toLowerCase().startsWith('tap')).length
  const other = zf.tenant_inputs.filter((t) => !t.toLowerCase().startsWith('tap'))
  const parts = [...other, ...(taps ? [`${taps} tap${taps > 1 ? 's' : ''}`] : [])]
  return { prefilled: zf.prefilled.length, inputs: parts.join(', ') || 'nothing yet' }
}

export function ZeroFormsCounter({ c }: { c: CaseDetail }) {
  const z = zeroFormsText(c)
  if (!z) return null
  return (
    <div className="rounded border border-plum bg-plum-soft p-4" title={c.zero_forms?.prefilled.join(', ')}>
      <div className="label text-plum">Zero forms</div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-3">
        <span className="font-serif text-3xl font-semibold text-plum">{z.prefilled}</span>
        <span className="text-lg text-plum">fields pre-filled from centrix</span>
      </div>
      <div className="mt-1 text-lg">
        Resident gave: <span className="font-semibold">{z.inputs}</span>
      </div>
    </div>
  )
}

// ---------- case card ----------
export function CaseCard({ c }: { c: CaseDetail }) {
  return (
    <Card title="Case">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <StatusPill status={c.status} big />
        <PriorityPill priority={c.priority} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Partner">{c.partner?.name ?? <span className="text-muted">not assigned</span>}</Field>
        <Field label="Visit">{c.slot ? fmtSlot(c.slot) : <span className="text-muted">not scheduled</span>}</Field>
        <Field label="Cost bearer">{humanize(c.cost_bearer)}</Field>
        <Field label="Estimate">{fmtEur(c.estimated_cost_eur)}</Field>
        {c.asset && (
          <Field label="Asset">
            {c.asset.make} {c.asset.model}
            {c.asset.error_code && <span className="ml-2 rounded-sm bg-danger-soft px-2 font-mono text-sm font-semibold text-danger">{c.asset.error_code}</span>}
          </Field>
        )}
        <Field label="Reported by">
          {c.reporters.map((r) => (
            <div key={r.contact_id}>
              {r.name} <Link className="text-plum underline" to={`/staff/units/${r.unit_id}`}>{r.unit_id.replace('unit_', '')}</Link>
              {r.relation !== 'reporter' && <span className="text-sm text-muted"> · {r.relation}</span>}
            </div>
          ))}
        </Field>
      </div>
      {c.approval && !c.approval.required && <div className="mt-4 text-sm text-muted">✓ {c.approval.rule}</div>}
      <div className="mt-4">
        <ZeroFormsCounter c={c} />
      </div>
    </Card>
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
    <Card tone="warning" className="animate-enter">
      <div className="label text-warning">Approval needed</div>
      <div className="mt-2 font-serif text-2xl font-semibold text-plum">
        Approve {fmtEur(amount)} repair{c.partner ? ` by ${c.partner.name}` : ''}?
      </div>
      {c.approval?.rule && <div className="mt-1 text-muted">{c.approval.rule}</div>}
      <button
        className="btn-primary mt-4 w-full text-lg"
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
        {busy ? 'Approving…' : 'Approve'}
      </button>
      {err && <div className="mt-2 text-danger">{err}</div>}
    </Card>
  )
}

// ---------- timeline ----------
export function Timeline({ events }: { events: CaseEvent[] }) {
  const isNew = useNewKeys(events.map(eventKey))
  const list = useRef<HTMLOListElement>(null)
  const count = events.length
  useEffect(() => {
    // scroll only the list, never the page (the page must stay put on the projector)
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: 'smooth' })
  }, [count])
  const shown = events.filter((e) => !e.kind.startsWith('message.'))
  return (
    <Card title="Timeline" action={<span className="text-sm text-muted">{shown.length} events</span>}>
      {shown.length === 0 ? (
        <Empty>No events yet</Empty>
      ) : (
        <ol ref={list} className="relative max-h-[70vh] overflow-y-auto pr-2">
          {shown.map((e, i) => (
            <li key={eventKey(e)} className={`relative flex gap-4 rounded px-2 py-3 ${isNew(eventKey(e)) ? 'animate-enter' : ''}`}>
              {i < shown.length - 1 && <span className="absolute bottom-0 left-[27px] top-14 w-0.5 bg-line" />}
              <ActorIcon actor={e.actor} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-3">
                  <span className="text-sm font-semibold text-muted">{actorInfo(e.actor).label}</span>
                  <span className="text-sm text-muted">{fmtTime(e.ts)}</span>
                  <span className="font-mono text-xs text-muted">{e.kind}</span>
                </div>
                <div className="text-lg leading-snug">{e.summary}</div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  )
}

// ---------- WhatsApp thread ----------
function mediaLabel(m: ThreadMessage['media'][number]) {
  const kind = typeof m === 'string' ? m : m.kind ?? 'file'
  return kind === 'audio' ? '🎤 Voice note' : kind === 'photo' || kind === 'image' ? '📷 Photo' : kind === 'document' || kind === 'pdf' ? '📄 Document' : `📎 ${kind}`
}

export function WhatsAppThread({ messages }: { messages: ThreadMessage[] }) {
  const isNew = useNewKeys(messages.map(messageKey))
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length])
  return (
    <Card title={<span className="flex items-center gap-2">WhatsApp <span className="text-sm font-normal text-muted font-sans">resident ↔ Debye</span></span>}>
      <div ref={box} className="flex max-h-[52vh] flex-col gap-2 overflow-y-auto rounded bg-wa-bg p-3">
        {messages.length === 0 && <div className="p-4 text-center text-muted">No messages yet</div>}
        {messages.map((m) => (
          <div
            key={messageKey(m)}
            className={`max-w-[85%] rounded px-3 py-2 shadow-card ${m.direction === 'in' ? 'self-start bg-wa-in' : 'self-end bg-wa-out'} ${isNew(messageKey(m)) ? 'animate-enter' : ''}`}
          >
            <div className="text-xs font-semibold text-muted">{m.direction === 'in' ? m.contact : 'Debye'}</div>
            {m.media?.length > 0 && <div className="text-sm text-muted">{m.media.map(mediaLabel).join(' · ')}</div>}
            <div className="text-body leading-snug">{m.text}</div>
            <div className="text-right text-xs text-muted">{fmtTime(m.ts)}</div>
          </div>
        ))}
      </div>
    </Card>
  )
}

// ---------- ranking ----------
export function Ranking({ ranking, chosen }: { ranking: RankingEntry[]; chosen?: string | null }) {
  return (
    <Card title="Why this partner">
      {ranking.length === 0 ? (
        <Empty>Ranking appears once Debye has triaged the case</Empty>
      ) : (
        <ol className="flex flex-col gap-4">
          {ranking.map((r, i) => {
            const win = chosen ? r.partner_id === chosen : i === 0
            return (
              <li key={r.partner_id} className={`rounded border p-3 ${win ? 'border-plum bg-plum-soft' : 'border-line'}`}>
                <div className="flex items-baseline justify-between gap-2">
                  <span className={`font-semibold ${win ? 'text-plum' : ''}`}>
                    {i + 1}. {r.name}
                  </span>
                  <span className="font-mono font-semibold">{r.score.toFixed(2)}</span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-alt">
                  <div className={`h-full rounded-full transition-all duration-700 ${win ? 'bg-plum' : 'bg-muted'}`} style={{ width: `${Math.round(r.score * 100)}%` }} />
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {r.reasons.map((x) => (
                    <span key={x} className="rounded-pill bg-surface px-2 text-sm text-muted">{x}</span>
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
export function ConsentRecord({ consents, partnerName }: { consents: Consent[]; partnerName: (id: string) => string }) {
  const [open, setOpen] = useState(true)
  return (
    <Card title="Consent record" action={consents.length > 0 && <button className="text-sm font-semibold text-plum" onClick={() => setOpen(!open)}>{open ? 'Hide JSON' : 'Show JSON'}</button>}>
      {consents.length === 0 ? (
        <Empty>No data shared yet. Nothing leaves centrix without the resident's tap.</Empty>
      ) : (
        <div className="flex flex-col gap-4">
          {consents.map((k) => (
            <div key={k.partner_id + k.given_at}>
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone="success">✓ Consent given</Pill>
                <span className="font-semibold">→ {partnerName(k.partner_id)}</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {k.data_shared.map((f) => (
                  <span key={f} className="rounded-pill border border-line px-2 font-mono text-sm">{f}</span>
                ))}
              </div>
              <div className="mt-2 text-sm text-muted">
                {fmtDateTime(k.given_at)} · via {k.channel} · {k.purpose}
              </div>
              {open && (
                <div className="mt-2">
                  <JsonView value={{ data_shared: k.data_shared, given_at: k.given_at, channel: k.channel }} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

// ---------- documents ----------
const DOC_ICON: Record<string, string> = { invoice: '🧾', photo: '📷', report: '📋', contract: '📄' }

export function InvoiceFields({ x }: { x: Record<string, unknown> }) {
  const items = Array.isArray(x.line_items) ? (x.line_items as { desc: string; qty: number; unit_price: number }[]) : []
  const num = (k: string) => (typeof x[k] === 'number' ? fmtEur(x[k] as number, true) : '—')
  return (
    <div className="mt-2 rounded bg-surface-alt p-3">
      <div className="grid grid-cols-3 gap-2">
        <Field label="Net">{num('net_eur')}</Field>
        <Field label="VAT">{num('vat_eur')}</Field>
        <Field label="Gross"><span className="font-semibold">{num('gross_eur')}</span></Field>
        {x.invoice_number != null && <Field label="Number">{String(x.invoice_number)}</Field>}
        {x.date != null && <Field label="Date">{String(x.date)}</Field>}
        {x.labour_hours != null && <Field label="Labour">{String(x.labour_hours)} h</Field>}
      </div>
      {items.length > 0 && (
        <table className="mt-3 w-full text-sm">
          <tbody>
            {items.map((l, i) => (
              <tr key={i} className="border-t border-line">
                <td className="py-1">{l.desc}</td>
                <td className="py-1 text-right text-muted">{l.qty}×</td>
                <td className="py-1 text-right">{fmtEur(l.unit_price, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {x.price_check != null && (
        <div className="mt-2">
          <Pill tone={String(x.price_check).startsWith('ok') ? 'success' : 'warning'}>Price check: {String(x.price_check)}</Pill>
        </div>
      )}
    </div>
  )
}

export function Documents({ docs, title = 'Documents' }: { docs: DocumentItem[]; title?: string }) {
  const isNew = useNewKeys(docs.map((d) => d.document_id))
  return (
    <Card title={title}>
      {docs.length === 0 ? (
        <Empty>No documents yet</Empty>
      ) : (
        <ul className="flex flex-col gap-3">
          {docs.map((d) => (
            <li key={d.document_id} className={`rounded px-1 ${isNew(d.document_id) ? 'animate-enter' : ''}`}>
              <a href={d.url} target="_blank" rel="noreferrer" className="flex items-center gap-3 hover:underline">
                <span className="text-xl">{DOC_ICON[d.kind] ?? '📎'}</span>
                <span className="min-w-0 flex-1 truncate font-semibold">{d.filename}</span>
                <span className="text-sm text-muted">{humanize(d.kind)}</span>
              </a>
              {d.kind === 'invoice' && d.extracted && Object.keys(d.extracted).length > 0 && <InvoiceFields x={d.extracted} />}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

// ---------- result ----------
export function ResultPayload({ result }: { result: Record<string, unknown> | null }) {
  if (!result) return null
  return (
    <Card title="Written back to centrix" tone="success" className="animate-enter">
      <JsonView value={result} />
    </Card>
  )
}

export function statusLabel(s: string) {
  return statusInfo(s).label
}
