import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { t } from '../lib/i18n'
import { ApiError, api, type TCaseDetail, type THistory, type THome, type TMessage, type TOption } from './api'
import { MiniBar } from './Home'
import { fmtDay, fmtSlot, fmtTime, isClosed, isEmergency, stageLabel, steps, solvedWithoutTech } from './progress'
import { TopBar, floorLabel, usePortal } from './shell'

/** WhatsApp-style *bold* → <b>, newlines kept by CSS (pre-wrap). */
function rich(text: string): ReactNode {
  const parts = text.split(/\*([^*\n]+)\*/g)
  return parts.map((p, i) => (i % 2 ? <b key={i}>{p}</b> : <Fragment key={i}>{p}</Fragment>))
}

interface Local {
  key: string
  ins: number // server 'in' messages when it was sent; dropped once the server has more
  text?: string
  preview?: string // object URL of a photo being sent
  at: number
}

export interface HomeState {
  optimistic: string
  sentAt: number
  count: number
  ins: number
}

const WAIT_MS = 60_000
const PHOTO_ASK = /\b(photo|picture|foto|bild)\b/i

export default function Chat() {
  const { caseId, chatId } = useParams()
  const { me, tick, refresh } = usePortal()
  const nav = useNavigate()
  const loc = useLocation()
  const [hist, setHist] = useState<THistory | null>(null)
  const [detail, setDetail] = useState<TCaseDetail | null>(null)
  const [locals, setLocals] = useState<Local[]>(() => {
    const st = loc.state as HomeState | null
    return st?.optimistic ? [{ key: 'home', text: st.optimistic, at: st.sentAt, ins: st.ins }] : []
  })
  const [waitingSince, setWaitingSince] = useState<number | null>(() => (loc.state as HomeState | null)?.sentAt ?? null)
  const [baseline, setBaseline] = useState<number>(() => (loc.state as HomeState | null)?.count ?? 0) // messages before we sent
  const [draft, setDraft] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [sendErr, setSendErr] = useState('')
  const thread = useRef<HTMLDivElement>(null)
  const atBottom = useRef(true)
  const photoInput = useRef<HTMLInputElement>(null)
  const ta = useRef<HTMLTextAreaElement>(null)

  const load = useCallback(async () => {
    try {
      const h = await api.messages(caseId, chatId)
      if (!caseId && !chatId && h.case_id) {
        nav(`/tenant/case/${h.case_id}`, { replace: true, state: loc.state })
        return
      }
      setHist(h)
      if (caseId) setDetail(await api.case(caseId))
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) nav('/tenant', { replace: true })
    }
  }, [caseId, chatId, nav, loc.state])

  useEffect(() => {
    load()
  }, [load, tick])
  // while Debye is thinking, poll a bit faster than the portal-wide fallback
  useEffect(() => {
    if (waitingSince == null) return
    const iv = window.setInterval(load, 2000)
    return () => window.clearInterval(iv)
  }, [waitingSince, load])

  const msgs = hist?.messages ?? []
  // reconcile optimistic bubbles and the typing indicator with what the server has
  useEffect(() => {
    if (!hist) return
    const ins = msgs.filter((m) => m.direction === 'in').length
    setLocals((ls) => (ls.length ? ls.filter((l) => ins <= l.ins && Date.now() - l.at < WAIT_MS) : ls))
    if (waitingSince != null) {
      const replied = msgs.slice(baseline).some((m) => m.direction === 'out')
      if (replied || Date.now() - waitingSince > WAIT_MS) setWaitingSince(null)
    }
  }, [hist])

  useLayoutEffect(() => {
    const el = thread.current
    if (el && atBottom.current) el.scrollTop = el.scrollHeight
  })
  useEffect(() => {
    atBottom.current = true
  }, [caseId])

  useEffect(() => {
    if (!file) return setPreview(null)
    const u = URL.createObjectURL(file)
    setPreview(u)
    return () => URL.revokeObjectURL(u)
  }, [file])

  const send = async (m: { text?: string; option?: TOption; file?: File | null }) => {
    const text = m.option ? m.option.title : m.text?.trim()
    if (!text && !m.file) return
    setSendErr('')
    const ins = msgs.filter((x) => x.direction === 'in').length
    const local: Local = { key: Math.random().toString(36), ins, text, preview: m.file ? URL.createObjectURL(m.file) : undefined, at: Date.now() }
    setLocals((ls) => [...ls, local])
    setBaseline(msgs.length)
    setWaitingSince(Date.now())
    atBottom.current = true
    try {
      await api.send({ text: m.option ? undefined : text, buttonId: m.option?.id, buttonTitle: m.option?.title, file: m.file })
      refresh()
    } catch {
      setLocals((ls) => ls.filter((l) => l !== local))
      setWaitingSince(null)
      setSendErr(t('Could not send. Please try again.'))
    }
  }

  const submit = () => {
    if (!draft.trim() && !file) return
    send({ text: draft, file })
    setDraft('')
    setFile(null)
    if (ta.current) ta.current.style.height = ''
  }

  const earlier = !!chatId // an earlier web chat that never became a case: read-only
  const closed = earlier || (detail ? isClosed(detail) : false)
  const current = hist?.current ?? !caseId
  const pending = current && waitingSince == null && !closed ? hist?.pending : null
  const lastOut = [...msgs].reverse().find((m) => m.direction === 'out')
  const lastIsOut = msgs.length > 0 && msgs[msgs.length - 1].direction === 'out'
  const askPhoto = current && !closed && waitingSince == null && !pending && lastIsOut && !!lastOut?.text && PHOTO_ASK.test(lastOut.text)
  const [label, tone] = detail ? stageLabel(detail) : [t('Diagnosis'), '' as const]
  const title = detail?.title || t('New conversation')

  return (
    <div className="shell">
      <TopBar sel={caseId ?? null} />
      <div className={`app ${detail ? 'withpanel' : ''}`}>
        <main>
          <div className="topline">
            <button className="back" onClick={() => nav('/tenant')} title={t('Home')}>
              ‹
            </button>
            <div>
              <b>{title}</b>
              <br />
              <span>{detail ? `${t('Case {id}', { id: detail.case_id })} · ${t('opened {when}', { when: fmtDay(detail.created_at) })}` : t('Debye is looking into it')}</span>
              {detail && (
                <div className="tmini">
                  <MiniBar c={detail} />
                </div>
              )}
            </div>
            <span className={`stpill ${tone}`}>{label}</span>
          </div>
          <div
            className="thread"
            ref={thread}
            onScroll={(e) => {
              const el = e.currentTarget
              atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
            }}
          >
            <div className="inner">
              {msgs.map((m) => (
                <Bubble key={m.id} m={m} />
              ))}
              {locals.map((l) => (
                <div className="row me" key={l.key}>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', maxWidth: '75%' }}>
                    <div className="ubub">
                      {l.preview && <img src={l.preview} alt={t('Photo')} />}
                      {l.text && <span>{l.text}</span>}
                    </div>
                    <div className="meta">{fmtTime(new Date(l.at).toISOString())}</div>
                  </div>
                </div>
              ))}
              {waitingSince != null && (
                <div className="row">
                  <div className="bav" />
                  <div>
                    <div className="btext" aria-label={t('Debye is typing')}>
                      <div className="bname">Debye</div>
                      <span className="typing">
                        <i />
                        <i />
                        <i />
                      </span>
                    </div>
                  </div>
                </div>
              )}
              {pending && pending.options.length > 0 && (
                <div className="actions">
                  {pending.options.map((o, n) => (
                    <button key={o.id} className={`chip ${n === 0 ? 'solid' : ''}`} onClick={() => send({ option: o })}>
                      {o.title}
                    </button>
                  ))}
                </div>
              )}
              {askPhoto && (
                <div className="actions">
                  <button className="chip solid" onClick={() => photoInput.current?.click()}>
                    📷 {t('Upload photo')}
                  </button>
                </div>
              )}
              {msgs.length === 0 && locals.length === 0 && waitingSince == null && (
                <p style={{ color: 'var(--muted)', textAlign: 'center' }}>{t('No messages yet.')}</p>
              )}
            </div>
          </div>
          <input
            ref={photoInput}
            type="file"
            accept="image/*"
            style={{ display: 'none' }}
            onChange={(e) => {
              const f = e.target.files?.[0]
              e.target.value = ''
              if (f) send({ file: f })
            }}
          />
          {closed ? (
            <div className="composer">
              <div className="closedbar">
                <span>
                  {earlier
                    ? t('This is an earlier chat. Something else broken?')
                    : detail && (solvedWithoutTech(detail) || detail.status === 'closed')
                    ? t('This case is closed. Something else broken?')
                    : t('This case is with your property manager. Something else broken?')}
                </span>
                <button onClick={() => nav('/tenant')}>{t('Report a new problem')}</button>
              </div>
            </div>
          ) : (
            <form
              className="composer"
              onSubmit={(e) => {
                e.preventDefault()
                submit()
              }}
            >
              {sendErr && <div className="sendfail">{sendErr}</div>}
              {preview && (
                <div className="cfile">
                  <img src={preview} alt="" />
                  <span>{file?.name}</span>
                  <button type="button" onClick={() => setFile(null)}>
                    {t('Remove')}
                  </button>
                </div>
              )}
              <div className="cin">
                <label className="att" title={t('Add a photo')}>
                  📎
                  <input
                    type="file"
                    accept="image/*"
                    style={{ display: 'none' }}
                    onChange={(e) => {
                      setFile(e.target.files?.[0] ?? null)
                      e.target.value = ''
                    }}
                  />
                </label>
                <textarea
                  ref={ta}
                  rows={1}
                  value={draft}
                  placeholder={t('Message Debye…')}
                  onChange={(e) => {
                    setDraft(e.target.value)
                    e.target.style.height = ''
                    e.target.style.height = Math.min(e.target.scrollHeight, 140) + 'px'
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      submit()
                    }
                  }}
                />
                <button className="sendc" type="submit" aria-label={t('Send')} disabled={!draft.trim() && !file}>
                  ➤
                </button>
              </div>
              <div className="cnote">{t('Same conversation as your WhatsApp with Debye. Answer wherever is easier.')}</div>
            </form>
          )}
        </main>
        {detail && <Progress c={detail} home={me.home} />}
      </div>
    </div>
  )
}

function Bubble({ m }: { m: TMessage }) {
    if (m.direction === 'in')
      return (
        <div className="row me">
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', maxWidth: '75%' }}>
            <div className="ubub">
              {m.media.map((d) =>
                d.mime.startsWith('image/') ? (
                  <img key={d.document_id} src={d.url} alt={t('Photo')} />
                ) : (
                  <a key={d.document_id} href={d.url} target="_blank" rel="noreferrer" style={{ color: 'inherit' }}>
                    📎 {d.kind === 'voice_note' ? t('Voice note') : t('File')}
                  </a>
                ),
              )}
              {m.text && <span>{m.text}</span>}
            </div>
            <div className="meta">
              {fmtTime(m.ts)}
              {m.channel === 'whatsapp' && <span className="via">{t('via WhatsApp')}</span>}
              {m.channel === 'voice' && <span className="via">{t('by phone')}</span>}
            </div>
          </div>
        </div>
      )
    return (
      <div className="row">
        <div className="bav" />
        <div>
          <div className="btext">
            <div className="bname">Debye</div>
            {m.media.map((d) =>
              d.mime.startsWith('image/') ? <img key={d.document_id} src={d.url} alt="" style={{ marginBottom: 8 }} /> : null,
            )}
            {rich(m.text || '')}
          </div>
          <div className="meta">{fmtTime(m.ts)}</div>
        </div>
      </div>
    )
  }

  function Progress({ c, home }: { c: TCaseDetail; home: THome | null }) {
    const rows = useMemo(() => steps(c, home), [c, home])
    const appliance = c.asset ?? home?.assets[0]
    const report = c.documents.find((d) => d.kind === 'report' || d.kind === 'invoice')
    return (
      <aside className="tp-panel">
        <h2>{c.title}</h2>
        <div className="psub">
          {t('Case {id}', { id: c.case_id })}
          {home?.address ? ` · ${home.address.split(',')[0]}${home.floor != null ? ', ' + floorLabel(home.floor) : ''}` : ''}
        </div>
        <ol className="flow">
          {rows.map((r, n) => (
            <li key={n} className={r.state}>
              <span className="fd">{r.state === 'done' ? '✓' : n + 1}</span>
              <div className="ft">
                <b>{r.title}</b>
                {r.sub && <small>{r.sub}</small>}
              </div>
            </li>
          ))}
        </ol>
        {c.diagnosis?.label && !isEmergency(c) && (
          <div className="pbox">
            <h4>{t('What we found')}</h4>
            <b>{c.diagnosis.label}</b>
            {c.diagnosis.confidence != null && (
              <div className="bar">
                <i style={{ width: `${Math.round(c.diagnosis.confidence <= 1 ? c.diagnosis.confidence * 100 : c.diagnosis.confidence)}%` }} />
              </div>
            )}
            {c.error_code && (
              <div className="meta" style={{ marginTop: 0 }}>
                {t('Display')}: {c.error_code}
                {c.error_label ? ` · ${c.error_label}` : ''}
              </div>
            )}
          </div>
        )}
        {c.technician_name && (
          <div className={`pbox ${c.slot && ['scheduled', 'completed', 'invoiced', 'closed'].includes(c.status) ? 'good' : ''}`}>
            <h4>{t('Technician')}</h4>
            <div className="big">
              <div className="tav" style={{ width: 36, height: 36 }}>
                {c.technician_name[0]}
              </div>
              <div>
                <b style={{ fontSize: 14 }}>{c.technician_name}</b>
                <span style={{ fontSize: 13 }}>
                  {c.partner_name}
                  {c.slot ? ` · ${fmtSlot(c.slot)}` : ''}
                </span>
              </div>
            </div>
          </div>
        )}
        {report && (
          <div className="pbox">
            <h4>{t('Documents')}</h4>
            {c.documents
              .filter((d) => d.kind !== 'photo')
              .map((d) => (
                <div key={d.document_id}>
                  <a href={d.url} target="_blank" rel="noreferrer">
                    📄 {d.filename}
                  </a>
                </div>
              ))}
          </div>
        )}
        <div className="pbox">
          <h4>{t('Your home')}</h4>
          <dl>
            {appliance && (
              <>
                <dt>{t('Appliance')}</dt>
                <dd>{[appliance.make, appliance.model].filter(Boolean).join(' ') || appliance.type}</dd>
              </>
            )}
            {appliance?.last_service && (
              <>
                <dt>{t('Last service')}</dt>
                <dd>{new Date(appliance.last_service).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}</dd>
              </>
            )}
            {home?.landlord && (
              <>
                <dt>{t('Landlord')}</dt>
                <dd>{home.landlord}</dd>
              </>
            )}
          </dl>
        </div>
      </aside>
    )
}
