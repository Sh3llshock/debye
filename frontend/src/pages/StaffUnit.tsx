import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { Documents, UnitCard } from '../components/case/CasePanels'
import { Icon } from '../components/icons'
import { Card, Empty, ErrorBox, Field, Loading, StatusPill } from '../components/ui'
import { fmtDate, fmtEur, fmtRelative } from '../lib/format'
import { useStream } from '../lib/stream'
import { useDebounced, useResource } from '../lib/useResource'

export function StaffUnits() {
  const { data, error, reload } = useResource(() => api.staffUnits(), [])
  const refetch = useDebounced(reload, 300)
  useStream(() => refetch())
  return (
    <div className="flex flex-col gap-gap">
      <h1 className="text-3xl">Units</h1>
      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {!data && !error && <Loading what="Loading units" />}
      <div className="grid grid-cols-1 gap-gap md:grid-cols-2 xl:grid-cols-3">
        {data?.map((u) => (
          <Link key={u.unit_id} to={`/staff/units/${u.unit_id}`} className="rounded-card border border-line bg-surface p-card-sm shadow-card transition-colors hover:border-plum">
            <div className="flex items-baseline justify-between gap-3">
              <h2 className="text-xl">Unit {u.unit_id.replace('unit_', '')}</h2>
              {!!u.open_cases && <span className="rounded-pill bg-violet-soft px-3 py-0.5 text-sm font-semibold text-violet">{u.open_cases} open</span>}
            </div>
            <div className="mt-2 text-body-sm">{u.address}</div>
            <div className="mt-1 text-sm text-muted">
              {[u.floor != null ? `Floor ${u.floor}` : null, u.size_sqm ? `${u.size_sqm} m²` : null, u.tenant?.name].filter(Boolean).join(' · ')}
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}

export default function StaffUnit() {
  const { unitId = '' } = useParams()
  const { data: u, error, reload } = useResource(() => api.staffUnit(unitId), [unitId])
  const refetch = useDebounced(reload, 300)
  useStream(() => refetch())

  if (error && !u) return <ErrorBox error={error} onRetry={reload} />
  if (!u) return <Loading what="Loading unit" />
  const lease = { ...(u.lease ?? {}), ...((u.lease?.data as object) ?? {}) } as { rent_cold_eur?: number; start?: string }
  const label = unitId.replace('unit_', '')

  return (
    <div className="flex flex-col gap-gap">
      <div>
        <div className="text-body-sm text-muted">
          <Link to="/staff/units" className="hover:text-plum">
            Units
          </Link>{' '}
          / {(u.property?.address ?? '').split(',')[0]}
        </div>
        <h1 className="mt-2 text-3xl">Unit {label}</h1>
      </div>
      <div className="grid grid-cols-1 gap-gap lg:grid-cols-3">
        <UnitCard u={u} unitId={unitId} />
        <div className="flex flex-col gap-gap">
          <Card title="Tenant & lease">
            {u.tenant ? (
              <div className="grid grid-cols-2 gap-4">
                <Field label="Tenant">{u.tenant.name}</Field>
                <Field label="Move-in">{fmtDate(u.tenant.move_in)}</Field>
                <Field label="Cold rent">{fmtEur(lease.rent_cold_eur)}</Field>
                <Field label="Lease start">{fmtDate(lease.start)}</Field>
              </div>
            ) : (
              <Empty>No tenant</Empty>
            )}
          </Card>
          <Card title="Cases">
            {u.cases.length === 0 ? (
              <Empty>No cases</Empty>
            ) : (
              <ul className="divide-y divide-line">
                {u.cases.map((c) => (
                  <li key={c.case_id}>
                    <Link to={`/staff/cases/${c.case_id}`} className="flex items-center gap-3 py-3 hover:text-plum">
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-semibold">{c.title}</span>
                        <span className="text-sm text-muted">{fmtRelative(c.updated_at)}</span>
                      </span>
                      <StatusPill status={c.status} />
                      <Icon name="chevron" className="h-5 w-5 text-muted" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <Documents docs={u.documents} title={`Documents · unit ${label}`} />
      </div>
    </div>
  )
}
