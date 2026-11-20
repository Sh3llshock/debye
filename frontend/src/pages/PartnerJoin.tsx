import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { OnboardCheck, OnboardResult } from '../api/types'
import { useCrumbs } from '../components/Layout'
import { Icon } from '../components/icons'
import { Chip, Mascot } from '../components/ui'
import { t } from '../lib/i18n'

/* ---------------------------------------------------------------- form → manifest (docs/connector-spec.md §2) */

const TRADES: { id: string; label: string; brands: string[]; assetTypes?: string[] }[] = [
  { id: 'heating', label: 'Heating', brands: ['Vaillant', 'Viessmann', 'Buderus', 'Wolf', 'Junkers'], assetTypes: ['gas_boiler', 'heat_pump'] },
  { id: 'plumbing', label: 'Plumbing', brands: ['Grohe', 'Hansgrohe', 'Geberit'] },
  { id: 'electrical', label: 'Electrical', brands: ['Hager', 'ABB', 'Siemens'] },
  { id: 'roofing', label: 'Roofing', brands: ['Velux', 'Braas'] },
  { id: 'locksmith', label: 'Locksmith', brands: ['ABUS', 'DOM', 'BKS'] },
]

const CONTEXT = [
  { key: 'address', source: 'property.address', pii: true, label: 'Address' },
  { key: 'unit_floor', source: 'unit.floor', pii: false, label: 'Floor' },
  { key: 'asset', source: 'asset', pii: false, label: 'Device (make, model)' },
  { key: 'error_code', source: 'case.error_code', pii: false, label: 'Error code' },
  { key: 'tenant_name', source: 'tenant.name', pii: true, label: 'Resident name' },
  { key: 'tenant_phone', source: 'tenant.phone', pii: true, label: 'Resident phone' },
  { key: 'photos', source: 'case.documents[kind=photo]', pii: true, label: 'Photos' },
]

type Transport = 'portal' | 'api' | 'whatsapp' | 'email'
type Tech = { name: string; skills: string[] }
type Form = {
  name: string
  trades: string[]
  brands: string[]
  areaMode: 'radius' | 'postcodes'
  basePostcode: string
  radiusKm: number
  postcodes: string
  pricing: 'framework_agreement' | 'quote'
  callout: number
  hourly: number
  transport: Transport
  baseUrl: string
  address: string
  techs: Tech[]
  urgentHours: number
  context: string[]
}

const EMPTY: Form = {
  name: '',
  trades: ['heating'],
  brands: [],
  areaMode: 'radius',
  basePostcode: '52062',
  radiusKm: 15,
  postcodes: '52062, 52064, 52066',
  pricing: 'framework_agreement',
  callout: 79,
  hourly: 65,
  transport: 'portal',
  baseUrl: 'https://api.example-partner.de/centrix',
  address: '',
  techs: [{ name: '', skills: ['heating'] }],
  urgentHours: 4,
  context: ['address', 'unit_floor', 'asset', 'error_code', 'tenant_name', 'tenant_phone', 'photos'],
}

const DEMO_FORM: Form = {
  ...EMPTY,
  name: 'Heizung Müller GmbH',
  trades: ['heating', 'plumbing'],
  brands: ['Vaillant', 'Buderus'],
  techs: [
    { name: 'Jonas Müller', skills: ['heating', 'Vaillant'] },
    { name: 'Eva Krämer', skills: ['plumbing'] },
  ],
  address: '+49 241 555 0199',
}

export function slugify(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/ä/g, 'ae')
      .replace(/ö/g, 'oe')
      .replace(/ü/g, 'ue')
      .replace(/ß/g, 'ss')
      .replace(/\b(gmbh|ag|kg|ug|ohg|e\.?k\.?|co)\b/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 40) || 'partner'
  )
}

const shortName = (n: string) => n.replace(/\s+(GmbH|AG|KG|UG|OHG|e\.\s?K\.)(\s|&|$).*$/i, '').trim() || n

function buildManifest(f: Form): Record<string, unknown> {
  const id = slugify(f.name)
  const primary = f.trades[0] ?? 'heating'
  const heatingOnly = f.trades.length === 1 && f.trades[0] === 'heating'
  const transport =
    f.transport === 'portal'
      ? { type: 'portal', url: `/partner/${id}` }
      : f.transport === 'api'
        ? { type: 'api', base_url: f.baseUrl.trim(), auth: { type: 'hmac', header: 'X-Centrix-Signature' } }
        : { type: 'conversational', channel: f.transport, address: f.address.trim() }
  return {
    partner_id: id,
    name: f.name.trim(),
    category: `repair.${primary}`,
    kind: 'deliver',
    triggers: f.trades.map((tr) => `case.repair.${tr}`),
    service_area:
      f.areaMode === 'radius'
        ? { base_postcode: f.basePostcode.trim(), radius_km: f.radiusKm }
        : { postcodes: f.postcodes.split(/[\s,;]+/).filter(Boolean) },
    capabilities: { trades: f.trades, brands_certified: f.brands },
    eligibility: [
      ...(heatingOnly ? [{ field: 'asset.type', op: 'in', value: TRADES[0].assetTypes }] : []),
      { field: 'property.postcode', op: 'in_service_area' },
    ],
    pricing: f.pricing === 'framework_agreement' ? { model: 'framework_agreement', callout_fee_eur: f.callout, hourly_eur: f.hourly } : { model: 'quote' },
    required_context: CONTEXT.filter((c) => f.context.includes(c.key)).map(({ key, source, pii }) => ({ key, source, pii, consent_required: pii })),
    availability: f.transport === 'api' ? { mode: 'api', availability_endpoint: `${f.baseUrl.trim()}/availability` } : { mode: 'conversational' },
    transport,
    status_events: ['accepted', 'declined', 'scheduled', 'in_progress', 'completed', 'invoiced'],
    documents_returned: ['visit_report', 'invoice'],
    sla: { urgent_response_hours: f.urgentHours, standard_response_hours: 48 },
  }
}

/* ---------------------------------------------------------------- small controls */

function Toggle({ on, onClick, children, disabled }: { on: boolean; onClick: () => void; children: ReactNode; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={on}
      className={`inline-flex h-9 items-center gap-1.5 rounded-chip border px-3 text-label font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
        on ? 'border-action bg-action-soft text-action' : 'border-line bg-surface text-secondary hover:bg-sub'
      }`}
    >
      {on && <Icon name="check" className="h-3.5 w-3.5" />}
      {children}
    </button>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <div>
        <div className="text-label font-semibold text-ink">{label}</div>
        {hint && <div className="text-meta text-muted">{hint}</div>}
      </div>
      {children}
    </div>
  )
}

const inputCls = 'h-11 w-full rounded border border-line bg-surface px-3 text-body focus:border-action focus:outline-none'

const toggle = (xs: string[], x: string) => (xs.includes(x) ? xs.filter((y) => y !== x) : [...xs, x])

/* ---------------------------------------------------------------- page */

const STEPS = ['Company', 'Area & prices', 'Jobs & team'] as const

/** /partners/join: a partner fills three short steps; the connector manifest builds live beside the form. */
export default function PartnerJoin() {
  useCrumbs([{ label: t('Partners'), to: '/staff/partners' }, { label: t('Onboard a partner') }])
  const [f, setF] = useState<Form>(EMPTY)
  const [step, setStep] = useState(0)
  const [checks, setChecks] = useState<OnboardCheck[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<OnboardResult | null>(null)
  const set = (patch: Partial<Form>) => setF((x) => ({ ...x, ...patch }))

  const manifest = useMemo(() => buildManifest(f), [f])
  const json = useMemo(() => JSON.stringify(manifest, null, 2), [manifest])

  // live validation against the backend's connector-spec validator (same code that guards POST)
  useEffect(() => {
    let alive = true
    const id = setTimeout(() => {
      api
        .onboardValidate(manifest)
        .then((r) => alive && setChecks(r.checks))
        .catch(() => alive && setChecks(null))
    }, 250)
    return () => {
      alive = false
      clearTimeout(id)
    }
  }, [json]) // eslint-disable-line react-hooks/exhaustive-deps

  const valid = !!f.name.trim() && !!checks && checks.every((c) => c.ok)
  const brandChoices = TRADES.filter((tr) => f.trades.includes(tr.id)).flatMap((tr) => tr.brands)
  const skillChoices = [...f.trades, ...f.brands]

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      setDone(await api.onboard(manifest, f.techs.filter((x) => x.name.trim())))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (done) return <Live result={done} onAgain={() => { setDone(null); setF(EMPTY); setStep(0) }} />

  const setTech = (i: number, patch: Partial<Tech>) => set({ techs: f.techs.map((x, j) => (j === i ? { ...x, ...patch } : x)) })

  return (
    <div className="flex flex-col gap-work">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-page">{t('Become a Debye partner')}</h1>
          <p className="mt-1 max-w-[640px] text-body text-secondary">
            {t('Three short steps. Debye turns your answers into a connector manifest and starts sending you matching jobs right away.')}
          </p>
        </div>
        <button type="button" className="btn-ghost" onClick={() => setF(DEMO_FORM)}>
          {t('Fill demo partner')}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-work lg:grid-cols-[minmax(0,1fr)_minmax(0,440px)]">
        {/* ---------------- form */}
        <section className="panel overflow-hidden">
          <ol className="flex border-b border-line">
            {STEPS.map((s, i) => (
              <li key={s} className="flex-1">
                <button
                  type="button"
                  onClick={() => setStep(i)}
                  className={`flex w-full items-center gap-2 px-4 py-3 text-left text-label font-semibold ${i === step ? 'border-b-2 border-action text-action' : 'text-secondary hover:bg-sub'}`}
                >
                  <span className={`inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-meta ${i < step ? 'bg-action text-on-action' : i === step ? 'bg-action-soft text-action' : 'bg-sub text-muted'}`}>
                    {i < step ? <Icon name="check" className="h-3.5 w-3.5" /> : i + 1}
                  </span>
                  <span className="truncate">{t(s)}</span>
                </button>
              </li>
            ))}
          </ol>

          <div className="flex flex-col gap-6 p-5">
            {step === 0 && (
              <>
                <Field label={t('Company name')}>
                  <input className={inputCls} value={f.name} placeholder="Heizung Müller GmbH" onChange={(e) => set({ name: e.target.value })} autoFocus />
                </Field>
                <Field label={t('Trades')} hint={t('Debye sends you cases of these trades.')}>
                  <div className="flex flex-wrap gap-2">
                    {TRADES.map((tr) => (
                      <Toggle
                        key={tr.id}
                        on={f.trades.includes(tr.id)}
                        disabled={f.trades.length === 1 && f.trades[0] === tr.id}
                        onClick={() => {
                          const trades = toggle(f.trades, tr.id)
                          const keep = new Set(TRADES.filter((x) => trades.includes(x.id)).flatMap((x) => x.brands))
                          set({ trades, brands: f.brands.filter((b) => keep.has(b)) })
                        }}
                      >
                        {t(tr.label)}
                      </Toggle>
                    ))}
                  </div>
                </Field>
                <Field label={t('Certified brands')} hint={t('Certified partners rank higher for devices of that brand.')}>
                  <div className="flex flex-wrap gap-2">
                    {brandChoices.map((b) => (
                      <Toggle key={b} on={f.brands.includes(b)} onClick={() => set({ brands: toggle(f.brands, b) })}>
                        {b}
                      </Toggle>
                    ))}
                  </div>
                </Field>
              </>
            )}

            {step === 1 && (
              <>
                <Field label={t('Service area')}>
                  <div className="flex flex-wrap gap-2">
                    <Toggle on={f.areaMode === 'radius'} onClick={() => set({ areaMode: 'radius' })}>{t('Radius around a postcode')}</Toggle>
                    <Toggle on={f.areaMode === 'postcodes'} onClick={() => set({ areaMode: 'postcodes' })}>{t('List of postcodes')}</Toggle>
                  </div>
                  {f.areaMode === 'radius' ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <input className={`${inputCls} w-28`} inputMode="numeric" maxLength={5} value={f.basePostcode} onChange={(e) => set({ basePostcode: e.target.value.replace(/\D/g, '') })} aria-label={t('Postcode')} />
                      {[5, 10, 15, 30, 50].map((km) => (
                        <Toggle key={km} on={f.radiusKm === km} onClick={() => set({ radiusKm: km })}>{km} km</Toggle>
                      ))}
                    </div>
                  ) : (
                    <input className={inputCls} value={f.postcodes} onChange={(e) => set({ postcodes: e.target.value })} placeholder="52062, 52064" />
                  )}
                </Field>
                <Field label={t('Pricing')}>
                  <div className="flex flex-wrap gap-2">
                    <Toggle on={f.pricing === 'framework_agreement'} onClick={() => set({ pricing: 'framework_agreement' })}>{t('Fixed rates (call-out + hourly)')}</Toggle>
                    <Toggle on={f.pricing === 'quote'} onClick={() => set({ pricing: 'quote' })}>{t('Quote per job')}</Toggle>
                  </div>
                  {f.pricing === 'framework_agreement' && (
                    <div className="grid grid-cols-2 gap-3 sm:max-w-[360px]">
                      <label className="flex flex-col gap-1 text-meta text-muted">
                        {t('Call-out fee (€)')}
                        <input className={inputCls} type="number" min={0} value={f.callout} onChange={(e) => set({ callout: Number(e.target.value) })} />
                      </label>
                      <label className="flex flex-col gap-1 text-meta text-muted">
                        {t('Hourly rate (€)')}
                        <input className={inputCls} type="number" min={0} value={f.hourly} onChange={(e) => set({ hourly: Number(e.target.value) })} />
                      </label>
                    </div>
                  )}
                </Field>
                <Field label={t('Response time for urgent jobs')} hint={t('Debye re-dispatches the job if you do not answer in time.')}>
                  <div className="flex flex-wrap gap-2">
                    {[2, 4, 8, 24].map((h) => (
                      <Toggle key={h} on={f.urgentHours === h} onClick={() => set({ urgentHours: h })}>{t('{h} h', { h })}</Toggle>
                    ))}
                  </div>
                </Field>
              </>
            )}

            {step === 2 && (
              <>
                <Field label={t('How do you want to receive jobs?')}>
                  <div className="flex flex-wrap gap-2">
                    {(
                      [
                        ['portal', 'Partner portal'],
                        ['api', 'API'],
                        ['whatsapp', 'WhatsApp'],
                        ['email', 'Email'],
                      ] as [Transport, string][]
                    ).map(([k, label]) => (
                      <Toggle key={k} on={f.transport === k} onClick={() => set({ transport: k })}>{t(label)}</Toggle>
                    ))}
                  </div>
                  {f.transport === 'api' && <input className={inputCls} value={f.baseUrl} onChange={(e) => set({ baseUrl: e.target.value })} placeholder="https://…" aria-label={t('API base URL')} />}
                  {(f.transport === 'whatsapp' || f.transport === 'email') && (
                    <input
                      className={inputCls}
                      value={f.address}
                      onChange={(e) => set({ address: e.target.value })}
                      placeholder={f.transport === 'email' ? 'jobs@firma.de' : '+49 …'}
                      aria-label={f.transport === 'email' ? t('Email') : t('WhatsApp number')}
                    />
                  )}
                  {f.transport === 'portal' && <div className="text-meta text-muted">{t('You get your own job inbox on centrix: accept, propose times, upload the invoice.')}</div>}
                </Field>

                <Field label={t('What you need for a job')} hint={t('Personal data is only shared after the resident agrees.')}>
                  <div className="flex flex-wrap gap-2">
                    {CONTEXT.map((c) => (
                      <Toggle key={c.key} on={f.context.includes(c.key)} onClick={() => set({ context: toggle(f.context, c.key) })}>
                        {t(c.label)}
                        {c.pii && <Icon name="shield" className="h-3.5 w-3.5 opacity-70" />}
                      </Toggle>
                    ))}
                  </div>
                </Field>

                <Field label={t('Technicians')} hint={t('Each technician gets a phone page to confirm appointments.')}>
                  <ul className="flex flex-col gap-3">
                    {f.techs.map((x, i) => (
                      <li key={i} className="rounded border border-line p-3">
                        <div className="flex gap-2">
                          <input className={inputCls} value={x.name} placeholder={t('Name')} onChange={(e) => setTech(i, { name: e.target.value })} aria-label={t('Technician name')} />
                          {f.techs.length > 1 && (
                            <button type="button" className="btn-ghost px-3" onClick={() => set({ techs: f.techs.filter((_, j) => j !== i) })} aria-label={t('Remove')}>
                              ✕
                            </button>
                          )}
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {skillChoices.map((s) => (
                            <Toggle key={s} on={x.skills.includes(s)} onClick={() => setTech(i, { skills: toggle(x.skills, s) })}>
                              {TRADES.some((tr) => tr.id === s) ? t(TRADES.find((tr) => tr.id === s)!.label) : s}
                            </Toggle>
                          ))}
                        </div>
                      </li>
                    ))}
                  </ul>
                  <button type="button" className="btn-secondary self-start" onClick={() => set({ techs: [...f.techs, { name: '', skills: [f.trades[0]] }] })}>
                    + {t('Add technician')}
                  </button>
                </Field>
              </>
            )}

            {error && <div className="rounded border border-negative bg-negative-soft p-3 text-body-sm text-negative">{error}</div>}

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
              <button type="button" className="btn-ghost" disabled={step === 0} onClick={() => setStep(step - 1)}>
                ← {t('Back')}
              </button>
              {step < STEPS.length - 1 ? (
                <button type="button" className="btn-primary" onClick={() => setStep(step + 1)}>
                  {t('Next')} →
                </button>
              ) : (
                <button type="button" className="btn-primary" disabled={!valid || busy} onClick={submit}>
                  {busy ? t('Going live…') : t('Go live')}
                </button>
              )}
            </div>
          </div>
        </section>

        {/* ---------------- live preview */}
        <aside className="flex flex-col gap-work lg:sticky lg:top-4 lg:self-start">
          <section className="panel overflow-hidden">
            <header className="panel-head">
              <h2 className="text-panel">{t('Connector manifest')}</h2>
              <span className="font-mono text-meta text-muted">partners/{String(manifest.partner_id)}.json</span>
            </header>
            <pre className="max-h-[440px] overflow-auto bg-rail p-4 font-mono text-meta leading-relaxed text-rail-text-active">{json}</pre>
          </section>
          <section className="panel overflow-hidden">
            <header className="panel-head">
              <h2 className="text-panel">{t('Spec check')}</h2>
              {checks && <Chip tone={checks.every((c) => c.ok) ? 'positive' : 'warning'}>{t('{n}/{m} passed', { n: checks.filter((c) => c.ok).length, m: checks.length })}</Chip>}
            </header>
            {checks === null ? (
              <div className="px-5 py-4 text-body-sm text-muted">{t('Checking')}…</div>
            ) : (
              <ul className="divide-y divide-line">
                {checks.map((c, i) => (
                  <li key={`${c.id}-${i}`} className="flex items-start gap-2.5 px-5 py-2 text-body-sm">
                    <span className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-meta font-bold ${c.ok ? 'bg-positive-soft text-positive' : 'bg-warning-soft text-warning'}`}>
                      {c.ok ? <Icon name="check" className="h-3 w-3" /> : '!'}
                    </span>
                    <span className="min-w-0">
                      <span className="mr-1.5 font-mono text-meta text-muted">{c.id}</span>
                      <span className={c.ok ? 'text-ink' : 'text-warning'}>{c.message}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </div>
    </div>
  )
}

function Live({ result, onAgain }: { result: OnboardResult; onAgain: () => void }) {
  useCrumbs([{ label: t('Partners'), to: '/staff/partners' }, { label: result.name }])
  return (
    <div className="mx-auto flex w-full max-w-[720px] flex-col gap-work">
      <section className="panel animate-rise overflow-hidden">
        <div className="flex flex-col items-center gap-3 px-6 py-8 text-center">
          <Mascot pose="thumbs-up" className="h-28 w-28" />
          <Chip tone="positive">{t('Live')}</Chip>
          <h1 className="text-page">{t('{name} is live', { name: shortName(result.name) })}</h1>
          <p className="max-w-[520px] text-body text-secondary">
            {t('The manifest passed every spec check. Debye will rank {name} for the next matching case, no code change needed.', { name: shortName(result.name) })}
          </p>
          <div className="mt-2 flex flex-wrap justify-center gap-3">
            <Link to={result.portal_url} className="btn-primary">
              <Icon name="jobs" className="h-4 w-4" /> {t('Open partner portal')}
            </Link>
            {result.technicians.map((x) => (
              <Link key={x.tech_id} to={x.url} className="btn-secondary">
                <Icon name="phone" className="h-4 w-4" /> {t('Open as {name}', { name: x.name.split(' ')[0] })}
              </Link>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3 text-body-sm">
          <span className="text-muted">
            {result.file ? (
              <>
                {t('Saved as')} <span className="font-mono text-ink">{result.file}</span>
              </>
            ) : (
              t('Saved')
            )}
          </span>
          <div className="flex gap-2">
            <button type="button" className="btn-ghost" onClick={onAgain}>
              {t('Onboard another')}
            </button>
            <Link to="/staff/partners" className="btn-secondary">
              {t('See all partners')}
            </Link>
          </div>
        </div>
      </section>
    </div>
  )
}
