import type { CaseDetail, DiagnosisQA } from '../../api/types'
import { explainCodes } from '../../lib/errors'
import { fmtEur } from '../../lib/format'
import { t } from '../../lib/i18n'
import { Icon } from '../icons'
import { Chip } from '../ui'
import { KB_CAUSES, KB_QUESTIONS } from '../../lib/kb'

/** Trade the job needs, in words (English source; shown through t()). */
const TRADE_LABEL: Record<string, string> = {
  plumbing: 'Plumber',
  plumber: 'Plumber',
  heating: 'Heating',
  electrical: 'Electrician',
  electrician: 'Electrician',
  caretaker: 'Caretaker',
  gas_utility: 'Gas utility',
}
export function tradeLabel(trade?: string | null, outcome?: string | null) {
  if (!trade || outcome === 'self_help') return t('No technician needed')
  return t(TRADE_LABEL[trade] ?? trade.charAt(0).toUpperCase() + trade.slice(1))
}

/** No-technician outcomes avoid a call-out. The KB has no cost for them, so we fall back to its cheapest technician job (€180). */
const KB_MIN_TECHNICIAN_EUR = 180
const NO_TECHNICIAN = new Set(['self_help', 'caretaker'])

/** Question + answer from any of the shapes the agent may send: {question, answer}, {id, answer}, "q_scope=everywhere" or plain text. */
function qa(x: DiagnosisQA | string): { q: string; a: string } {
  const fromKb = (id: string, ans: string) => {
    const k = KB_QUESTIONS[id]
    return k ? { q: k.text, a: k.answers[ans] ?? ans.replace(/_/g, ' ') } : null
  }
  if (typeof x === 'string') {
    const m = x.match(/^(q_\w+)\s*[=:]\s*(.+)$/)
    if (m) return fromKb(m[1], m[2].trim()) ?? { q: m[1].replace(/^q_/, '').replace(/_/g, ' '), a: m[2] }
    return fromKb(x, '') ?? { q: x, a: '' }
  }
  const ans = x.answer_text ?? x.answer ?? x.a ?? ''
  const q = x.question ?? x.text ?? x.q
  if (!q && x.id) return fromKb(x.id, ans) ?? { q: x.id, a: ans }
  return { q: q ?? '', a: x.id && KB_QUESTIONS[x.id]?.answers[ans] ? KB_QUESTIONS[x.id].answers[ans] : ans }
}

/** The diagnosis outcome: from the API, else caretaker if the caretaker was notified, else the KB entry for the cause. */
export function diagnosisOutcome(c: CaseDetail): string | null {
  const d = c.diagnosis
  if (!d) return null
  if (c.resolution && NO_TECHNICIAN.has(c.resolution)) return c.resolution
  return d.outcome ?? (c.events.some((e) => e.kind === 'caretaker.notified') ? 'caretaker' : KB_CAUSES[d.cause_id]?.outcome ?? null)
}
export const isNoTechnician = (c: CaseDetail) => NO_TECHNICIAN.has(c.resolution ?? '') || NO_TECHNICIAN.has(diagnosisOutcome(c) ?? '')
/** For list rows (CaseSummary): closed without a partner. */
export const isNoTechnicianSummary = (c: { resolution?: string | null }) => NO_TECHNICIAN.has(c.resolution ?? '')

/** "Debye's diagnosis": likely cause, confidence, one-line reasoning, the questions asked, the trade it needs. */
export function DiagnosisPanel({ c }: { c: CaseDetail }) {
  const d = c.diagnosis
  if (!d) return null
  const pct = d.confidence == null ? null : Math.round(d.confidence <= 1 ? d.confidence * 100 : d.confidence)
  // outcome/cost come in a backend follow-up; until then fall back to the KB entry for the cause,
  // and a caretaker.notified event means the caretaker outcome.
  const kb = KB_CAUSES[d.cause_id]
  const outcome = diagnosisOutcome(c)
  const trade = outcome && NO_TECHNICIAN.has(outcome) ? (outcome === 'caretaker' ? 'caretaker' : null) : (c.trade ?? d.trade ?? kb?.trade ?? null)
  const cost = d.estimated_cost_eur ?? kb?.cost ?? null
  const saved = outcome && NO_TECHNICIAN.has(outcome) ? (c.saving_eur ?? d.estimated_saving_eur ?? KB_MIN_TECHNICIAN_EUR) : null
  const qs = (d.questions_asked ?? []).map(qa).filter((x) => x.q)
  return (
    <section className="panel overflow-hidden">
      <header className="panel-head">
        <h2 className="flex items-center gap-2 text-panel">
          <Icon name="search" className="h-5 w-5 text-action" /> {t("Debye's diagnosis")}
        </h2>
        <Chip tone={outcome === 'emergency' ? 'negative' : saved != null ? 'positive' : 'action'}>{tradeLabel(trade, outcome)}</Chip>
      </header>
      <div className="px-5 py-4">
        <div className="flex flex-wrap items-baseline gap-x-3">
          <span className="text-label text-muted">{t('Likely cause')}</span>
          <span className="text-body font-semibold">{explainCodes(d.label)}</span>
          {pct != null && <span className="text-label font-semibold text-action">{t('{n}% confident', { n: pct })}</span>}
        </div>
        {pct != null && (
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-sub" aria-hidden>
            <div className="h-full rounded-full bg-action" style={{ width: `${pct}%` }} />
          </div>
        )}
        {d.reasoning && <p className="mt-3 text-body-sm text-ink">{explainCodes(d.reasoning)}</p>}
        {qs.length > 0 && (
          <div className="mt-3">
            <div className="text-label text-muted">{t('Questions Debye asked')}</div>
            <ol className="mt-1 flex flex-col gap-1.5">
              {qs.map((x, i) => (
                <li key={i} className="grid grid-cols-[20px_minmax(0,1fr)] gap-2 text-body-sm">
                  <span className="text-muted">{i + 1}.</span>
                  <span>
                    <span className="text-secondary">{x.q}</span>
                    {x.a && (
                      <>
                        {' '}
                        <span className="font-medium text-ink">→ {x.a}</span>
                      </>
                    )}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}
        {saved != null && (
          <div className="mt-4 flex items-center gap-2 rounded border border-positive bg-positive-soft px-3 py-2 font-semibold text-positive">
            <Icon name="check" className="h-5 w-5 shrink-0" />
            {outcome === 'caretaker' ? t('No technician sent, the caretaker handles it. Saved ~{eur}', { eur: fmtEur(saved) }) : t('No technician sent, saved ~{eur}', { eur: fmtEur(saved) })}
          </div>
        )}
        {outcome === 'technician' && cost != null && <div className="mt-3 text-label text-muted">{t('Typical cost for this cause: {eur}', { eur: fmtEur(cost) })}</div>}
      </div>
    </section>
  )
}
