import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { CaseSummary } from '../api/types'
import { LiveDot, useFullBleed } from '../components/Layout'
import { NewPartnersBanner } from '../components/staff/PartnerApplications'
import { ChannelTag, Chat, channelOf, firstName, isOpen, lastMessage, messagePreview, needsMe, StagePill, SummaryCard, tenantOf } from '../components/staff/StaffBits'
import { ErrorBox, Loading } from '../components/ui'
import { fmtRelative, fmtTime, placeLabel } from '../lib/format'
import { t } from '../lib/i18n'
import { useStaffBoard } from '../lib/staffBoard'
import { useNewKeys } from '../lib/useNewKeys'

type Filter = 'all' | 'me' | 'open'

/** Outlook-style inbox: conversations on the left, the selected one (summary + chat) on the right. */
export default function StaffInbox() {
  useFullBleed()
  const { cases, details, error, reload } = useStaffBoard()
  const [filter, setFilter] = useState<Filter>('all')
  const [sel, setSel] = useState<string | null>(null)
  const [reading, setReading] = useState(false) // phones: list or reading pane
  const lastTs = (c: CaseSummary) => lastMessage(details[c.case_id])?.ts ?? c.updated_at
  const isNew = useNewKeys(cases ? cases.map((c) => c.case_id + c.status) : null)

  let list = (cases ?? []).slice()
  if (filter === 'me') list = list.filter(needsMe)
  if (filter === 'open') list = list.filter(isOpen)
  list.sort((a, b) => Number(needsMe(b)) - Number(needsMe(a)) || lastTs(b).localeCompare(lastTs(a)))
  const selId = sel && list.some((c) => c.case_id === sel) ? sel : list[0]?.case_id ?? null
  const c = selId ? details[selId] : undefined
  const summary = selId ? list.find((x) => x.case_id === selId) : undefined

  if (error && !cases) return <div className="p-6"><ErrorBox error={error} onRetry={reload} /></div>

  return (
    <div className="grid h-full grid-cols-1 md:grid-cols-[380px_minmax(0,1fr)]">
      <div className={`overflow-y-auto border-line bg-bg md:border-r ${reading ? 'hidden md:block' : ''}`}>
        <div className="flex items-center justify-between px-[18px] pb-2.5 pt-[18px]">
          <h2 className="text-head font-semibold">{t('Inbox')}</h2>
          <span className="flex items-center gap-3 text-muted">
            <LiveDot />
            {list.length}
          </span>
        </div>
        <div className="flex gap-1.5 px-[18px] pb-2.5">
          {(
            [
              ['all', 'All'],
              ['me', 'Needs me'],
              ['open', 'Open'],
            ] as [Filter, string][]
          ).map(([k, l]) => (
            <button key={k} onClick={() => setFilter(k)} className={`rounded-full px-[11px] py-[5px] text-label ${filter === k ? 'bg-wine-tint font-semibold text-wine' : 'text-secondary hover:bg-beige'}`}>
              {t(l)}
            </button>
          ))}
        </div>
        <NewPartnersBanner />
        {!cases && <Loading />}
        {cases && list.length === 0 && <div className="px-5 py-8 text-center text-muted">{t('Nothing here.')}</div>}
        {list.map((x) => {
          const d = details[x.case_id]
          const name = tenantOf(d) ?? placeLabel(x.address, x.unit_id)
          const m = lastMessage(d)
          const on = x.case_id === selId
          return (
            <button
              key={x.case_id}
              onClick={() => {
                setSel(x.case_id)
                setReading(true)
              }}
              className={`relative grid w-full grid-cols-[36px_minmax(0,1fr)_auto] gap-2.5 border-t border-line px-[18px] py-3 text-left ${on ? 'bg-wine-tint' : 'hover:bg-[rgba(107,31,51,.035)]'} ${isNew(x.case_id + x.status) ? 'animate-enter' : ''}`}
            >
              {needsMe(x) && <span className="absolute left-1.5 top-[22px] h-[7px] w-[7px] rounded-full bg-wine" aria-label={t('Needs you')} />}
              <span className={`uav ${needsMe(x) ? '' : 'bg-[#B9AAA4]'}`}>{name.charAt(0)}</span>
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-1.5 text-body font-semibold">
                  {name} <ChannelTag ch={channelOf(d)} />
                </span>
                <span className="mt-px block truncate text-body-sm">{x.title}</span>
                <span className="mt-0.5 block truncate text-label text-muted">{messagePreview(m)}</span>
              </span>
              <span className="flex flex-col items-end gap-1.5 text-right text-meta text-muted">
                {m ? fmtRelative(m.ts) : fmtRelative(x.updated_at)}
                <StagePill c={x} inbox />
              </span>
            </button>
          )
        })}
      </div>

      <div className={`overflow-y-auto px-4 pb-10 pt-6 md:px-[30px] ${reading ? '' : 'hidden md:block'}`}>
        <button className="mb-3 text-label text-muted hover:text-wine md:hidden" onClick={() => setReading(false)}>
          ← {t('Inbox')}
        </button>
        {!selId && cases && <div className="px-5 py-[60px] text-center text-muted">{t('No messages yet. When a tenant writes to Debye on WhatsApp or the website, it lands here.')}</div>}
        {selId && !c && <Loading />}
        {c && summary && (
          <>
            <div className="mb-[18px] flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 className="text-title font-semibold">{c.title}</h2>
                <p className="mt-1 text-muted">
                  {[tenantOf(c), placeLabel(c.address, c.unit_id), t('case {id}', { id: c.case_id.replace(/^case_0*/, '') }), t('via {ch} at {time}', { ch: channelOf(c) === 'Website' ? t('Website') : channelOf(c) === 'Phone' ? t('Phone') : 'WhatsApp', time: fmtTime(c.created_at) })].filter(Boolean).join(' · ')}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <StagePill c={c} />
                <Link className={needsMe(c) ? 'btn-primary' : 'btn-secondary'} to={`/staff/cases/${c.case_id}`}>
                  {needsMe(c) ? t('Approve partner →') : t('Open case →')}
                </Link>
              </div>
            </div>
            <SummaryCard c={c} className="mb-[18px]" />
            <h4 className="mb-2 text-meta font-semibold tracking-normal text-muted">{t('Conversation with Debye')}</h4>
            <Chat c={c} />
            {needsMe(c) && (
              <p className="mt-3 text-label text-muted">
                {t('{name} is waiting. Approve the partner and Debye tells {name} right away.', { name: firstName(tenantOf(c)) || t('The tenant') })}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}
