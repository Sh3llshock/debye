import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { Documents, MiniLine } from '../components/case/CasePanels'
import { useCrumbs } from '../components/Layout'
import { ErrorBox, Loading, Panel, Prop } from '../components/ui'
import { fmtDate, fmtEur, fmtRelative, humanize } from '../lib/format'
import { lineState, STAFF_STATIONS } from '../lib/lifecycle'
import { useStream } from '../lib/stream'
import { useDebounced, useResource } from '../lib/useResource'

export function StaffUnits() {
  useCrumbs([{ label: 'Units' }])
  const { data, error, reload } = useResource(() => api.staffUnits(), [])
  const refetch = useDebounced(reload, 300)
  useStream(() => refetch())
  return (
    <div className="flex flex-col gap-work">
      <h1 className="text-page">Units</h1>
      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {!data && !error && <Loading what="Loading units" />}
      {data && (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[640px] text-left">
            <thead className="bg-sub">
              <tr className="border-b border-line text-label text-muted">
                <th className="px-5 py-3 font-medium">Unit</th>
                <th className="px-4 py-3 font-medium">Address</th>
                <th className="px-4 py-3 font-medium">Size</th>
                <th className="px-4 py-3 font-medium">Tenant</th>
                <th className="px-4 py-3 font-medium">Open cases</th>
              </tr>
            </thead>
            <tbody>
              {data.map((u) => (
                <tr key={u.unit_id} className="h-row border-b border-line last:border-b-0 hover:bg-sub">
                  <td className="px-5 py-3">
                    <Link to={`/staff/units/${u.unit_id}`} className="font-semibold hover:underline">
                      Unit {u.unit_id.replace('unit_', '')}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-body-sm">{u.address}</td>
                  <td className="px-4 py-3 text-body-sm">{[u.floor != null ? `Floor ${u.floor}` : null, u.size_sqm ? `${u.size_sqm} m²` : null].filter(Boolean).join(' · ')}</td>
                  <td className="px-4 py-3 text-body-sm">{u.tenant?.name ?? '—'}</td>
                  <td className="px-4 py-3 text-body-sm">{u.open_cases ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function StaffUnit() {
  const { unitId = '' } = useParams()
  const label = unitId.replace('unit_', '')
  const { data: u, error, reload } = useResource(() => api.staffUnit(unitId), [unitId])
  const refetch = useDebounced(reload, 300)
  useStream(() => refetch())
  useCrumbs([{ label: 'Units', to: '/staff/units' }, { label: u ? `${(u.property?.address ?? '').split(',')[0]} · ${label}` : label }])

  if (error && !u) return <ErrorBox error={error} onRetry={reload} />
  if (!u) return <Loading what="Loading unit" />
  const p = u.property
  const lease = { ...(u.lease ?? {}), ...((u.lease?.data as object) ?? {}) } as { rent_cold_eur?: number; start?: string }
  const boiler = u.assets.find((a) => a.type?.includes('boiler')) ?? u.assets[0]

  return (
    <div className="flex flex-col gap-work">
      <h1 className="text-page">Unit {label}</h1>
      <div className="grid grid-cols-1 gap-work xl:grid-cols-[minmax(0,1fr)_theme(spacing.inspector)]">
        <div className="flex min-w-0 flex-col gap-work">
          <Panel title="Cases on this unit">
            {u.cases.length === 0 ? (
              <div className="px-5 py-6 text-muted">No cases</div>
            ) : (
              <table className="w-full text-left">
                <tbody>
                  {u.cases.map((c) => (
                    <tr key={c.case_id} className="h-row border-b border-line last:border-b-0 hover:bg-sub">
                      <td className="px-5 py-3">
                        <Link to={`/staff/cases/${c.case_id}`} className="font-semibold hover:underline">
                          {c.title}
                        </Link>
                        <div className="text-meta text-muted">{c.case_id}</div>
                      </td>
                      <td className="px-4 py-3">
                        <MiniLine total={STAFF_STATIONS.length} reached={lineState(STAFF_STATIONS, c.status).reached} status={c.status} />
                      </td>
                      <td className="px-5 py-3 text-right text-body-sm text-secondary">{fmtRelative(c.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
          <Panel title="Documents" bodyClass="px-5 py-4">
            <Documents docs={u.documents} />
          </Panel>
        </div>
        <aside className="panel self-start">
          <section className="border-b border-line px-5 py-4">
            <h3 className="mb-2 text-panel">Unit</h3>
            <dl>
              <Prop label="Address">{p?.address}</Prop>
              <Prop label="Floor">{[u.unit.floor, u.unit.size_sqm ? `${u.unit.size_sqm} m²` : null, u.unit.rooms ? `${u.unit.rooms} rooms` : null].filter((x) => x != null).join(' · ')}</Prop>
              <Prop label="Building">{[p?.building_year, p?.heating_type ? humanize(p.heating_type) : null, p?.energy_class ? `energy class ${p.energy_class}` : null].filter(Boolean).join(' · ')}</Prop>
              {boiler && (
                <Prop label="Boiler">
                  {boiler.make} {boiler.model}
                  {boiler.installed ? ` (${boiler.installed.slice(0, 4)})` : ''}
                </Prop>
              )}
            </dl>
          </section>
          <section className="px-5 py-4">
            <h3 className="mb-2 text-panel">Tenant and lease</h3>
            <dl>
              <Prop label="Tenant">{u.tenant?.name ?? '—'}</Prop>
              <Prop label="Move-in">{fmtDate(u.tenant?.move_in)}</Prop>
              <Prop label="Cold rent">{fmtEur(lease.rent_cold_eur)}</Prop>
              <Prop label="Lease start">{fmtDate(lease.start)}</Prop>
            </dl>
          </section>
        </aside>
      </div>
    </div>
  )
}
