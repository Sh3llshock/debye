// /partners/join is replaced by the v3 "Register your company" flow at /partner/register
// (pages/partner/Welcome.tsx), which still posts to POST /api/partners/onboard.
import { Navigate } from 'react-router-dom'

export default function PartnerJoin() {
  return <Navigate to="/partner/register" replace />
}
