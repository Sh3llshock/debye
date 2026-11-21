// Feature 1: while a self-onboarded partner waits for review (or was rejected / suspended),
// the portal shows this instead of the job inbox.
import type { PartnerProfile } from '../../api/types'
import { fmtRelative } from '../../lib/format'
import { t } from '../../lib/i18n'

export function needsReviewGate(p: PartnerProfile | null | undefined): boolean {
  return !!p && (p.status === 'pending_review' || p.status === 'rejected' || p.status === 'suspended')
}

export function ReviewStatus({ p }: { p: PartnerProfile }) {
  const reason = p.review?.reason
  const box = 'max-w-[660px] rounded-tile bg-surface p-6 shadow-card'
  if (p.status === 'pending_review')
    return (
      <div className={box}>
        <span className="pill bg-wine-tint text-wine">{t('Under review by reltix')}</span>
        <h2 className="mt-3 text-title font-medium">{t('Thanks, {name}. We are checking your documents.', { name: p.name })}</h2>
        <p className="mt-2 text-secondary">{t('A reltix property manager checks your licence and insurance. You get jobs as soon as you are approved. This usually takes less than a working day.')}</p>
      </div>
    )
  if (p.status === 'rejected')
    return (
      <div className={box}>
        <span className="pill bg-beige text-secondary">{t('Not approved')}</span>
        <h2 className="mt-3 text-title font-medium">{t('reltix could not approve {name} yet', { name: p.name })}</h2>
        {reason && (
          <p className="mt-2">
            <b>{t('Reason')}:</b> {reason}
          </p>
        )}
        <p className="mt-2 text-secondary">
          {[p.review?.reviewer, p.review?.decided_at ? fmtRelative(p.review.decided_at) : null].filter(Boolean).join(' · ')}
        </p>
        <p className="mt-2 text-secondary">{t('Fix the points above and register again with the same company name.')}</p>
      </div>
    )
  return (
    <div className={box}>
      <span className="pill bg-warn-tint text-warn">{t('Suspended')}</span>
      <h2 className="mt-3 text-title font-medium">{t('{name} gets no new jobs right now', { name: p.name })}</h2>
      {reason && <p className="mt-2">{reason}</p>}
      <p className="mt-2 text-secondary">{t('Send reltix a current certificate and we switch you back on.')}</p>
    </div>
  )
}
