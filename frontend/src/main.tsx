import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import './index.css'
import { initStageScale } from './lib/stage'

initStageScale()
import { StaffLayout } from './components/Layout'
import { RequireLogin } from './components/RequireLogin'
import StaffCases from './pages/StaffCases'
import StaffInbox from './pages/StaffInbox'
import StaffCase from './pages/StaffCase'
import StaffUnit, { StaffUnits } from './pages/StaffUnit'
import PartnerPage, { PartnerLogin, PartnerRegister, PartnerWelcome } from './pages/PartnerInbox'
import TechPage from './pages/TechPage'
import StaffPartners, { StaffPartner } from './pages/StaffPartners'
import PartnerJoin from './pages/PartnerJoin'
import TenantApp from './tenant/TenantApp'
import { t, useLang } from './lib/i18n'

function Staff() {
  return (
    <StaffLayout>
      <Outlet />
    </StaffLayout>
  )
}

function NotFound() {
  return (
    <div className="p-8 text-center">
      <h1 className="text-page">{t('Page not found')}</h1>
      <a className="mt-4 inline-block text-action underline" href="/staff">
        {t('Go to cases')}
      </a>
    </div>
  )
}

function App() {
  useLang() // re-render everything when EN/DE changes
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/staff" replace />} />
        <Route path="/staff" element={<RequireLogin role="staff"><Staff /></RequireLogin>}>
          <Route index element={<StaffInbox />} />
          <Route path="cases" element={<StaffCases />} />
          <Route path="cases/:caseId" element={<StaffCase />} />
          <Route path="properties" element={<Navigate to="/staff/units" replace />} />
          <Route path="units" element={<StaffUnits />} />
          <Route path="units/:unitId" element={<StaffUnit />} />
          <Route path="partners" element={<StaffPartners />} />
          <Route path="partners/:partnerId" element={<StaffPartner />} />
        </Route>
        <Route path="/partners" element={<Navigate to="/staff/partners" replace />} />
        <Route path="/partners/join" element={<PartnerJoin />} />
        <Route path="/partner" element={<PartnerWelcome />} />
        <Route path="/partner/login" element={<PartnerLogin />} />
        <Route path="/partner/register" element={<PartnerRegister />} />
        <Route path="/partner/:partnerId" element={<RequireLogin role="partner"><PartnerPage /></RequireLogin>} />
        <Route path="/partner/:partnerId/new" element={<RequireLogin role="partner"><PartnerPage tab="new" /></RequireLogin>} />
        <Route path="/partner/:partnerId/wip" element={<RequireLogin role="partner"><PartnerPage tab="wip" /></RequireLogin>} />
        <Route path="/partner/:partnerId/availability" element={<RequireLogin role="partner"><PartnerPage tab="availability" /></RequireLogin>} />
        <Route path="/partner/:partnerId/done" element={<RequireLogin role="partner"><PartnerPage tab="done" /></RequireLogin>} />
        <Route path="/partner/:partnerId/profile" element={<RequireLogin role="partner"><PartnerPage tab="profile" /></RequireLogin>} />
        <Route path="/partner/:partnerId/jobs/:caseId" element={<RequireLogin role="partner"><PartnerPage /></RequireLogin>} />
        <Route path="/tenant/*" element={<TenantApp />} />
        <Route path="/tech/:techId" element={<RequireLogin role="tech"><TechPage /></RequireLogin>} />
        <Route path="/tech/:techId/jobs/:caseId" element={<RequireLogin role="tech"><TechPage /></RequireLogin>} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
