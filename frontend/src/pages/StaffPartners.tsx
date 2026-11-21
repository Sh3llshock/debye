import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { JobSummary, PartnerProfile, Technician } from '../api/types'
import { tradeLabel } from '../components/case/Diagnosis'
import { useCrumbs } from '../components/Layout'
import { NewPartnersSection } from '../components/staff/PartnerApplications'
import { Pill, StagePill } from '../components/staff/StaffBits'
import { ErrorBox, Loading } from '../components/ui'
import { t } from '../lib/i18n'
import { useStream } from '../lib/stream'
import { useDebounced, useResource } from '../lib/useResource'

const DONE = new Set(['completed', 'invoiced', 'closed', 'declined', 'partner_declined'])

function trades(p: PartnerProfile): string[] {
  const tr = p.capabilities?.trades
  if (tr?.length) return tr
  const cat = p.category?.split('.').pop()
  return cat ? [cat] : []
}
const str = (v: unknown) => (typeof v === 'string' || typeof v === 'number' ? String(v) : null)

function Row({ p }: { p: PartnerProfile }) {
  const jobs = useResource(() => api.jobs(p.partner_id).catch(() => [] as JobSummary[]), [p.partner_id])
  const refetch = useDebounced(jobs.reload, 400)
  useStream(() => refetch())
  const nav = useNavigate()
  const active = p.open_jobs ?? jobs.data?.filter((j) => !DONE.has(j.status)).length ?? 0
  const city = str((p as Record<string, unknown>).city) ?? p.service_area?.base_postcode ?? ''
  return (
    <tr className="click" onClick={() => nav(`/staff/partners/${p.partner_id}`)}>
      <td>
        <b>{p.name}</b>
        <br />
        <span className="text-muted">{[city, str((p as Record<string, unknown>).email)].filter(Boolean).join(' · ')}</span>
      </td>
      <td>{trades(p).map((x) => tradeLabel(x)).join(', ')}</td>
      <td>{(p.capabilities?.brands_certified ?? []).join(', ') || <span className="text-muted">–</span>}</td>
      <td className="text-right">{p.rating != null ? p.rating.toFixed(1) : '–'}</td>
      <td className="text-right">{jobs.data?.length ?? '…'}</td>
      <td>{active ? <Pill tone="hot">{t('{n} active', { n: active })}</Pill> : <span className="text-muted">–</span>}</td>
      <td>
        <PartnerStatusPill p={p} />
      </td>
    </tr>
  )
}

function PartnerStatusPill({ p }: { p: PartnerProfile }) {
  const st = p.status ?? (p.active === false ? 'suspended' : 'active')
  if (st === 'pending_review') return <Pill tone="hot">{t('Under review')}</Pill>
  if (st === 'rejected') return <Pill>{t('Rejected')}</Pill>
  if (st === 'suspended') return <Pill tone="warn">{t('Suspended')}</Pill>
  return <Pill tone="ok">{t('Verified')}</Pill>
}

/** /staff/partners: verified partner companies (they register in the partner portal). */
export default function StaffPartners() {
  useCrumbs([{ label: t('Partners') }])
  const { data, error, reload } = useResource(() => api.partners(), [])
  return (
    <>
      <div className="mb-[18px] flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-page font-bold">{t('Partners')}</h1>
          <p className="mt-1 text-secondary">{t('Companies register themselves in the partner portal and appear here once verified.')}</p>
        </div>
        <Link to="/partners/join" className="btn-ghost">
          {t('Partner sign-up page')}
        </Link>
      </div>
      <NewPartnersSection onChange={reload} />
      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {!data && !error && <Loading what={t('Loading partners')} />}
      {data && (
        <div className="card overflow-x-auto p-2">
          <table className="t min-w-[820px]">
            <thead>
              <tr>
                <th>{t('Partner')}</th>
                <th>{t('Services')}</th>
                <th>{t('Brands')}</th>
                <th className="text-right">{t('Rating')}</th>
                <th className="text-right">{t('Jobs')}</th>
                <th>{t('Now')}</th>
                <th>{t('Status')}</th>
              </tr>
            </thead>
            <tbody>
              {data.map((p) => (
                <Row key={p.partner_id} p={p} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

/** /staff/partners/:pid: one partner with services, area, team (open as technician) and jobs for us. */
export function StaffPartner() {
  const { partnerId = '' } = useParams()
  const { data: p, error, reload } = useResource(() => api.partner(partnerId), [partnerId])
  const techs = useResource(() => api.technicians(partnerId).catch(() => [] as Technician[]), [partnerId])
  const jobs = useResource(() => api.jobs(partnerId).catch(() => [] as JobSummary[]), [partnerId])
  const refetch = useDebounced(() => {
    jobs.reload()
    techs.reload()
  }, 400)
  useStream(() => refetch())
  const nav = useNavigate()
  useCrumbs([{ label: t('Partners'), to: '/staff/partners' }, { label: p?.name ?? partnerId }])
  if (error && !p) return <ErrorBox error={error} onRetry={reload} />
  if (!p) return <Loading what={t('Loading partners')} />
  const x = p as Record<string, unknown>
  const contact = (x.contact ?? {}) as Record<string, unknown>
  const pricing = (x.pricing ?? {}) as Record<string, unknown>
  const done = jobs.data?.filter((j) => DONE.has(j.status)).length ?? 0
  const area = p.service_area?.postcodes?.length ? p.service_area.postcodes.join(', ') : p.service_area?.radius_km ? t('{km} km around {pc}', { km: p.service_area.radius_km, pc: p.service_area.base_postcode }) : '–'
  const kv = (rows: [string, React.ReactNode][]) => (
    <dl className="kv">
      {rows
        .filter(([, v]) => v != null && v !== '')
        .map(([k, v]) => (
          <div key={k} className="contents">
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
    </dl>
  )
  return (
    <>
      <div className="mb-[18px] flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-page font-bold">{p.name}</h1>
          <p className="mt-1 text-secondary">{[trades(p).map((y) => tradeLabel(y)).join(', '), area].filter(Boolean).join(' · ')}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <PartnerStatusPill p={p} />
          <Link className="btn-ghost" to={`/partner/${p.partner_id}`}>
            {t('Open partner portal')}
          </Link>
        </div>
      </div>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          [p.rating != null ? p.rating.toFixed(1) : '–', t('Rating')],
          [String(jobs.data?.length ?? '…'), t('Jobs for us')],
          [String(done), t('Done')],
          [String(techs.data?.length ?? '…'), t('Technicians')],
        ].map(([b, s]) => (
          <div key={s} className="rounded-tile bg-surface px-4 py-3.5 shadow-ring">
            <b className="block text-stat font-bold">{b}</b>
            <span className="text-label text-muted">{s}</span>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
        <section className="card">
          <h3 className="mb-3 text-panel">{t('Company & contact')}</h3>
          {kv([
            [t('Contact'), str(contact.name) ?? p.staff?.[0]?.name],
            [t('Email'), str(contact.email) ?? str(x.email)],
            [t('Phone'), str(contact.phone) ?? str(x.phone)],
            [t('Pricing'), pricing.model ? (pricing.model === 'framework_agreement' ? t('Framework agreement') : String(pricing.model).replace(/_/g, ' ')) : null],
            [t('Callout'), pricing.callout_fee_eur != null ? `€${pricing.callout_fee_eur}` : null],
            [t('Hourly'), pricing.hourly_eur != null ? `€${pricing.hourly_eur}` : null],
            [t('Partner ID'), p.partner_id],
          ])}
        </section>
        <section className="card">
          <h3 className="mb-3 text-panel">{t('Services & area')}</h3>
          <div className="mb-2 text-label text-muted">{t('Services')}</div>
          <div className="flex flex-wrap gap-1.5">
            {trades(p).map((y) => (
              <span key={y} className="rounded-full bg-beige px-2.5 py-1 text-label">
                {tradeLabel(y)}
              </span>
            ))}
          </div>
          {(p.capabilities?.brands_certified ?? []).length > 0 && (
            <>
              <div className="mb-2 mt-3.5 text-label text-muted">{t('Certified brands')}</div>
              <div className="flex flex-wrap gap-1.5">
                {p.capabilities!.brands_certified!.map((b) => (
                  <span key={b} className="rounded-full bg-beige px-2.5 py-1 text-label">
                    {b}
                  </span>
                ))}
              </div>
            </>
          )}
          <div className="mt-3.5">{kv([[t('Area'), area]])}</div>
        </section>
        <section className="card">
          <h3 className="mb-3 text-panel">{t('Team')}</h3>
          {techs.data === null ? (
            <Loading />
          ) : techs.data.length === 0 ? (
            <span className="text-muted">{t('No technicians listed')}</span>
          ) : (
            <table className="t">
              <tbody>
                {techs.data.map((tc) => (
                  <tr key={tc.tech_id}>
                    <td>
                      <b>{tc.name}</b>
                      <br />
                      <span className="text-muted">
                        {tc.skills.join(' · ')}
                        {tc.free_slots ? ` · ${t('{n} free slots in the next days', { n: tc.free_slots.length })}` : ''}
                      </span>
                    </td>
                    <td className="text-right">
                      <Link to={`/tech/${tc.tech_id}`} className="text-label font-semibold text-wine no-underline hover:underline">
                        {t('Open as {name}', { name: tc.name.split(' ')[0] })} →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <section className="card">
          <h3 className="mb-3 text-panel">{t('Jobs with us')}</h3>
          {!jobs.data?.length ? (
            <span className="text-muted">{t('No jobs yet')}</span>
          ) : (
            <table className="t">
              <tbody>
                {jobs.data.map((j) => (
                  <tr key={j.case_id} className="click" onClick={() => nav(`/staff/cases/${j.case_id}`)}>
                    <td>
                      <b>{j.title}</b>
                      <br />
                      <span className="text-muted">
                        {j.case_id.replace(/^case_0*/, '')} · {(j.address ?? '').split(',')[0]}
                      </span>
                    </td>
                    <td className="text-right">
                      <StagePill c={{ ...j, unit_id: '', partner: null, type: j.type ?? '', address: j.address ?? '' }} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </>
  )
}
