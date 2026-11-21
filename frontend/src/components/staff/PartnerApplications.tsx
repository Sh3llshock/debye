// Feature 1: staff review of self-onboarded partners (Partners page + inbox badge).
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import type { PartnerApplication, PrecheckRow } from '../../api/types'
import { tradeLabel } from '../case/Diagnosis'
import { fmtRelative } from '../../lib/format'
import { t } from '../../lib/i18n'
import { useStream } from '../../lib/stream'
import { useDebounced, useResource } from '../../lib/useResource'
import { Pill } from './StaffBits'

/** Pending partner applications, refreshed live (partner.applied / approved / rejected events). */
export function usePartnerApplications() {
  const r = useResource(() => api.partnerApplications().catch(() => [] as PartnerApplication[]), [])
  const refetch = useDebounced(r.reload, 400)
  useStream((ev) => {
    if (String(ev.type).startsWith('partner.') || ev.type === 'demo.reset' || ev.type === 'clock.skipped') refetch()
  })
  return r
}

/** Small inbox banner: "2 new partners to review". */
export function NewPartnersBanner() {
  const { data } = usePartnerApplications()
  if (!data?.length) return null
  return (
    <Link to="/staff/partners" className="mx-[18px] mb-2.5 flex items-center justify-between gap-2 rounded-tile bg-wine-tint px-3 py-2 text-label font-semibold text-wine no-underline hover:underline">
      <span>{data.length === 1 ? t('1 new partner to review') : t('{n} new partners to review', { n: data.length })}</span>
      <span aria-hidden>→</span>
    </Link>
  )
}

const TONE = { pass: 'ok', warn: 'warn', fail: 'red' } as const
const MARK = { pass: '✓', warn: '!', fail: '✕' } as const

function CheckRow({ c }: { c: PrecheckRow }) {
  return (
    <li className="flex flex-wrap items-start justify-between gap-2 border-t border-line py-2 first:border-t-0">
      <span className="min-w-0">
        <b className="font-semibold">{t(c.label)}</b>
        <span className="block text-label text-muted [overflow-wrap:anywhere]">{c.detail}</span>
      </span>
      <Pill tone={TONE[c.status]}>
        {MARK[c.status]} {t(c.status === 'pass' ? 'Pass' : c.status === 'warn' ? 'Check' : 'Fail')}
      </Pill>
    </li>
  )
}

function area(m: PartnerApplication['manifest']): string {
  const a = m.service_area
  if (a?.postcodes?.length) return a.postcodes.join(', ')
  if (a?.radius_km) return t('{km} km around {pc}', { km: a.radius_km, pc: a.base_postcode ?? '' })
  return '–'
}

function ApplicationCard({ a, onDone }: { a: PartnerApplication; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const pricing = (a.manifest.pricing ?? {}) as Record<string, unknown>
  const trades = a.manifest.capabilities?.trades ?? []
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setErr(null)
    try {
      await fn()
      onDone()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <article className="card">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-panel">{a.name}</h3>
          <p className="mt-0.5 text-label text-muted">
            {[trades.map((x) => tradeLabel(x)).join(', '), area(a.manifest), a.applied_at ? t('applied {when}', { when: fmtRelative(a.applied_at) }) : null].filter(Boolean).join(' · ')}
          </p>
        </div>
        <Pill tone={TONE[a.precheck_result]}>{a.precheck_result === 'pass' ? t('All checks pass') : a.precheck_result === 'warn' ? t('Needs a look') : t('Checks failed')}</Pill>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          <dl className="kv">
            {(
              [
                [t('Company'), [a.company.name, [a.company.postcode, a.company.city].filter(Boolean).join(' ')].filter(Boolean).join(', ')],
                [t('VAT ID'), a.company.vat_id],
                [t('Brands'), (a.manifest.capabilities?.brands_certified ?? []).join(', ')],
                [t('Callout'), pricing.callout_fee_eur != null ? `€${pricing.callout_fee_eur}` : null],
                [t('Hourly'), pricing.hourly_eur != null ? `€${pricing.hourly_eur}` : null],
              ] as [string, string | null | undefined][]
            )
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k} className="contents">
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
          </dl>
          <div className="mb-1.5 mt-3 text-label text-muted">{t('Documents')}</div>
          {a.documents.length === 0 ? (
            <span className="text-muted">{t('No documents uploaded')}</span>
          ) : (
            <ul className="m-0 list-none p-0">
              {a.documents.map((d) => (
                <li key={d.document_id} className="py-1">
                  <a href={d.url} target="_blank" rel="noreferrer" className="font-semibold text-wine no-underline hover:underline">
                    {t(d.label)}
                  </a>
                  <span className="text-label text-muted">
                    {' · '}
                    {[d.extracted.number, d.extracted.valid_until ? t('valid until {d}', { d: String(d.extracted.valid_until) }) : null].filter(Boolean).join(' · ') || d.filename}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <div className="mb-1.5 text-label text-muted">{t('Automatic checks')}</div>
          <ul className="m-0 list-none p-0">
            {a.precheck.map((c) => (
              <CheckRow key={c.id} c={c} />
            ))}
          </ul>
        </div>
      </div>
      {err && <p className="mt-3 font-medium text-red">{err}</p>}
      {rejecting ? (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <input className="field min-w-[220px] flex-1" autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t('Reason (shown to the partner)')} />
          <button className="btn-ghost" disabled={busy} onClick={() => setRejecting(false)}>
            {t('Cancel')}
          </button>
          <button className="btn-secondary" disabled={busy || !reason.trim()} onClick={() => run(() => api.rejectPartner(a.partner_id, reason.trim()))}>
            {t('Reject')}
          </button>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button className="btn-primary" disabled={busy} onClick={() => run(() => api.approvePartner(a.partner_id))}>
            {busy ? t('Saving…') : t('Approve partner')}
          </button>
          <button className="btn-ghost" disabled={busy} onClick={() => setRejecting(true)}>
            {t('Reject…')}
          </button>
        </div>
      )}
    </article>
  )
}

/** "New partners" section at the top of /staff/partners. Renders nothing when nobody waits. */
export function NewPartnersSection({ onChange }: { onChange?: () => void }) {
  const { data, reload } = usePartnerApplications()
  if (!data?.length) return null
  return (
    <section className="mb-5">
      <h2 className="mb-2.5 flex items-center gap-2 text-head font-semibold">
        {t('New partners')}
        <span className="rounded-full bg-wine px-2 py-px text-meta font-bold" style={{ color: '#fff' }}>{data.length}</span>
      </h2>
      <div className="grid grid-cols-1 gap-3.5">
        {data.map((a) => (
          <ApplicationCard
            key={a.partner_id}
            a={a}
            onDone={() => {
              reload()
              onChange?.()
            }}
          />
        ))}
      </div>
    </section>
  )
}
