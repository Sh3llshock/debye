import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Card, Empty, ErrorBox, Loading, PriorityPill, StatusPill } from '../components/ui'
import { fmtDateTime } from '../lib/format'
import { useStream } from '../lib/stream'
import { useDebounced, useResource } from '../lib/useResource'
import { useNewKeys } from '../lib/useNewKeys'

export default function StaffCases() {
  const { data, error, reload } = useResource(() => api.staffCases(), [])
  const refetch = useDebounced(reload, 250)
  useStream(() => refetch())
  const isNew = useNewKeys(data ? data.map((c) => c.case_id + c.status) : null)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-3xl">Cases</h1>
        <span className="text-muted">{data?.length ?? 0} cases · newest first</span>
      </div>
      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {!data && !error && <Loading what="Loading cases" />}
      {data && data.length === 0 && <Empty>No cases yet. When a resident messages Debye on WhatsApp, the case appears here live.</Empty>}
      {data && data.length > 0 && (
        <Card className="!p-0 overflow-hidden">
          <table className="w-full text-left">
            <thead className="bg-surface-alt">
              <tr className="label">
                <th className="px-card py-3">Case</th>
                <th className="px-4 py-3">Status</th>
                <th className="hidden px-4 py-3 md:table-cell">Priority</th>
                <th className="hidden px-4 py-3 lg:table-cell">Partner</th>
                <th className="hidden px-4 py-3 lg:table-cell">Updated</th>
              </tr>
            </thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.case_id} className={`border-t border-line hover:bg-plum-soft ${isNew(c.case_id + c.status) ? 'animate-enter' : ''}`}>
                  <td className="px-card py-4">
                    <Link to={`/staff/cases/${c.case_id}`} className="block">
                      <div className="text-lg font-semibold text-plum">{c.title}</div>
                      <div className="text-sm text-muted">{c.case_id} · {c.address} · {c.unit_id.replace('unit_', 'Unit ')}</div>
                    </Link>
                  </td>
                  <td className="px-4 py-4"><StatusPill status={c.status} /></td>
                  <td className="hidden px-4 py-4 md:table-cell"><PriorityPill priority={c.priority} /></td>
                  <td className="hidden px-4 py-4 lg:table-cell">{c.partner?.name ?? <span className="text-muted">—</span>}</td>
                  <td className="hidden px-4 py-4 text-muted lg:table-cell">{fmtDateTime(c.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
