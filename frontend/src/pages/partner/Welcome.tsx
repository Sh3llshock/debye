// v3 partner portal: Welcome (landing), Log in (demo), Register your company (6 steps).
// Register keeps the real onboarding backend: POST /api/partners/onboard(/validate).
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { OnboardCheck, OnboardDocument, OnboardResult, PartnerProfile } from '../../api/types'
import { LangToggle, Logo } from '../../components/Layout'
import { t } from '../../lib/i18n'
import { CheckPill, saveLocalProfile, setSession } from './shared'

// ---------------------------------------------------------------- layout: side panel + main

function Side({ children }: { children?: ReactNode }) {
  return (
    <aside className="flex flex-col gap-[22px] border-b border-line bg-surface px-5 py-6 text-secondary md:border-b-0 md:border-r md:px-8 md:py-10">
      <Link to="/partner" className="flex items-center gap-[9px] text-[17px] font-semibold tracking-[-0.02em] text-ink">
        <Logo />
        Debye {t('partners')}
      </Link>
      <h1 className="text-[24px] font-bold leading-[1.15] text-ink md:text-page md:leading-[1.15]">{t('Get repair jobs from thousands of rented homes. No sales, no paperwork.')}</h1>
      <ul className="m-0 hidden list-none flex-col gap-3 p-0 leading-[1.45] sm:flex">
        <li className="flex gap-2.5">
          🔧 <span><b className="font-semibold text-ink">{t('Jobs that fit you.')}</b> {t('Only your trades, brands and area.')}</span>
        </li>
        <li className="flex gap-2.5">
          📸 <span><b className="font-semibold text-ink">{t('Everything up front.')}</b> {t('Photos, error codes, access, an approved budget.')}</span>
        </li>
        <li className="flex gap-2.5">
          💶 <span><b className="font-semibold text-ink">{t('Paid in 14 days.')}</b> {t('Send a photo of the invoice; we do the rest.')}</span>
        </li>
      </ul>
      {children}
    </aside>
  )
}

function RegShell({ side, children, wide }: { side?: ReactNode; children: ReactNode; wide?: boolean }) {
  return (
    <div className="grid min-h-[100dvh] grid-cols-1 bg-bg md:grid-cols-[300px_minmax(0,1fr)] lg:grid-cols-[360px_minmax(0,1fr)]">
      <Side>{side}</Side>
      <div className={`relative min-w-0 px-4 pb-16 pt-8 md:px-10 md:pt-10 lg:px-14 ${wide ? 'max-w-[980px]' : 'max-w-[760px]'}`}>
        <div className="absolute right-4 top-4 md:right-6 md:top-6">
          <LangToggle />
        </div>
        {children}
      </div>
    </div>
  )
}

function Eyebrow({ children }: { children: ReactNode }) {
  return <div className="text-label font-semibold text-wine">{children}</div>
}
function H2({ children }: { children: ReactNode }) {
  return <h2 className="mb-2 mt-1 text-[28px] font-bold leading-tight md:text-[34px]">{children}</h2>
}
function Lead({ children }: { children: ReactNode }) {
  return <p className="mb-[26px] mt-0 text-[15px] leading-[1.5] text-secondary">{children}</p>
}

// ---------------------------------------------------------------- welcome

export function PartnerWelcome() {
  return (
    <RegShell>
      <div className="max-w-[660px] pt-6 md:pt-0">
        <Eyebrow>{t('Debye partner portal')}</Eyebrow>
        <H2>{t('Welcome')}</H2>
        <Lead>{t('Heating and plumbing companies get repair jobs from reltix properties, with the diagnosis, photos and an approved budget already done.')}</Lead>
        <div className="flex flex-wrap gap-2.5">
          <Link to="/partner/register" className="btn-primary">
            {t('Register your company')}
          </Link>
          <Link to="/partner/login" className="btn-secondary">
            {t('Log in')}
          </Link>
        </div>
      </div>
    </RegShell>
  )
}

// ---------------------------------------------------------------- login (demo: any password)

/** Demo accounts from our seed (partners/*.json, data/seed.json). Technicians land on their phone page. */
const DEMO_LOGINS: { who: string; email?: string; phone?: string; to: string; pid: string }[] = [
  { who: 'Tom Schmidt · Heizung Schmidt', email: 'jobs@heizung-schmidt.example', phone: '+49 000 000 0003', to: '/partner/heizung-schmidt', pid: 'heizung-schmidt' },
  { who: 'Ali Yilmaz · Heizung Schmidt (technician)', phone: '+49 000 000 0005', to: '/tech/tech_ali', pid: 'heizung-schmidt' },
  { who: 'Elektro Klein', email: 'jobs@elektro-klein.example', to: '/partner/elektro-klein', pid: 'elektro-klein' },
  { who: 'Marco Klein · Elektro Klein (technician)', phone: '+49 000 000 0006', to: '/tech/tech_marco', pid: 'elektro-klein' },
  { who: 'Heiztechnik Grün', email: 'jobs@heiztechnik-gruen.example', to: '/partner/heiztechnik-gruen', pid: 'heiztechnik-gruen' },
  { who: 'Wärme Wagner', phone: '+49 000 000 0004', to: '/partner/waerme-wagner', pid: 'waerme-wagner' },
]
const digits = (s: string) => s.replace(/\D/g, '').replace(/^00/, '')

/** Find a partner by email/phone: the demo list first, then the live partner list (transport addresses). */
async function findLogin(raw: string): Promise<{ to: string; pid: string } | null> {
  const q = raw.trim().toLowerCase()
  if (!q) return null
  const d = digits(q)
  const hit = DEMO_LOGINS.find((x) => x.email === q || (d.length >= 6 && x.phone && digits(x.phone) === d))
  if (hit) return hit
  let partners: PartnerProfile[] = []
  try {
    partners = await api.partners()
  } catch {
    return null
  }
  for (const p of partners) {
    const tr = (p.transport ?? {}) as { address?: string; notify?: { address?: string } }
    const addrs = [tr.address, tr.notify?.address].filter(Boolean).map((a) => String(a).toLowerCase())
    if (addrs.some((a) => a === q || (d.length >= 6 && digits(a) === d)) || p.partner_id === q) return { to: `/partner/${p.partner_id}`, pid: p.partner_id }
  }
  return null
}

export function PartnerLogin() {
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [pass, setPass] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    setErr('')
    if (!email.trim()) return setErr(t('Enter your email address or mobile number.'))
    if (!pass) return setErr(t('Enter your password.'))
    setBusy(true)
    const hit = await findLogin(email)
    setBusy(false)
    if (!hit) return setErr(t('No partner account with this email or number.'))
    setSession({ pid: hit.pid })
    nav(hit.to)
  }
  return (
    <RegShell>
      <form
        className="max-w-[660px] pt-6 md:pt-0"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <Eyebrow>{t('Log in')}</Eyebrow>
        <H2>{t('Welcome back')}</H2>
        <Lead>{t('Use the email address or mobile number you registered with.')}</Lead>
        <div className="grid max-w-[420px] grid-cols-1 gap-4">
          <F label={t('Email or mobile')} id="lemail">
            <input id="lemail" className="field" type="text" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.de" autoComplete="username" />
          </F>
          <F label={t('Password')} id="lpass">
            <input id="lpass" className="field" type="password" value={pass} onChange={(e) => setPass(e.target.value)} autoComplete="current-password" />
          </F>
        </div>
        {err && <p className="mb-0 mt-3 font-medium text-red">{err}</p>}
        <div className="mt-[30px] flex max-w-[420px] items-center justify-between border-t border-line pt-5">
          <Link to="/partner" className="btn-ghost">
            ← {t('Back')}
          </Link>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? t('Logging in…') : t('Log in')}
          </button>
        </div>
        <p className="mt-[18px] text-muted">
          {t('No account yet?')}{' '}
          <Link to="/partner/register" className="text-wine">
            {t('Register your company')}
          </Link>
        </p>
        <div className="mt-6 max-w-[420px] rounded-tile bg-beige/60 p-4 text-label text-secondary shadow-ring">
          <b className="text-ink">{t('Demo logins')}</b> · {t('any password works')}
          <ul className="mt-2 flex flex-col gap-1">
            {DEMO_LOGINS.map((x) => (
              <li key={x.who}>
                <button
                  type="button"
                  className="text-left hover:text-wine"
                  onClick={() => {
                    setEmail(x.email ?? x.phone ?? '')
                    setPass('demo')
                  }}
                >
                  <span className="font-medium text-ink">{x.email ?? x.phone}</span> · {x.who}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </form>
    </RegShell>
  )
}

// ---------------------------------------------------------------- register

const TRADES: [string, string, string][] = [
  // [mockup key, label, our trade]
  ['gas_boiler', 'Gas boilers', 'heating'],
  ['oil_boiler', 'Oil boilers', 'heating'],
  ['heat_pump', 'Heat pumps', 'heating'],
  ['plumbing', 'Plumbing', 'plumbing'],
  ['shower_bath', 'Showers & bathrooms', 'plumbing'],
  ['water_heater_electric', 'Electric water heaters', 'electrical'],
  ['drain', 'Drain cleaning', 'plumbing'],
  ['radiators', 'Radiators & valves', 'heating'],
]
const BRANDS = ['Vaillant', 'Buderus', 'Viessmann', 'Wolf', 'Bosch', 'Stiebel Eltron', 'Grohe', 'Hansgrohe']
const DOCS: [string, string][] = [
  ['doc_hwk', 'Handwerkskarte (trade register card)'],
  ['doc_ins', 'Liability insurance certificate'],
  ['doc_gas', 'Gas installer registration'],
  ['doc_vat', 'VAT registration certificate'],
]
type TeamRow = { name: string; phone: string; qual: string }
export type Profile = {
  [k: string]: string | boolean | string[] | TeamRow[] | Record<string, string>
  docs: Record<string, string>
  trades: string[]
  brands: string[]
  team: TeamRow[]
}
export const EMPTY_PROFILE: Profile = {
  company_name: '', legal_form: '', street: '', postcode: '', city: '', register: '', vat_id: '', tax_no: '',
  contact_name: '', contact_role: '', email: '', mobile: '', phone_office: '', website: '',
  hwk_chamber: '', hwk_no: '', master: '', gas_operator: '', gas_no: '', gas_valid: '', insurer: '', policy_no: '', coverage_eur: '', ins_valid: '',
  docs: {}, trades: [], brands: [], base_postcode: '', radius_km: '', postcodes: '', emergency: 'No', max_jobs: '',
  callout_eur: '', hourly_eur: '', weekend_pct: '', night_pct: '', response: '', hours_week: '', hours_sat: '', jobs_via: 'WhatsApp', calendar_url: '',
  team: [{ name: '', phone: '', qual: '' }], account_holder: '', iban: '', bic: '', invoice_format: 'PDF',
  ag_terms: false, ag_dpa: false, ag_wa: false, ag_true: false,
}
/** Our own demo company (fills every step; not a seeded partner, so it can go live). */
const DEMO_PROFILE: Profile = {
  ...EMPTY_PROFILE,
  company_name: 'Heizung Müller GmbH', legal_form: 'GmbH', street: 'Jülicher Str. 120', postcode: '52070', city: 'Aachen',
  register: 'Amtsgericht Aachen, HRB 12345', vat_id: 'DE123456789', tax_no: '201/1234/5678',
  contact_name: 'Jonas Müller', contact_role: 'Managing director, master installer', email: 'jonas@heizung-mueller.example', mobile: '+49 000 000 0199', phone_office: '+49 241 000 0199', website: 'heizung-mueller.example',
  hwk_chamber: 'Handwerkskammer Aachen', hwk_no: 'HWK-AC 12345', master: 'Yes · Meisterbetrieb', gas_operator: 'Local gas network operator, Aachen', gas_no: 'IV-AC-1234', gas_valid: '2028-12-31',
  insurer: 'Example Versicherung AG', policy_no: 'BHV-1234-56', coverage_eur: '5000000', ins_valid: '2027-06-30',
  docs: { doc_hwk: 'handwerkskarte.pdf', doc_ins: 'insurance_2026.pdf', doc_gas: 'gas_registry.pdf', doc_vat: 'ust_bescheinigung.pdf' },
  trades: ['gas_boiler', 'plumbing', 'radiators'], brands: ['Vaillant', 'Buderus'],
  base_postcode: '52062', radius_km: '15', postcodes: '', emergency: 'Yes', max_jobs: '6',
  callout_eur: '85', hourly_eur: '70', weekend_pct: '25', night_pct: '50', response: 'Within 24 hours', hours_week: '07:00–17:00', hours_sat: '08:00–13:00', jobs_via: 'WhatsApp',
  team: [
    { name: 'Jonas Müller', phone: '+49 000 000 0199', qual: 'Master installer, gas registered' },
    { name: 'Eva Krämer', phone: '+49 000 000 0198', qual: 'Journeyman, plumbing' },
  ],
  account_holder: 'Heizung Müller GmbH', iban: 'DE00 0000 0000 0000 0000 00', bic: 'XXXXDEXXXXX', invoice_format: 'PDF',
  ag_terms: true, ag_dpa: true, ag_wa: true, ag_true: true,
}

type FieldDef = { sec?: string; custom?: 'docs' | 'trades' | 'brands' | 'team' | 'agree'; k?: string; l?: string; req?: boolean; type?: string; opts?: string[]; ph?: string; hint?: string; full?: boolean }
export const STEPS: { t: string; lead: string; fields: FieldDef[] }[] = [
  {
    t: 'Company & contact',
    lead: 'Who you are and how we reach you. We check your VAT ID and trade register automatically.',
    fields: [
      { sec: 'Company' },
      { k: 'company_name', l: 'Company name', req: true },
      { k: 'legal_form', l: 'Legal form', type: 'select', opts: ['', 'GmbH', 'UG', 'GbR', 'e.K.', 'Einzelunternehmen', 'GmbH & Co. KG'], req: true },
      { k: 'street', l: 'Street and number', req: true },
      { k: 'postcode', l: 'Postcode', req: true },
      { k: 'city', l: 'City', req: true },
      { k: 'register', l: 'Trade register', ph: 'Amtsgericht …, HRB …', hint: 'Not needed for sole traders' },
      { k: 'vat_id', l: 'VAT ID (USt-IdNr.)', ph: 'DE…', req: true },
      { k: 'tax_no', l: 'Tax number' },
      { sec: 'Main contact' },
      { k: 'contact_name', l: 'Full name', req: true },
      { k: 'contact_role', l: 'Role' },
      { k: 'email', l: 'Email', type: 'email', req: true },
      { k: 'mobile', l: 'Mobile (jobs arrive here on WhatsApp)', type: 'tel', req: true },
      { k: 'phone_office', l: 'Office phone', type: 'tel' },
      { k: 'website', l: 'Website' },
    ],
  },
  {
    t: 'Licences & insurance',
    lead: 'Gas work in Germany needs a master business and a registration with the gas network operator. Upload proof once; we remind you before anything expires.',
    fields: [
      { sec: 'Trade licence' },
      { k: 'hwk_chamber', l: 'Chamber of crafts', ph: 'Handwerkskammer …', req: true },
      { k: 'hwk_no', l: 'Handwerksrolle number', req: true },
      { k: 'master', l: 'Master business (Meisterbetrieb)?', type: 'select', opts: ['', 'Yes · Meisterbetrieb', 'No'], req: true },
      { sec: 'Gas installer registration (only for gas work)' },
      { k: 'gas_operator', l: 'Registered with (network operator)' },
      { k: 'gas_no', l: 'Registration number' },
      { k: 'gas_valid', l: 'Valid until', type: 'date' },
      { sec: 'Business liability insurance' },
      { k: 'insurer', l: 'Insurer', req: true },
      { k: 'policy_no', l: 'Policy number', req: true },
      { k: 'coverage_eur', l: 'Coverage (€)', type: 'number', req: true },
      { k: 'ins_valid', l: 'Valid until', type: 'date', req: true },
      { sec: 'Documents' },
      { custom: 'docs' },
    ],
  },
  {
    t: 'Services & area',
    lead: 'This decides which jobs you see. We only send you jobs you’re qualified for, in your area.',
    fields: [
      { sec: 'Services you offer' },
      { custom: 'trades' },
      { sec: 'Brands you’re certified or trained for' },
      { custom: 'brands' },
      { sec: 'Service area' },
      { k: 'base_postcode', l: 'Base postcode', req: true },
      { k: 'radius_km', l: 'Radius (km)', type: 'number', req: true },
      { k: 'postcodes', l: 'Or exact postcodes', ph: '52062, 52064, …', full: true },
      { k: 'emergency', l: 'Emergency service 24/7?', type: 'select', opts: ['No', 'Yes'] },
      { k: 'max_jobs', l: 'Max. Debye jobs per day', type: 'number' },
    ],
  },
  {
    t: 'Rates & hours',
    lead: 'Used to estimate costs before a job is approved. You can change them any time.',
    fields: [
      { sec: 'Rates (net, €)' },
      { k: 'callout_eur', l: 'Callout fee (€)', type: 'number', req: true },
      { k: 'hourly_eur', l: 'Hourly rate (€)', type: 'number', req: true },
      { k: 'weekend_pct', l: 'Weekend surcharge (%)', type: 'number' },
      { k: 'night_pct', l: 'Night / emergency surcharge (%)', type: 'number' },
      { sec: 'Availability' },
      { k: 'response', l: 'Typical response time', type: 'select', opts: ['', 'Same day', 'Within 24 hours', 'Within 48 hours', 'Within a week'], req: true },
      { k: 'hours_week', l: 'Working hours Mon–Fri', ph: '07:00–17:00' },
      { k: 'hours_sat', l: 'Working hours Saturday', ph: '08:00–13:00 or closed' },
      { sec: 'How you get jobs' },
      { k: 'jobs_via', l: 'Send new jobs via', type: 'select', opts: ['WhatsApp', 'Email', 'Portal only'] },
      { k: 'calendar_url', l: 'Calendar link (optional)', ph: 'Google / Outlook / iCal URL', hint: 'Lets us offer your free slots without asking you' },
    ],
  },
  {
    t: 'Team, payout & agreements',
    lead: 'Who does the work, where we pay you, and the agreements that let us share tenant data with you.',
    fields: [
      { sec: 'Technicians' },
      { custom: 'team' },
      { sec: 'Payout' },
      { k: 'account_holder', l: 'Account holder', req: true },
      { k: 'iban', l: 'IBAN', req: true },
      { k: 'bic', l: 'BIC' },
      { k: 'invoice_format', l: 'Invoice format', type: 'select', opts: ['PDF', 'ZUGFeRD (PDF + XML)', 'XRechnung'], hint: 'Payment 14 days after the invoice is approved' },
      { sec: 'Agreements' },
      { custom: 'agree' },
    ],
  },
]
const AGREE: [string, string, string][] = [
  ['ag_terms', 'I accept the', 'Debye partner terms (job acceptance within 2 h, cost caps, 14-day payment).'],
  ['ag_dpa', 'I sign the', 'data processing agreement (GDPR Art. 28): tenant data is used only for the job and deleted 30 days after it closes.'],
  ['ag_wa', 'Send me jobs and reminders on', 'WhatsApp at the mobile number above.'],
  ['ag_true', '', 'The information and documents I’ve given are correct and up to date.'],
]

function F({ label, id, req, hint, full, children, bad }: { label: string; id?: string; req?: boolean; hint?: string; full?: boolean; children: ReactNode; bad?: boolean }) {
  return (
    <div className={`flex min-w-0 flex-col gap-1.5 ${full ? 'sm:col-span-2' : ''} ${bad ? '[&_input]:shadow-[0_0_0_1.5px_#C0262D]' : ''}`}>
      <label htmlFor={id} className="text-label font-medium text-secondary">
        {label}
        {req && <span className="text-red"> *</span>}
      </label>
      {children}
      {hint && <small className="text-meta text-muted">{hint}</small>}
    </div>
  )
}

function Sec({ children, first }: { children: ReactNode; first?: boolean }) {
  return <div className={`text-[17px] font-semibold tracking-[-0.02em] sm:col-span-2 ${first ? '' : 'mt-3 border-t border-line pt-4'}`}>{children}</div>
}

/** One form field from the step definition (also used read/write on the Profile tab). */
export function ProfileField({ f, p, set, errors, first }: { f: FieldDef; p: Profile; set: (patch: Partial<Profile>) => void; errors: string[]; first?: boolean }) {
  if (f.sec) return <Sec first={first}>{t(f.sec)}</Sec>
  if (f.custom === 'docs')
    return (
      <div className="flex flex-col gap-2 sm:col-span-2">
        {DOCS.map(([k, l]) =>
          p.docs[k] ? (
            <div key={k} className="flex items-center justify-between gap-3 rounded-[12px] bg-ok-tint px-3.5 py-3">
              <span className="min-w-0">
                ✓ <b>{t(l)}</b> · {p.docs[k]}
              </span>
              <button type="button" className="btn-ghost min-h-0 px-3 py-1.5 text-label" onClick={() => set({ docs: Object.fromEntries(Object.entries(p.docs).filter(([x]) => x !== k)) })}>
                {t('Replace')}
              </button>
            </div>
          ) : (
            <label key={k} className="flex cursor-pointer items-center justify-between gap-3 rounded-[12px] border-[1.5px] border-dashed border-black/15 bg-surface px-3.5 py-3">
              <span className="min-w-0">
                <b>{t(l)}</b> <span className="text-muted">{t('PDF or photo')}</span>
              </span>
              <span className="btn-secondary min-h-0 px-3 py-1.5 text-label">{t('Upload')}</span>
              <input type="file" accept="image/*,.pdf" className="sr-only" onChange={(e) => e.target.files?.[0] && set({ docs: { ...p.docs, [k]: e.target.files[0].name } })} />
            </label>
          ),
        )}
      </div>
    )
  if (f.custom === 'trades' || f.custom === 'brands') {
    const key = f.custom
    const items: [string, string][] = key === 'trades' ? TRADES.map(([k, l]) => [k, t(l)]) : BRANDS.map((b) => [b, b])
    return (
      <div className="flex flex-col gap-1.5 sm:col-span-2">
        <div className="flex flex-wrap gap-2">
          {items.map(([k, l]) => (
            <CheckPill key={k} on={p[key].includes(k)} onClick={() => set({ [key]: p[key].includes(k) ? p[key].filter((x) => x !== k) : [...p[key], k] } as Partial<Profile>)}>
              {l}
            </CheckPill>
          ))}
        </div>
        {key === 'trades' && errors.includes('trades') && <small className="font-medium text-red">{t('Pick at least one service')}</small>}
      </div>
    )
  }
  if (f.custom === 'team')
    return (
      <div className="flex flex-col gap-2.5 sm:col-span-2">
        {p.team.map((x, i) => {
          const setRow = (patch: Partial<TeamRow>) => set({ team: p.team.map((r, j) => (j === i ? { ...r, ...patch } : r)) })
          return (
            <div key={i} className="grid grid-cols-1 items-end gap-2.5 sm:grid-cols-[1.2fr_1fr_1.4fr_auto]">
              <F label={t('Name')}>
                <input className="field" value={x.name} onChange={(e) => setRow({ name: e.target.value })} aria-label={t('Technician name')} />
              </F>
              <F label={t('Mobile')}>
                <input className="field" value={x.phone} onChange={(e) => setRow({ phone: e.target.value })} />
              </F>
              <F label={t('Qualification')}>
                <input className="field" value={x.qual} onChange={(e) => setRow({ qual: e.target.value })} placeholder={t('e.g. journeyman, gas registered')} />
              </F>
              <button type="button" className="btn-ghost min-h-0 px-3 py-1.5 text-label" disabled={p.team.length < 2} onClick={() => set({ team: p.team.filter((_, j) => j !== i) })}>
                {t('Remove')}
              </button>
            </div>
          )
        })}
        <div>
          <button type="button" className="btn-secondary min-h-0 px-3 py-1.5 text-label" onClick={() => set({ team: [...p.team, { name: '', phone: '', qual: '' }] })}>
            + {t('Add technician')}
          </button>
        </div>
      </div>
    )
  if (f.custom === 'agree')
    return (
      <div className="flex flex-col gap-2 sm:col-span-2">
        {AGREE.map(([k, a, b]) => (
          <label key={k} className="flex cursor-pointer items-start gap-3 rounded-[12px] bg-surface px-[15px] py-[13px] leading-[1.45] shadow-ring">
            <input type="checkbox" className="mt-0.5 h-[18px] w-[18px] accent-wine" checked={!!p[k]} onChange={(e) => set({ [k]: e.target.checked })} />
            <span>
              {a && `${t(a)} `}
              {t(b)}
            </span>
          </label>
        ))}
        {errors.some((e) => e.startsWith('ag_')) && <small className="font-medium text-red">{t('Please accept all four to continue')}</small>}
      </div>
    )
  const k = f.k!
  const v = String(p[k] ?? '')
  const id = `f_${k}`
  return (
    <F label={t(f.l!)} id={id} req={f.req} hint={f.hint ? t(f.hint) : undefined} full={f.full} bad={errors.includes(k)}>
      {f.type === 'select' ? (
        <select id={id} className="field" value={v} onChange={(e) => set({ [k]: e.target.value })}>
          {f.opts!.map((o) => (
            <option key={o} value={o}>
              {o ? t(o) : t('Choose…')}
            </option>
          ))}
        </select>
      ) : (
        <input id={id} className="field" type={f.type ?? 'text'} value={v} placeholder={f.ph} onChange={(e) => set({ [k]: e.target.value })} />
      )}
    </F>
  )
}

function validateStep(i: number, p: Profile): string[] {
  const errs: string[] = []
  STEPS[i].fields.forEach((f) => f.req && f.k && !String(p[f.k] ?? '').trim() && errs.push(f.k))
  if (i === 2 && !p.trades.length) errs.push('trades')
  if (i === 4) ['ag_terms', 'ag_dpa', 'ag_wa', 'ag_true'].forEach((k) => !p[k] && errs.push(k))
  return errs
}

function slugify(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/ä/g, 'ae')
      .replace(/ö/g, 'oe')
      .replace(/ü/g, 'ue')
      .replace(/ß/g, 'ss')
      .replace(/\b(gmbh|ag|kg|ug|ohg|gbr|e\.?k\.?|co)\b/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 40) || 'partner'
  )
}
const toE164 = (s: string) => {
  const d = s.replace(/[^\d+]/g, '')
  return d.startsWith('+') ? d : d.startsWith('00') ? `+${d.slice(2)}` : d.startsWith('0') ? `+49${d.slice(1)}` : d ? `+${d}` : ''
}

/** Registration form → connector manifest (docs/connector-spec.md §2), same shape the old /partners/join built. */
function buildManifest(p: Profile): Record<string, unknown> {
  const id = slugify(String(p.company_name))
  const trades = [...new Set(p.trades.map((k) => TRADES.find((x) => x[0] === k)?.[2] ?? 'heating'))]
  const primary = trades[0] ?? 'heating'
  const heatingOnly = trades.length === 1 && primary === 'heating'
  const postcodes = String(p.postcodes).split(/[\s,;]+/).filter(Boolean)
  const via = String(p.jobs_via)
  const notify = via === 'WhatsApp' && p.mobile ? { channel: 'whatsapp', address: toE164(String(p.mobile)) } : p.email ? { channel: 'email', address: String(p.email).trim() } : undefined
  const hours = { 'Same day': 8, 'Within 24 hours': 24, 'Within 48 hours': 48, 'Within a week': 168 }[String(p.response)] ?? 24
  return {
    partner_id: id,
    name: String(p.company_name).trim(),
    category: `repair.${primary}`,
    kind: 'deliver',
    triggers: trades.map((tr) => `case.repair.${tr}`),
    service_area: postcodes.length ? { postcodes } : { base_postcode: String(p.base_postcode).trim(), radius_km: Number(p.radius_km) || 15 },
    capabilities: { trades, brands_certified: p.brands },
    eligibility: [...(heatingOnly ? [{ field: 'asset.type', op: 'in', value: ['gas_boiler', 'heat_pump'] }] : []), { field: 'property.postcode', op: 'in_service_area' }],
    pricing: { model: 'framework_agreement', callout_fee_eur: Number(p.callout_eur) || 0, hourly_eur: Number(p.hourly_eur) || 0 },
    required_context: [
      { key: 'address', source: 'property.address', pii: true, consent_required: true },
      { key: 'unit_floor', source: 'unit.floor', pii: false, consent_required: false },
      { key: 'asset', source: 'asset', pii: false, consent_required: false },
      { key: 'error_code', source: 'case.error_code', pii: false, consent_required: false },
      { key: 'tenant_name', source: 'tenant.name', pii: true, consent_required: true },
      { key: 'tenant_phone', source: 'tenant.phone', pii: true, consent_required: true },
      { key: 'photos', source: 'case.documents[kind=photo]', pii: true, consent_required: true },
    ],
    availability: p.calendar_url ? { mode: 'static', hours: String(p.hours_week || 'calendar link') } : { mode: 'conversational' },
    transport: { type: 'portal', url: `/partner/${id}`, ...(notify ? { notify } : {}) },
    status_events: ['accepted', 'declined', 'scheduled', 'in_progress', 'completed', 'invoiced'],
    documents_returned: ['visit_report', 'invoice'],
    sla: { urgent_response_hours: Math.min(hours, 8), standard_response_hours: Math.max(hours, 24) },
  }
}

/** The uploaded documents with their numbers and dates, for the staff review (feature 1). */
function onboardDocuments(p: Profile): OnboardDocument[] {
  const company = String(p.company_name).trim()
  const out: OnboardDocument[] = []
  const add = (doc_type: OnboardDocument['doc_type'], key: string, extra: Partial<OnboardDocument>) => {
    const filename = p.docs[key]
    const given = Object.values(extra).some((v) => v !== undefined && v !== '')
    if (filename || given) out.push({ doc_type, filename: filename ?? '', company_name: company, ...extra })
  }
  add('trade_licence', 'doc_hwk', { number: String(p.hwk_no || '') || undefined, issuer: String(p.hwk_chamber || '') || undefined })
  add('insurance', 'doc_ins', { number: String(p.policy_no || '') || undefined, issuer: String(p.insurer || '') || undefined, valid_until: String(p.ins_valid || '') || undefined, coverage_eur: Number(p.coverage_eur) || undefined })
  if (p.gas_no || p.docs.doc_gas) add('gas_registry', 'doc_gas', { number: String(p.gas_no || '') || undefined, issuer: String(p.gas_operator || '') || undefined, valid_until: String(p.gas_valid || '') || undefined })
  add('vat', 'doc_vat', { number: String(p.vat_id || '') || undefined })
  return out
}

/** Format checks we can do here (the mockup's VIES / register lookups are not real services). */
function localChecks(p: Profile): { label: string; ok: boolean; pill: string }[] {
  const vatOk = /^DE\d{9}$/.test(String(p.vat_id).replace(/\s/g, ''))
  const ibanOk = /^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$/.test(String(p.iban).replace(/\s/g, ''))
  return [
    { label: `${t('VAT ID')} ${p.vat_id}`, ok: vatOk, pill: vatOk ? t('Format OK') : t('Check the format') },
    { label: `${t('Handwerksrolle')} ${p.hwk_no} · ${p.hwk_chamber}`, ok: !!p.hwk_no, pill: t('Given') },
    { label: `${t('Gas installer registration')} ${p.gas_no || '–'}`, ok: !!p.gas_no, pill: p.gas_no ? t('Valid until {d}', { d: String(p.gas_valid || '–') }) : t('Not given · no gas jobs') },
    { label: `${t('Liability insurance')} ${p.policy_no} · ${Number(p.coverage_eur || 0).toLocaleString('de-DE')} €`, ok: !!p.policy_no, pill: t('Valid until {d}', { d: String(p.ins_valid || '–') }) },
    { label: `IBAN ${p.iban}`, ok: ibanOk, pill: ibanOk ? t('Format OK') : t('Check the format') },
  ]
}

export function PartnerRegister() {
  const [p, setP] = useState<Profile>(EMPTY_PROFILE)
  const [step, setStep] = useState(0)
  const [review, setReview] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const [checks, setChecks] = useState<OnboardCheck[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState<OnboardResult | null>(null)
  const set = (patch: Partial<Profile>) => {
    setP((x) => ({ ...x, ...patch }) as Profile)
    setErrors((e) => e.filter((k) => !(k in patch)))
  }
  const manifest = useMemo(() => buildManifest(p), [p])

  // Verification step: run the backend's connector-spec validator (same code that guards POST).
  useEffect(() => {
    if (!review) return
    let alive = true
    setChecks(null)
    api
      .onboardValidate(manifest)
      .then((r) => alive && setChecks(r.checks))
      .catch(() => alive && setChecks([]))
    return () => {
      alive = false
    }
  }, [review, manifest])

  const next = () => {
    const e = validateStep(step, p)
    setErrors(e)
    if (e.length) return
    if (step < STEPS.length - 1) setStep(step + 1)
    else setReview(true)
    window.scrollTo(0, 0)
  }
  const back = () => {
    setErrors([])
    if (review) setReview(false)
    else if (step > 0) setStep(step - 1)
  }
  const goLive = async () => {
    setBusy(true)
    setErr(null)
    try {
      const techs = p.team.filter((x) => x.name.trim()).map((x) => ({ name: x.name.trim(), skills: [...new Set([...p.trades.map((k) => TRADES.find((y) => y[0] === k)?.[2] ?? 'heating'), ...p.brands])], ...(x.phone ? { phone_e164: toE164(x.phone) } : {}) }))
      const r = await api.onboard(manifest, techs as { name: string; skills: string[] }[], onboardDocuments(p), {
        name: String(p.company_name).trim(),
        street: String(p.street),
        postcode: String(p.postcode),
        city: String(p.city),
        vat_id: String(p.vat_id),
      })
      saveLocalProfile(r.partner_id, p as unknown as Record<string, unknown>)
      setSession({ pid: r.partner_id, name: r.name })
      setDone(r)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const sideSteps = (
    <>
      <ol className="m-0 mt-2 flex list-none flex-col gap-0.5 rounded-tile bg-bg p-1">
        {STEPS.map((s, i) => {
          const isOn = i === step && !review && !done
          const isDone = i < step || review || !!done
          return (
            <li key={s.t} className={`flex items-center gap-2.5 rounded-[10px] px-2.5 py-[9px] font-medium ${isOn ? 'bg-surface text-ink shadow-[0_1px_3px_rgba(0,0,0,.08)]' : isDone ? 'text-ink' : 'text-muted'}`}>
              <StepDot n={i + 1} on={isOn} done={isDone} />
              {t(s.t)}
            </li>
          )
        })}
        <li className={`flex items-center gap-2.5 rounded-[10px] px-2.5 py-[9px] font-medium ${review && !done ? 'bg-surface text-ink shadow-[0_1px_3px_rgba(0,0,0,.08)]' : done ? 'text-ink' : 'text-muted'}`}>
          <StepDot n={6} on={review && !done} done={!!done} />
          {t('Verification')}
        </li>
      </ol>
      <p className="m-0 text-muted">
        {t('Already registered?')}{' '}
        <Link to="/partner/login" className="text-wine">
          {t('Log in')}
        </Link>
      </p>
    </>
  )

  if (done) {
    return (
      <RegShell side={sideSteps}>
        <div className="max-w-[660px] pt-6 md:pt-0">
          <Eyebrow>{t('Step 6 of 6')}</Eyebrow>
          <H2>{done.status === 'pending_review' ? t('{name} is registered', { name: done.name }) : t('{name} is live', { name: done.name })}</H2>
          <Lead>{done.status === 'pending_review' ? t('reltix checks your documents first. You get jobs as soon as a property manager approves you.') : t('Your details passed every check. Debye ranks you for the next matching case.')}</Lead>
          <ul className="my-5 list-none overflow-hidden rounded-tile bg-surface p-0 shadow-card">
            <ResultRow label={t('Partner portal')} right={<span className="font-mono text-label">{done.portal_url}</span>} />
            {done.technicians.map((x) => (
              <ResultRow key={x.tech_id} label={`${t('Technician page')} · ${x.name}`} right={<Link to={x.url} className="font-mono text-label text-wine">{x.url}</Link>} />
            ))}
            {done.file && <ResultRow label={t('Saved as')} right={<span className="font-mono text-label">{done.file}</span>} />}
          </ul>
          <Link to={done.portal_url} className="btn-primary">
            {t('Go to your partner portal')} →
          </Link>
        </div>
      </RegShell>
    )
  }

  if (review) {
    const lc = localChecks(p)
    const failed = checks?.filter((c) => !c.ok) ?? []
    return (
      <RegShell side={sideSteps}>
        <div className="max-w-[660px] pt-6 md:pt-0">
          <Eyebrow>{t('Step 6 of 6')}</Eyebrow>
          <H2>{t('Checking your details')}</H2>
          <Lead>{t('These checks run automatically. A reltix property manager then reviews your documents.')}</Lead>
          <ul className="my-5 list-none overflow-hidden rounded-tile bg-surface p-0 shadow-card">
            {lc.map((c) => (
              <ResultRow key={c.label} label={c.label} right={<span className={`pill ${c.ok ? 'bg-ok-tint text-ok' : 'bg-warn-tint text-warn'}`}>{c.pill}</span>} />
            ))}
            <ResultRow
              label={t('Connector spec (Debye can send you jobs)')}
              right={
                checks === null ? (
                  <span className="pill">{t('Checking…')}</span>
                ) : (
                  <span className={`pill ${failed.length ? 'bg-warn-tint text-warn' : 'bg-ok-tint text-ok'}`}>{t('{n}/{m} passed', { n: checks.length - failed.length, m: checks.length })}</span>
                )
              }
            />
          </ul>
          {failed.length > 0 && (
            <ul className="mb-4 list-disc pl-5 text-label text-warn">
              {failed.map((c, i) => (
                <li key={i}>{c.message}</li>
              ))}
            </ul>
          )}
          {err && <p className="mb-4 font-medium text-red">{err}</p>}
          <div className="flex flex-wrap items-center gap-2.5">
            <button className="btn-ghost" onClick={back}>
              ← {t('Back')}
            </button>
            <button className="btn-primary" disabled={busy || checks === null || failed.length > 0} onClick={goLive}>
              {busy ? t('Going live…') : `${t('Go to your partner portal')} →`}
            </button>
          </div>
        </div>
      </RegShell>
    )
  }

  const st = STEPS[step]
  return (
    <RegShell side={sideSteps} wide>
      <div className="pt-6 md:pt-0">
        <div className="flex flex-wrap items-center justify-between gap-2 pr-24">
          <Eyebrow>{t('Step {n} of 6', { n: step + 1 })}</Eyebrow>
          <button type="button" className="link-btn" onClick={() => setP(DEMO_PROFILE)}>
            {t('Fill demo company')}
          </button>
        </div>
        <H2>{t(st.t)}</H2>
        <Lead>{t(st.lead)}</Lead>
        <div className="grid grid-cols-1 gap-x-[18px] gap-y-4 sm:grid-cols-2">
          {st.fields.map((f, i) => (
            <ProfileField key={f.k ?? f.sec ?? f.custom ?? i} f={f} p={p} set={set} errors={errors} first={i === 0} />
          ))}
        </div>
        <div className="mt-[30px] flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
          {step === 0 ? (
            <Link to="/partner" className="btn-ghost">
              ← {t('Back')}
            </Link>
          ) : (
            <button className="btn-ghost" onClick={back}>
              ← {t('Back')}
            </button>
          )}
          <span className="order-last w-full text-center sm:order-none sm:w-auto">
            {errors.length ? <span className="font-medium text-red">{t('Please fill in the marked fields')}</span> : <span className="text-muted">{t('Fields with * are required')}</span>}
          </span>
          <button className="btn-primary" onClick={next}>
            {step === STEPS.length - 1 ? t('Submit for verification') : `${t('Continue')} →`}
          </button>
        </div>
      </div>
    </RegShell>
  )
}

function StepDot({ n, on, done }: { n: number; on: boolean; done: boolean }) {
  return (
    <span
      className={`grid h-[22px] w-[22px] flex-none place-items-center rounded-full border-[1.5px] text-[11px] font-bold ${on ? 'border-wine bg-wine text-white' : done ? 'border-ok bg-ok text-white' : 'border-[#D1D1D6] bg-surface'}`}
    >
      {done && !on ? '✓' : n}
    </span>
  )
}

function ResultRow({ label, right }: { label: ReactNode; right: ReactNode }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-3.5 first:border-t-0">
      <span className="min-w-0 [overflow-wrap:anywhere]">{label}</span>
      {right}
    </li>
  )
}
