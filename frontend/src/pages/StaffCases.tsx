import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useCrumbs } from '../components/Layout'
import { isOpen, MiniBar, needsMe, StagePill, tenantOf } from '../components/staff/StaffBits'
import { ErrorBox, Loading } from '../components/ui'
import { placeLabel, unitLabel } from '../lib/format'
import { t } from '../lib/i18n'
import { useStaffBoard } from '../lib/staffBoard'
import { useNewKeys } from '../lib/useNewKeys'

export const shortId = (id: string) => id.replace(/^case_0*/, '')

export default function StaffCases() {
  useCrumbs([{ label: t('Cases') }])
  const { cases, details, error, reload } = useStaffBoard()
  const [all, setAll] = useState(false)
  const [params, setParams] = useSearchParams()
  const q = (params.get('q') ?? '').trim().toLowerCase()
  const nav = useNavigate()
  const isNew = useNewKeys(cases ? cases.map((c) => c.case_id + c.status) : null)

  const running = cases?.filter(isOpen) ?? []
  const need = cases?.filter(needsMe).length ?? 0
  const match = (c: NonNullable<typeof cases>[number]) => {
    if (!q) return true
    const hay = [c.case_id, c.title, c.address, c.unit_id, c.partner?.name, c.technician?.name, tenantOf(details[c.case_id])].join(' ').toLowerCase()
    return hay.includes(q)
  }
  const rows = (cases ?? [])
    .filter((c) => (all || q ? true : isOpen(c)))
    .filter(match)
    .sort((a, b) => Number(needsMe(b)) - Number(needsMe(a)) || b.updated_at.localeCompare(a.updated_at))

  return (
    <>
      <div className="mb-[18px] flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-page font-medium">{t('Cases')}</h1>
          <p className="mt-1 text-secondary">
            {t('{n} running', { n: running.length })} · {t(need === 1 ? '{n} needs you' : '{n} need you', { n: need })}
            {q && (
              <>
                {' · '}
                {t('search “{q}”', { q })}{' '}
                <button className="link-btn" onClick={() => setParams({})}>
                  {t('clear')}
                </button>
              </>
            )}
          </p>
        </div>
        <button className="btn-ghost" onClick={() => setAll(!all)}>
          {all ? t('Show running only') : t('Show closed too')}
        </button>
      </div>

      {error && !cases && <ErrorBox error={error} onRetry={reload} />}
      {!cases && !error && <Loading what={t('Loading cases')} />}

      {cases && (
        <div className="card overflow-x-auto p-2">
          <table className="t min-w-[860px]">
            <thead>
              <tr>
                <th>{t('Case')}</th>
                <th>{t('Problem')}</th>
                <th>{t('Flat')}</th>
                <th>{t('Partner')}</th>
                <th>{t('Progress')}</th>
                <th>{t('Status')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.case_id} className={`click ${isNew(c.case_id + c.status) ? 'animate-enter' : ''}`} onClick={() => nav(`/staff/cases/${c.case_id}`)}>
                  <td>
                    <b>{shortId(c.case_id)}</b>
                  </td>
                  <td>
                    <Link to={`/staff/cases/${c.case_id}`} className="font-medium text-ink no-underline" onClick={(e) => e.stopPropagation()}>
                      {c.title}
                    </Link>
                    <br />
                    <span className="text-muted">{tenantOf(details[c.case_id]) ?? ' '}</span>
                  </td>
                  <td>
                    {placeLabel(c.address).split(' · ')[0]} <span className="text-muted">· {t('unit {u}', { u: unitLabel(c.unit_id, c.address) })}</span>
                  </td>
                  <td>
                    {c.partner ? c.partner.name.replace(/ GmbH$| KG$/, '') : <span className="text-muted">–</span>}
                    {c.technician && <div className="text-meta text-muted">{c.technician.name}</div>}
                  </td>
                  <td>
                    <MiniBar c={c} />
                  </td>
                  <td>
                    <StagePill c={c} />
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-[60px] text-center text-muted">
                    {q ? t('No cases match “{q}”.', { q }) : t('No running cases.')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
