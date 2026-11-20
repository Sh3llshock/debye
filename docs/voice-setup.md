# Calling Debye (voice)

Residents can phone Debye. The call lands in the same case as WhatsApp, shows on the staff timeline as
"Call with Luka (0:47): heating cold, all radiators cold, ignition failed (F.28). Case opened, consent asked on WhatsApp.",
and when the caller hangs up, Debye continues on WhatsApp with a short recap and the consent buttons. The resident
is never asked the same thing twice.

## How it works

```
caller ──(browser /call  or  phone number)──► ElevenLabs agent "Debye" (German voice, gemini-2.5-flash)
                                                 │ server tools (webhooks, header X-Debye-Voice-Secret)
                                                 ├─► POST /api/voice/tools/identify_caller  → contact, unit, heating, open cases
                                                 └─► POST /api/voice/tools/report_issue     → flow.ensure_case (same case logic as WhatsApp)
call ends ──► finish_call: timeline event "call.completed" + WhatsApp recap + consent / triage buttons
```

The backend notices the end of a call in one of three ways and dedupes them by conversation id:
1. a background watcher, started on the first tool call, polls `GET /v1/convai/conversations/{id}` until the call is processed. **This needs no extra setup and also covers phone calls.**
2. the `/call` page posts `/api/voice/calls/{id}/end` when the session closes.
3. the ElevenLabs post-call webhook `POST /api/voice/post_call`. It's optional, see below.

The WhatsApp follow-up is a business-initiated message, so it only reaches the resident inside WhatsApp's 24-hour window. Have the demo phone send "hi" first (runbook step 7). If the resident already has an open case in the chat, the call joins that case and only the recap is sent.

Code: `backend/app/voice/` (router `api.py`, logic `calls.py`, page `call_page.html`). The agent config is in `scripts/elevenlabs_agent.py`.

## Setup (once per public URL)

ElevenLabs calls our tools over the internet, so the backend needs a public https URL: the Render URL, or a tunnel.

1. Add to `.env`:
   ```
   ELEVENLABS_API_KEY=...            # already there for voice replies
   VOICE_TOOL_SECRET=<long random>   # python -c "import secrets;print(secrets.token_urlsafe(24))"
   ```
2. Start the server and the tunnel (runbook step 3–4), then create or update the agent:
   ```powershell
   python scripts\elevenlabs_agent.py --base https://<tunnel-or-render-url>
   ```
   It prints only the agent id. Put it into `.env` as `ELEVENLABS_AGENT_ID=agent_...` and restart the server.
   The script is idempotent: it matches the tools (`debye_identify_caller`, `debye_report_issue`) and the agent (`Debye`) by name and updates them in place.
3. **Each new `trycloudflare.com` URL means running step 2 again.** The tool URLs are stored in the agent. For the stage, prefer the Render URL, which doesn't change.

Optional `.env` knobs: `ELEVENLABS_AGENT_VOICE_ID` (default: "Simona – German, Calm, Social" from the voice library, added to the workspace automatically), `ELEVENLABS_AGENT_LLM` (default `gemini-2.5-flash`).

## Option A: web test page (no phone number needed)

Open **`https://<public-url>/call`**, or `http://localhost:8000/call` on the laptop itself. The browser needs the microphone, and localhost or https both count as secure. Pick "Anrufen als Luka" and press **Anrufen**. The page gets a signed URL from `/api/voice/signed_url` (the API key never reaches the browser) and starts the session with the `@elevenlabs/client` SDK. The caller is identified through the `contact_id` dynamic variable. `?contact=c_203` calls as Jonas.

This is the demo fallback. It's the same agent, tools and case logic as a phone call.

## Option B: a real phone number

Phone calls are identified by the caller's number (`system__caller_id`), which `services.get_contact_by_phone` matches against the contacts. So the calling phone must be in `data/seed.local.json` (Luka's demo phone already is).

### B1: Twilio number imported into ElevenLabs (recommended, about 15 minutes)
**The user must do this in their own accounts. Nobody on the team buys numbers or creates paid accounts for them.**
1. Create a Twilio account at twilio.com. A trial account comes with credit.
2. Twilio Console → Phone Numbers → Buy a number with **Voice** capability.
   - A US or UK number is available instantly. **German (+49) numbers need a regulatory bundle (ID + local address) that can take days, so it's too late for this hackathon.** An international call to a US number from a German mobile works fine for the demo.
   - On a **trial** account, Twilio plays a short "trial account" message before the call connects, and only verified caller numbers may call. Verify Luka's demo phone under *Verified Caller IDs*, or upgrade the account (about $20) to remove both limits.
3. Copy the **Account SID** and **Auth Token** (Console home).
4. ElevenLabs dashboard → **Agents → Phone Numbers → Import number → From Twilio**: label "Debye", the number in E.164, Account SID, Auth Token. ElevenLabs configures the Twilio webhooks itself.
5. In the same screen, assign the agent **Debye** to the number.
6. Call it from Luka's phone. Debye greets Luka by name, and the case and the WhatsApp follow-up appear as with the web page.
   Calls use ElevenLabs agent minutes plus Twilio minutes, about €0.10–0.20 per demo call.

The same thing via API (instead of steps 4–5): `POST https://api.elevenlabs.io/v1/convai/phone-numbers` with `{"provider":"twilio","phone_number":"+1...","label":"Debye","sid":"AC...","token":"..."}`, then `PATCH /v1/convai/phone-numbers/{id}` with `{"agent_id":"agent_..."}`.

### B2: SIP trunk (if the user already has a SIP provider, e.g. sipgate, Telnyx, Zadarma)
1. ElevenLabs → Agents → Phone Numbers → Import number → **From SIP trunk**: the number, inbound/outbound transport (TCP or TLS) and, if the provider needs it, digest username and password.
2. At the SIP provider, route inbound calls for that number to the ElevenLabs SIP endpoint given in the import dialog (at the time of writing `sip:sip.rtc.elevenlabs.io:5060;transport=tcp`. Check the dialog, it is authoritative).
3. Assign the agent Debye. A German number from a SIP provider that already holds it avoids the Twilio regulatory wait.

### Future option: WhatsApp Business Calling API
Meta's WhatsApp Cloud API supports voice calls to a business number. A resident could tap "call" inside the same WhatsApp chat, and the call would be bridged (WebRTC/SIP) to the ElevenLabs agent. That would be the most natural "same context" channel, but it needs calling enabled on the WhatsApp Business number plus a media bridge. **We did not build it.**

## Post-call webhook (optional)
Not needed, because the watcher covers it. It's nice to have when the server restarts during a call. ElevenLabs → **Settings → Webhooks** → add the post-call webhook `https://<public-url>/api/voice/post_call` with HMAC auth, then choose it under the agent's (or the workspace's) post-call webhook setting. Put the shown secret into `.env` as `ELEVENLABS_WEBHOOK_SECRET`. The endpoint checks the `ElevenLabs-Signature` header (`t=…,v0=…`). Without that secret it accepts only the `X-Debye-Voice-Secret` header.

## Tests
`cd backend; pytest tests/voice` covers the tools, the secret, HMAC, deduping, a neighbour joining the open case, the WhatsApp continuation and the polling watcher, with ElevenLabs stubbed.
