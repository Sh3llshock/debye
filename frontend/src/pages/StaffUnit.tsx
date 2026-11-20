import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { Documents } from '../components/case/CasePanels'
import { Card, Empty, ErrorBox, Field, Loading, StatusPill } from '../components/ui'
import { fmtDate, fmtDateTime, fmtEur, humanize } from '../lib/format'
import { useStream } from '../lib/stream'
import { useDebounced, useResource } from '../lib/useResource'

export default function StaffUnit() {
  const { unitId = '' } = useParams()
  const { data: u, error, reload } = useResource(() => api.staffUnit(unitId), [unitId])
  const refetch = useDebounced(reload, 300)
  useStream(() => refetch())

  if (error && !u) return <ErrorBox error={error} onRetry={reload} />
  if (!u) return <Loading what="Loading unit" />
  const p = u.property
  const energy = p.energy_certificate?.class ?? p.energy_class
  const label = (u.unit.id ?? u.unit.unit_id ?? unitId).replace('unit_', '')

  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className="label">Unit record</div>
        <h1 className="text-3xl">Unit {label}</h1>
        <div className="mt-1 text-lg text-muted">{p.address}</div>
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card title="Unit">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Floor">{u.unit.floor}</Field>
            <Field label="Size">{u.unit.size_sqm ? `${u.unit.size_sqm} m²` : '—'}</Field>
            <Field label="Rooms">{u.unit.rooms ?? '—'}</Field>
            <Field label="Building year">{p.building_year ?? '—'}</Field>
            <Field label="Heating">{humanize(p.heating_type)}{p.heating_central ? ' (central)' : ''}</Field>
            <Field label="Energy class">{energy ?? '—'}</Field>
          </div>
          {u.assets.length > 0 && (
            <div className="mt-4 border-t border-line pt-4">
              <div className="label">Assets</div>
              {u.assets.map((a, i) => (
                <div key={a.asset_id ?? a.id ?? i} className="mt-1">
                  <span className="font-semibold">{a.make} {a.model}</span>
                  <div className="text-sm text-muted">installed {fmtDate(a.installed)} · last service {fmtDate(a.last_service)}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card title="Tenant & lease">
          {u.tenant ? (
            <div className="grid grid-cols-2 gap-4">
              <Field label="Tenant">{u.tenant.name}</Field>
              <Field label="Move-in">{fmtDate(u.tenant.move_in)}</Field>
              <Field label="Cold rent">{fmtEur(u.lease?.rent_cold_eur as number | undefined)}</Field>
              <Field label="Lease start">{fmtDate(u.lease?.start as string | undefined)}</Field>
            </div>
          ) : (
            <Empty>No tenant</Empty>
          )}
        </Card>
        <Documents docs={u.documents} />
      </div>
      <Card title="Cases on this unit">
        {u.cases.length === 0 ? (
          <Empty>No cases</Empty>
        ) : (
          <ul className="divide-y divide-line">
            {u.cases.map((c) => (
              <li key={c.case_id}>
                <Link to={`/staff/cases/${c.case_id}`} className="flex flex-wrap items-center gap-4 py-3 hover:bg-plum-soft">
                  <span className="text-lg font-semibold text-plum">{c.title}</span>
                  <StatusPill status={c.status} />
                  <span className="ml-auto text-muted">{fmtDateTime(c.updated_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
