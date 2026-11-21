# Running Debye, step by step

This gets Debye running on a laptop: backend, web pages (staff, partner, tenant), demo data,
and optionally real WhatsApp, a public link, email approvals and voice calls.
Commands are for Windows PowerShell; on macOS/Linux use `/` paths and `source .venv/bin/activate`.

## 1. What you need

- **Python 3.13** and **Node.js 22** (check with `python --version` and `node --version`)
- **git**
- An **OpenAI API key** (the AI runs on `gpt-6-luna` via the EU endpoint). Without a key Debye
  still runs, but answers with scripted fallbacks instead of the AI.
- Optional: a spare phone with WhatsApp (real WhatsApp), `cloudflared` (public link),
  an AgentMail key (approval emails), an ElevenLabs key (voice).

## 2. Get the code

```powershell
git clone https://github.com/Sh3llshock/debye.git
cd debye
```

## 3. Settings (`.env`)

```powershell
copy .env.example .env
```

Open `.env` and fill in at least:

| Setting | What to put |
|---|---|
| `OPENAI_API_KEY` | your OpenAI key |
| `LLM_PROVIDER` | `openai` |
| `DEMO_MODE` | `1` (enables demo login, the demo panel and the reset buttons) |

Everything else is optional and explained in the sections below. `.env` is gitignored; never commit it.

## 4. Backend

```powershell
cd backend
python -m pip install -r requirements.txt
```

## 5. Web pages (frontend)

```powershell
cd ..\frontend
npm ci
npm run build
```

The build lands in `frontend/dist`, and the backend serves it, so there is only one server to run.

## 6. Start Debye

```powershell
cd ..\backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Leave this window open. In a second window, load the demo data (cases, partners, technicians):

```powershell
curl.exe -X POST http://localhost:8000/demo/scenarios
```

## 7. Open the pages

| Who | Link | Login |
|---|---|---|
| Staff (property management) | http://localhost:8000/staff | none |
| Partner (Heizung Schmidt, jobs waiting + history) | http://localhost:8000/partner/heizung-schmidt/new | demo login, any password |
| Partner sign-up | http://localhost:8000/partner/register | none |
| Tenant portal (chat with Debye) | http://localhost:8000/tenant | `luka@example.com` or `jona.weber@example.com`, any password |
| Technician phone page | http://localhost:8000/tech/tech_ali | none |
| Try Debye (register a phone as a demo tenant) | http://localhost:8000/tryDebye | none |
| Web voice call | http://localhost:8000/call | needs ElevenLabs (section 11) |

On the staff page press **`d`** for the demo panel (reset, skip to tomorrow, triggers such as a boiler
error that makes Debye message the tenant first). Add `?stage=1` to any page for bigger text on a projector.

That's the full web demo. The sections below add the real-world channels.

## 8. Real WhatsApp (optional)

Debye talks WhatsApp through a small bridge that links a spare phone like WhatsApp Web.

1. In `.env` set `WA_PROVIDER=wweb`, a random `WWEB_SECRET`, and `WWEB_BRIDGE_URL=http://127.0.0.1:3010`.
2. Start the bridge in a third window:
   ```powershell
   cd bridge
   npm ci
   npm start
   ```
3. A QR code appears in the window. On the spare phone: WhatsApp → Settings → Linked devices →
   Link a device, and scan it. The session is kept in `bridge/auth/`, so you only scan once.
4. Restart the backend (step 6) so it picks up the settings.
5. Tenants are recognised by phone number. Put real numbers in `data/seed.local.json` (gitignored), e.g.
   ```json
   {"contacts": [{"id": "c_202", "phone_e164": "+49151..."}]}
   ```
   or let people register themselves on `/tryDebye`.

More background: `docs/whatsapp-setup.md`. Twilio and the Meta Cloud API are also supported (`WA_PROVIDER`).

## 9. Public link (optional, needed for email buttons, phones and voice)

```powershell
cloudflared tunnel --url http://localhost:8000
```

Copy the `https://….trycloudflare.com` address it prints into `.env` as `PUBLIC_BASE_URL`, then restart the backend.

## 10. Approval emails (optional)

When Debye wants to book a craftsman, staff get an email with the reasoning and one-click
Confirm / Don't do it / More information links (no login needed). In `.env`:

- `AGENTMAIL_API_KEY`, `AGENTMAIL_INBOX` (sender), `STAFF_APPROVAL_EMAIL` (recipient)
- `EMAIL_LINK_SECRET` (any random string) and `PUBLIC_BASE_URL` (section 9)

Loading the demo data never sends emails; only real chats do.

## 11. Voice call (optional)

Set `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID` and `VOICE_TOOL_SECRET` in `.env`, have the public link
running (section 9), then point the voice agent at it:

```powershell
python scripts\elevenlabs_agent.py --base https://<your-tunnel>.trycloudflare.com
```

Run it again whenever the tunnel address changes. Details: `docs/voice-setup.md`.

## 12. Partner with its own system (optional)

To show the API partner (signed orders and status updates), set `PARTNER_API_SECRET` in `.env` and run
the fake partner next to the backend:

```powershell
python scripts\fake_partner.py --port 8100 --debye http://localhost:8000
```

## 13. Check that everything works

```powershell
cd backend
python -m pytest -q
cd ..
$env:PYTHONIOENCODING="utf-8"; python scripts\smoke_diagnosis.py
$env:PYTHONIOENCODING="utf-8"; python scripts\smoke_triage.py
```

The smoke scripts play short real-world chats against the real AI (they need `OPENAI_API_KEY`) and
check the hard rules: right first question, no repeated messages, one question per message, no invented facts.
To replay the whole demo end to end on a running server: `python scripts\simulate.py --reset`.

## 14. Reset before a demo

Press `d` on the staff page → reset, or:

```powershell
curl.exe -X POST http://localhost:8000/demo/scenarios
```

This wipes all cases and reloads the demo data. People who registered on `/tryDebye` are kept.

## Troubleshooting

| Problem | Fix |
|---|---|
| Page shows `frontend/dist not built` | Run step 5, then restart the backend. |
| Debye answers but sounds scripted | `OPENAI_API_KEY` missing or wrong; check the backend window for errors. |
| WhatsApp messages get no reply | Is the bridge window showing `ready`? Is the sender's number a tenant (section 8)? Unknown numbers get a "not registered" reply. |
| Email buttons open a dead link | `PUBLIC_BASE_URL` is the old tunnel address; update it and restart. |
| "502 Bad Gateway" on the public link | The backend isn't running (or is restarting); start it again (step 6). |

For the stage demo script and fallbacks, see `docs/runbook.md`.
