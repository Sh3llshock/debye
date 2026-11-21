import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { t } from '../lib/i18n'
import { api, type TCase } from './api'
import type { HomeState } from './Chat'
import { fmtDay, isClosed, stepIndex, stepShort, solvedWithoutTech } from './progress'
import { TopBar, usePortal } from './shell'

export function MiniBar({ c }: { c: TCase }) {
  const k = stepIndex(c)
  return (
    <div className="mini">
      {Array.from({ length: 8 }, (_, i) => (
        <i key={i} className={i < k ? 'd' : i === k ? 'n' : ''} />
      ))}
    </div>
  )
}

let DRAFT = '' // survives navigating away and back, like the mockup

export default function Home() {
  const { me, cases, refresh, tick } = usePortal()
  const [chats, setChats] = useState<{ id: string; title: string; started_at: string }[]>([])
  useEffect(() => {
    api.chats().then(setChats).catch(() => setChats([]))
  }, [tick])
  const nav = useNavigate()
  const [text, setText] = useState(DRAFT)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const ta = useRef<HTMLTextAreaElement>(null)
  useEffect(() => ta.current?.focus(), [])

  const open = cases.filter((c) => !isClosed(c))
  const closed = cases.filter((c) => isClosed(c))
  const SUGG: [string, string][] = [
    [t('No hot water'), t('My shower’s broken, there’s no hot water.')],
    [t('Shower only runs cold'), t('My shower only runs cold.')],
    [t('Weak shower'), t('The shower has almost no water pressure.')],
  ]

  const start = async (v: string) => {
    v = v.trim()
    if (!v) return ta.current?.focus()
    setBusy(true)
    setErr('')
    try {
      // what the current conversation already has, so the chat knows which reply is new
      // a new chat starts empty, so every message after this one is new
      const count = 0
      const ins = 0
      await api.send({ text: v, newCase: true })  // a new problem from home always starts a new chat
      DRAFT = ''
      setText('')
      refresh()
      const state: HomeState = { optimistic: v, sentAt: Date.now(), count, ins }
      nav('/tenant/chat', { state })
    } catch {
      setErr(t('Could not send. Please try again.'))
    } finally {
      setBusy(false)
    }
  }

  const caseList = (
            <div className="opencases">
              <h3>{t('Open cases')}</h3>
              {open.length ? (
                <div className="ocgrid">
                  {open.map((c) => (
                    <button key={c.case_id} className="oc" onClick={() => nav(`/tenant/case/${c.case_id}`)}>
                      <b>{c.title}</b>
                      <span>
                        {t('Case {id}', { id: c.case_id })} · {t('opened {when}', { when: fmtDay(c.created_at) })}
                      </span>
                      <br />
                      <span className="ostep">{stepShort(c)}</span>
                      <MiniBar c={c} />
                    </button>
                  ))}
                </div>
              ) : (
                <p style={{ color: 'var(--muted)', margin: 0 }}>{t('No open cases. Anything you report here or on WhatsApp shows up here.')}</p>
              )}
              {chats.length > 0 && (
                <div className="closedlist">
                  <h3>{t('Earlier chats')}</h3>
                  {chats.map((ch) => (
                    <button key={ch.id} className="cl" onClick={() => nav(`/tenant/chat/${ch.id}`)}>
                      <b style={{ fontWeight: 500 }}>{ch.title}</b>
                      <span>{fmtDay(ch.started_at)}</span>
                    </button>
                  ))}
                </div>
              )}
              {closed.length > 0 && (
                <div className="closedlist">
                  <h3>{t('Closed cases')}</h3>
                  {closed.map((c) => (
                    <button key={c.case_id} className="cl" onClick={() => nav(`/tenant/case/${c.case_id}`)}>
                      <b style={{ fontWeight: 500 }}>{c.title}</b>
                      <span>
                        {solvedWithoutTech(c) ? t('Fixed') : t('Closed')} · {c.case_id}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
  )

  return (
    <div className="shell">
      <TopBar sel={null} />
      <div className="app">
        <main>
          <div className="homewrap">
            {open.length > 0 && caseList}
            <div className="hello">
              <div className="logo" />
              <h1>{open.length ? t('Something else wrong at home, {name}?', { name: me.contact.first_name }) : t('What’s wrong at home, {name}?', { name: me.contact.first_name })}</h1>
              <p>{t('Describe what you see in your own words. Debye already knows your flat and its appliances.')}</p>
            </div>
            <div className="bigin">
              <textarea
                ref={ta}
                value={text}
                placeholder={t('For example: the shower only runs cold')}
                onChange={(e) => {
                  setText(e.target.value)
                  DRAFT = e.target.value
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    start(text)
                  }
                }}
              />
              <div className="binrow">
                <span className="hint">{t('Debye already knows your flat and its appliances')}</span>
                <button className="sendc" aria-label={t('Send')} disabled={busy} onClick={() => start(text)}>
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square" aria-hidden>
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                </button>
              </div>
            </div>
            {err && <div className="err">{err}</div>}
            <div className="sugg">
              {SUGG.map(([label, said]) => (
                <button key={label} disabled={busy} onClick={() => start(said)}>
                  {label}
                </button>
              ))}
            </div>
            {open.length === 0 && caseList}
          </div>
        </main>
      </div>
    </div>
  )
}
