import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { JobSummary, PartnerProfile, Technician } from '../api/types'
import { tradeLabel } from '../components/case/Diagnosis'
import { useCrumbs } from '../components/Layout'
import { Icon } from '../components/icons'
import { Chip, ErrorBox, Loading } from '../components/ui'
import { initials } from '../lib/format'
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

function PartnerCard({ p }: { p: PartnerProfile }) {
  const techs = useResource(() => api.technicians(p.partner_id).catch(() => [] as Technician[]), [p.partner_id])
  const jobs = useResource(() => api.jobs(p.partner_id).catch(() => [] as JobSummary[]), [p.partner_id])
  const refetch = useDebounced(() => {
    jobs.reload()
    techs.reload()
  }, 400)
  useStream(() => refetch())
  const open = p.open_jobs ?? jobs.data?.filter((j) => !DONE.has(j.status)).length
  const postcodes = p.service_area?.postcodes ?? []
  const brands = p.capabilities?.brands_certified ?? []

  return (
    <section className="panel flex flex-col overflow-hidden">
      <header className="flex items-start gap-3 border-b border-line px-5 py-4">
        <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded bg-sub text-label font-semibold text-ink">{initials(p.name)}</span>
        <div className="min-w-0 flex-1">
          <h2 className="text-panel leading-tight">{p.name}</h2>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {trades(p).map((tr) => (
              <Chip key={tr} tone="action">
                {tradeLabel(tr)}
              </Chip>
            ))}
            {p.rating != null && <span className="text-label text-secondary">★ {p.rating.toFixed(1)}</span>}
          </div>
        </div>
      </header>
      <dl className="grid grid-cols-[112px_minmax(0,1fr)] gap-x-3 gap-y-1.5 px-5 py-3 text-body-sm">
        <dt className="text-muted">{t('Service area')}</dt>
        <dd>{postcodes.length ? postcodes.join(', ') : '—'}</dd>
        {brands.length > 0 && (
          <>
            <dt className="text-muted">{t('Certified')}</dt>
            <dd>{brands.join(', ')}</dd>
          </>
        )}
        <dt className="text-muted">{t('Open jobs')}</dt>
        <dd className="font-semibold">{open ?? '…'}</dd>
      </dl>
      <div className="border-t border-line px-5 py-3">
        <div className="text-label text-muted">{t('Technicians')}</div>
        {techs.data === null ? (
          <div className="py-2 text-body-sm text-muted">{t('Loading')}…</div>
        ) : techs.data.length === 0 ? (
          <div className="py-2 text-body-sm text-muted">{t('No technicians listed')}</div>
        ) : (
          <ul className="mt-1 divide-y divide-line">
            {techs.data.map((x) => (
              <li key={x.tech_id} className="flex flex-wrap items-center gap-2 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block font-medium">{x.name}</span>
                  <span className="block text-meta text-muted">
                    {x.skills.join(' · ')}
                    {x.free_slots ? ` · ${t('{n} free slots in the next days', { n: x.free_slots.length })}` : ''}
                  </span>
                </span>
                <Link to={`/tech/${x.tech_id}`} className="text-label font-semibold text-action hover:underline">
                  {t('Open as {name}', { name: x.name.split(' ')[0] })} →
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="mt-auto border-t border-line px-5 py-3">
        <Link to={`/partner/${p.partner_id}`} className="btn-secondary w-full">
          <Icon name="jobs" className="h-4 w-4" /> {t('Open partner portal')}
        </Link>
      </div>
    </section>
  )
}

/** /staff/partners: every partner with trades, rating, area, open jobs and technicians, linking to their portals. */
export default function StaffPartners() {
  useCrumbs([{ label: t('Partners') }])
  const { data, error, reload } = useResource(() => api.partners(), [])
  return (
    <div className="flex flex-col gap-work">
      <div>
        <h1 className="text-page">{t('Partners')}</h1>
        <p className="mt-1 text-body text-secondary">{t('Framework partners Debye can send jobs to. Open their portal or a technician view to see what they see.')}</p>
      </div>
      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {!data && !error && <Loading what={t('Loading partners')} />}
      {data && (
        <div className="grid grid-cols-1 gap-work md:grid-cols-2 xl:grid-cols-3">
          {data.map((p) => (
            <PartnerCard key={p.partner_id} p={p} />
          ))}
        </div>
      )}
    </div>
  )
}
