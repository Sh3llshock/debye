import { useState } from 'react'

type Done = { debye_whatsapp: string; wa_link: string }

// /tryDebye: a judge or visitor registers their phone as a demo tenant, then writes to Debye on WhatsApp.
export default function TryDebye() {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [consent, setConsent] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<Done | null>(null)

  const submit = async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await fetch('/api/try/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, phone, consent }),
      })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'Something went wrong. Please try again.')
      setDone(j as Done)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not reach Debye. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-start justify-center bg-bg px-4 py-12 sm:items-center">
      <div className="w-full max-w-[440px] rounded-[4px] border border-[color:var(--line)] bg-surface p-6 sm:p-8">
        <div className="mb-6 flex items-center gap-2">
          <img src="/brand/debye-logo.png" alt="" className="h-6 w-6" />
          <span className="font-medium text-ink">Debye</span>
          <span className="text-[13px] text-muted">by reltix</span>
        </div>

        {!done ? (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              submit()
            }}
            className="grid gap-4"
          >
            <div>
              <h1 className="text-[28px] leading-[34px]">Try Debye on WhatsApp</h1>
              <p className="mt-2 text-[15px] leading-[23px] text-body">
                Enter your number and you become a tenant in our demo flat (Musterstraße 12, 2A). Then tell Debye
                what's broken at home, like "my shower is cold" or "water is dripping from the ceiling".
              </p>
            </div>
            <label className="grid gap-1 text-[13px] text-muted">
              First name
              <input className="h-11 border border-[color:var(--line)] px-3 text-[15px]" value={name}
                onChange={(e) => setName(e.target.value)} autoComplete="given-name" placeholder="Anna" required />
            </label>
            <label className="grid gap-1 text-[13px] text-muted">
              WhatsApp number, with country code
              <input className="h-11 border border-[color:var(--line)] px-3 text-[15px]" type="tel" value={phone}
                onChange={(e) => setPhone(e.target.value)} autoComplete="tel" placeholder="+49 151 2345 6789" required />
            </label>
            <label className="flex items-start gap-2 text-[13px] leading-[19px] text-body">
              <input type="checkbox" className="mt-[3px] accent-[color:var(--wine)]" checked={consent}
                onChange={(e) => setConsent(e.target.checked)} />
              Debye may reply to me on WhatsApp for this demo. My number is only used for the demo.
            </label>
            {err && <div className="text-[13px] text-[color:var(--red)]">{err}</div>}
            <button type="submit" disabled={busy}
              className="h-11 rounded-[3px] border-b-2 border-[color:var(--wine-d)] bg-wine px-4 font-medium text-[color:var(--cream)] active:translate-y-px disabled:opacity-60">
              {busy ? 'Registering…' : 'Register my number'}
            </button>
          </form>
        ) : (
          <div className="grid gap-4">
            <h1 className="text-[28px] leading-[34px]">You're in, {name.trim().split(' ')[0]}.</h1>
            <p className="text-[15px] leading-[23px] text-body">
              Message Debye on WhatsApp at <b className="text-ink">{done.debye_whatsapp}</b> and describe a problem in
              your flat. Debye asks a few short questions and, if a craftsman is needed, the property manager gets an
              approval email.
            </p>
            <a href={done.wa_link} target="_blank" rel="noreferrer"
              className="flex h-11 items-center justify-center rounded-[3px] border-b-2 border-[color:var(--wine-d)] bg-wine px-4 font-medium text-[color:var(--cream)]">
              Open WhatsApp
            </a>
            <p className="text-[13px] text-muted">Try: "my shower is cold", "toilet is blocked", "mould in the bathroom".</p>
          </div>
        )}
      </div>
    </div>
  )
}
