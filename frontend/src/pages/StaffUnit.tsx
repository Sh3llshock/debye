import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { UnitDetail } from '../api/types'
import { Documents } from '../components/case/CasePanels'
import { useCrumbs } from '../components/Layout'
import { isOpen, StagePill } from '../components/staff/StaffBits'
import { ErrorBox, Loading } from '../components/ui'
import { fmtDate, fmtEur, floorLabel, humanize, maskPhone, placeLabel, unitLabel } from '../lib/format'
import { locale, t } from '../lib/i18n'
import { useStream } from '../lib/stream'
import { useDebounced, useResource } from '../lib/useResource'

const street = (a?: string | null) => (a ?? '').split(',')[0].trim()
const city = (a?: string | null) => (a ?? '').split(',').slice(1).join(',').trim()
const device = (u?: UnitDetail | null) => {
  const b = u?.assets.find((a) => a.type?.includes('boiler') || a.type?.includes('heater')) ?? u?.assets[0]
  return b ? { name: `${b.make} ${b.model}`, year: b.installed?.slice(0, 4), type: b.type, service: b.last_service } : null
}

/** /staff/units ("Properties"): every flat with tenant, hot-water device and open cases. */
export function StaffUnits() {
  useCrumbs([{ label: t('Properties') }])
  const { data, error, reload } = useResource(() => api.staffUnits(), [])
  const [details, setDetails] = useState<Record<string, UnitDetail>>({})
  const refetch = useDebounced(reload, 300)
  useStream(() => refetch())
  const nav = useNavigate()
  useEffect(() => {
    if (!data) return
    Promise.all(data.map((u) => api.staffUnit(u.unit_id).then((d) => [u.unit_id, d] as const).catch(() => null))).then((xs) =>
      setDetails(Object.fromEntries(xs.filter((x): x is readonly [string, UnitDetail] => !!x))),
    )
  }, [data])
  const open = data?.reduce((a, u) => a + (u.open_cases ?? 0), 0) ?? 0
  return (
    <>
      <div className="mb-[18px] flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-page font-bold">{t('Properties')}</h1>
          {data && (
            <p className="mt-1 text-secondary">
              {t('{n} flats', { n: data.length })} · {t('{n} open cases', { n: open })} · {t('all data from centrix')}
            </p>
          )}
        </div>
      </div>
      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {!data && !error && <Loading what={t('Loading units')} />}
      {data && (
        <div className="card overflow-x-auto p-2">
          <table className="t min-w-[760px]">
            <thead>
              <tr>
                <th>{t('Flat')}</th>
                <th>{t('Tenant')}</th>
                <th>{t('Hot water')}</th>
                <th>{t('Size')}</th>
                <th>{t('Cases')}</th>
              </tr>
            </thead>
            <tbody>
              {data.map((u) => {
                const d = device(details[u.unit_id])
                return (
                  <tr key={u.unit_id} className="click" onClick={() => nav(`/staff/units/${u.unit_id}`)}>
                    <td>
                      <Link to={`/staff/units/${u.unit_id}`} className="font-semibold text-ink no-underline" onClick={(e) => e.stopPropagation()}>
                        {street(u.address)} · {floorLabel(u.floor)}
                      </Link>
                      <br />
                      <span className="text-muted">
                        {city(u.address)} · {t('unit {u}', { u: unitLabel(u.unit_id, u.address) })}
                      </span>
                    </td>
                    <td>{u.tenant?.name ?? '–'}</td>
                    <td>{d ? d.name : <span className="text-muted">…</span>}</td>
                    <td>{[u.size_sqm ? `${u.size_sqm} m²` : null, u.rooms ? t('{n} rooms', { n: u.rooms }) : null].filter(Boolean).join(' · ')}</td>
                    <td>{u.open_cases ? <span className="pill bg-wine-tint text-wine">{t('{n} open', { n: u.open_cases })}</span> : <span className="text-muted">–</span>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

/** /staff/units/:id: one flat with stats, its cases, details from centrix and documents. */
export default function StaffUnit() {
  const { unitId = '' } = useParams()
  const { data: u, error, reload } = useResource(() => api.staffUnit(unitId), [unitId])
  const refetch = useDebounced(reload, 300)
  useStream(() => refetch())
  const nav = useNavigate()
  useCrumbs([{ label: t('Properties'), to: '/staff/units' }, { label: t('unit {u}', { u: unitLabel(unitId, u?.property?.address) }) }])

  if (error && !u) return <ErrorBox error={error} onRetry={reload} />
  if (!u) return <Loading what={t('Loading unit')} />
  const p = u.property
  const lease = { ...(u.lease ?? {}), ...((u.lease?.data as object) ?? {}) } as { rent_cold_eur?: number; start?: string }
  const d = device(u)
  const invoices = u.documents.filter((x) => x.kind === 'invoice')
  const openCases = u.cases.filter(isOpen).length
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
          <h1 className="text-page font-bold">
            {street(p?.address)} · {floorLabel(u.unit.floor)}
          </h1>
          <p className="mt-1 text-secondary">
            {city(p?.address)}{' '}
            <span className="text-muted">
              · {[t('unit {u}', { u: unitLabel(unitId, p?.address) }), u.unit.size_sqm ? `${u.unit.size_sqm} m²` : null, u.unit.rooms ? t('{n} rooms', { n: u.unit.rooms }) : null].filter(Boolean).join(' · ')}
            </span>
          </p>
        </div>
      </div>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          [String(u.cases.length), t('Cases')],
          [String(openCases), t('Open now')],
          [String(invoices.length), t('Invoices')],
          [lease.rent_cold_eur != null ? fmtEur(lease.rent_cold_eur) : '–', t('Cold rent')],
        ].map(([b, s]) => (
          <div key={s} className="rounded-tile bg-surface px-4 py-3.5 shadow-ring">
            <b className="block text-stat font-bold">{b}</b>
            <span className="text-label text-muted">{s}</span>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
        <section className="card">
          <h3 className="mb-3 text-panel">{t('Cases')}</h3>
          {u.cases.length === 0 ? (
            <span className="text-muted">{t('No cases yet')}</span>
          ) : (
            <table className="t">
              <tbody>
                {u.cases.map((c) => (
                  <tr key={c.case_id} className="click" onClick={() => nav(`/staff/cases/${c.case_id}`)}>
                    <td>
                      <b>{c.title}</b>
                      <br />
                      <span className="text-muted">
                        {c.case_id.replace(/^case_0*/, '')} · {fmtDate(c.created_at ?? c.updated_at)}
                      </span>
                    </td>
                    <td className="text-right">
                      <StagePill c={c} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <div className="flex flex-col gap-4">
          <section className="card">
            <h3 className="mb-3 text-panel">{t('Details')}</h3>
            {kv([
              [t('Tenant'), u.tenant?.name],
              [t('Phone'), u.tenant?.phone_e164 ? maskPhone(u.tenant.phone_e164) : null],
              [t('Move-in'), u.tenant?.move_in ? fmtDate(u.tenant.move_in) : null],
              [t('Hot water'), d ? humanize(d.type) : null],
              [t('Device'), d ? `${d.name}${d.year ? ` (${d.year})` : ''}` : null],
              [t('Last service'), d?.service ? new Date(d.service).toLocaleDateString(locale(), { day: 'numeric', month: 'short', year: 'numeric' }) : null],
              [t('Building'), [p?.building_year, p?.heating_type ? humanize(p.heating_type) : null, p?.energy_class ? t('energy class {c}', { c: p.energy_class }) : null].filter(Boolean).join(' · ')],
              [t('Lease start'), lease.start ? fmtDate(lease.start) : null],
            ])}
          </section>
          <section className="card">
            <h3 className="mb-3 text-panel">{t('Documents')}</h3>
            <Documents docs={u.documents} />
          </section>
        </div>
      </div>
      <p className="mt-4 text-label text-muted">{placeLabel(p?.address, unitId)} · {t('read from centrix, nothing typed by hand')}</p>
    </>
  )
}
