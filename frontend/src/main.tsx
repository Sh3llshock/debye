import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import './index.css'
import { initStageScale } from './lib/stage'

initStageScale()
import { StaffLayout } from './components/Layout'
import StaffCases from './pages/StaffCases'
import StaffCase from './pages/StaffCase'
import StaffUnit, { StaffUnits } from './pages/StaffUnit'
import PartnerPage from './pages/PartnerInbox'

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
      <h1 className="text-page">Page not found</h1>
      <a className="mt-4 inline-block text-action underline" href="/staff">Go to cases</a>
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/staff" replace />} />
        <Route path="/staff" element={<Staff />}>
          <Route index element={<StaffCases />} />
          <Route path="cases/:caseId" element={<StaffCase />} />
          <Route path="units" element={<StaffUnits />} />
          <Route path="units/:unitId" element={<StaffUnit />} />
        </Route>
        <Route path="/partner" element={<Navigate to="/partner/heizung-schmidt" replace />} />
        <Route path="/partner/:partnerId" element={<PartnerPage />} />
        <Route path="/partner/:partnerId/jobs/:caseId" element={<PartnerPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
)
