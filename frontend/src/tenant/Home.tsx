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

const greet = () => {
  const h = new Date().getHours()
  return h < 12 ? t('Good morning') : h < 18 ? t('Good afternoon') : t('Good evening')
}

let DRAFT = '' // survives navigating away and back, like the mockup

export default function Home() {
  const { me, cases, refresh } = usePortal()
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
      const before = await api.messages().catch(() => null)
      const count = before?.messages.length ?? 0
      const ins = before?.messages.filter((m) => m.direction === 'in').length ?? 0
      await api.send({ text: v })
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

  return (
    <div className="shell">
      <TopBar sel={null} />
      <div className="app">
        <main>
          <div className="homewrap">
            <div className="hello">
              <div className="logo" />
              <h1>
                {greet()}, {me.contact.first_name}.
              </h1>
              <p>{t('I’m Debye. What problem do you have at home?')}</p>
            </div>
            <div className="bigin">
              <textarea
                ref={ta}
                value={text}
                placeholder={t('Please enter your problem, e.g. “My shower only runs cold.”')}
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
                <span className="hint">{t('I already know your address and your appliances.')}</span>
                <button className="sendc" aria-label={t('Send')} disabled={busy} onClick={() => start(text)}>
                  ➤
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
          </div>
        </main>
      </div>
    </div>
  )
}
