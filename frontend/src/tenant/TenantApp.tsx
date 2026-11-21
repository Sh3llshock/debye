// Tenant portal (designs-v3/tenant-portal1.html) with the real Debye behind the chat.
// Routes: /tenant (home), /tenant/chat (current conversation, before a case exists), /tenant/case/:id
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Route, Routes, useNavigate } from 'react-router-dom'
import { t, useLang } from '../lib/i18n'
import { useStream } from '../lib/stream'
import { ApiError, api, getToken, setToken, type TCase, type TMe } from './api'
import { Ctx } from './shell'
import Chat from './Chat'
import Home from './Home'
import Login from './Login'
import './tenant.css'

function useTitle() {
  useEffect(() => {
    const prev = document.title
    document.title = 'Debye · ' + t('Help with your home')
    return () => {
      document.title = prev
    }
  }, [])
}

function Portal({ onLogout }: { onLogout: () => void }) {
  const [me, setMe] = useState<TMe | null>(null)
  const [cases, setCases] = useState<TCase[]>([])
  const [tick, setTick] = useState(0)
  const [failed, setFailed] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  const refresh = useCallback(() => {
    Promise.all([api.me(), api.cases()])
      .then(([m, c]) => {
        setMe(m)
        setCases(c)
        setFailed(false)
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) onLogout()
        else setFailed(true)
      })
  }, [onLogout])

  const bump = useCallback(() => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      refresh()
      setTick((n) => n + 1)
    }, 250)
  }, [refresh])

  useEffect(() => {
    refresh()
    const iv = window.setInterval(bump, 6000) // fallback if the live stream drops
    return () => window.clearInterval(iv)
  }, [refresh, bump])

  const caseIds = useMemo(() => new Set(cases.map((c) => c.case_id)), [cases])
  useStream((m) => {
    if (!me) return
    const ev = (m.event ?? {}) as Record<string, unknown>
    if (m.type === 'demo.reset' || ev.contact_id === me.contact.contact_id || (m.case_id && caseIds.has(m.case_id)) || m.type === 'case.created') bump()
  })

  if (!me)
    return (
      <div className="login">
        <div className="lbox">
          <div className="logo" />
          <p>{failed ? t('Could not reach Debye. Retrying…') : t('Loading')}</p>
        </div>
      </div>
    )
  return (
    <Ctx.Provider value={{ me, cases, tick, refresh: bump, logout: onLogout }}>
      <Routes>
        <Route index element={<Home />} />
        <Route path="chat" element={<Chat />} />
        <Route path="case/:caseId" element={<Chat />} />
        <Route path="*" element={<Home />} />
      </Routes>
    </Ctx.Provider>
  )
}

export default function TenantApp() {
  useLang()
  useTitle()
  const [token, setTok] = useState(getToken())
  const nav = useNavigate()
  const logout = useCallback(() => {
    setToken(null)
    setTok(null)
    nav('/tenant', { replace: true })
  }, [nav])
  return (
    <div className="tp">
      {token ? (
        <Portal onLogout={logout} />
      ) : (
        <Login
          onLogin={(tok) => {
            setToken(tok)
            setTok(tok)
            nav('/tenant', { replace: true })
          }}
        />
      )}
    </div>
  )
}
