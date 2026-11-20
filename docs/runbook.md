# Stage runbook

Commands are PowerShell, run from the repo root. One server on `:8000` serves the API, the WhatsApp webhook and the built pages.

## T-30 min: set up

1. `.env` is filled in (copy of `.env.example`) and `data/seed.local.json` holds the real demo phones (Luka `c_202`, Jonas `c_203`). See [whatsapp-setup.md](whatsapp-setup.md).
2. Build the pages with the demo panel switched on:
   ```powershell
   cd frontend; npm ci; $env:VITE_DEMO="1"; npm run build; cd ..
   ```
3. Start the server (leave this terminal open):
   ```powershell
   cd backend; pip install -r requirements.txt; uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
4. Start the tunnel in a second terminal, then paste `https://<tunnel>/webhooks/whatsapp` into Meta → WhatsApp → Configuration → Webhook:
   ```powershell
   cloudflared tunnel --url http://localhost:8000
   ```
   The deployed Render URL works the same way. There, `/healthz` must return `{"ok":true}`.
5. Voice calls (optional, [voice-setup.md](voice-setup.md)): with the tunnel or Render URL from step 4, point the ElevenLabs agent at it. Run this again whenever the tunnel URL changes. Put the printed id into `.env` as `ELEVENLABS_AGENT_ID` and restart the server.
   ```powershell
   python scripts\elevenlabs_agent.py --base https://<tunnel>
   ```
6. Check the server:
   ```powershell
   Invoke-RestMethod http://localhost:8000/healthz
   ```
7. From **each demo phone**, send "hi" to the test number. That opens WhatsApp's 24-hour window for buttons and lists.
8. Reset and load the demo scenarios (this wipes the "hi" messages too). It creates 9 realistic cases on other units and partners so the staff and partner pages look busy; Luka's 4b and Jonas' 2a stay empty for the live run:
   ```powershell
   .\scripts\demo_scenarios.ps1
   ```
   For a completely empty dashboard instead: `.\scripts\demo_reset.ps1`.

## Screens

| Screen | Open |
|---|---|
| Projector, left | Luka's phone, mirrored (`scrcpy`) |
| Projector, right | http://localhost:8000/staff (case list → click the case once it appears) |
| Laptop 2 (the installer) | http://localhost:8000/partner/heizung-schmidt |
| Unit record for the finale | http://localhost:8000/staff/units/unit_4b |
| Call variant (laptop with mic) | http://localhost:8000/call (or Luka calls the Twilio number, see voice-setup.md) |

The demo panel sits behind the tiny dot at the bottom right of any page, or press `d`. It has **Skip to tomorrow** and **Reset**.

## The run (who does what)

| # | Who | Action | What appears |
|---|---|---|---|
| 1 | Luka (phone) | Voice note "Die Heizung ist kalt seit heute Morgen" + photo of the F.28 display | Case on the staff page, Debye asks "Sind alle Heizkörper kalt?" |
| 2 | Luka | Tap **Überall kalt** | Ranking (Schmidt first), consent request |
| 3 | Jonas (phone) | "Bei uns im 1. Stock ist die Heizung auch kalt." | "Schon gemeldet", Jonas linked to the case |
| 4 | Luka | Tap **Ja, gerne** (consent) | Consent record, job on the partner page |
| 5 | Installer (laptop 2) | Open the job → **Accept job** → tap 2 slots → **Send 2 slots to tenant** | Luka gets the slot list |
| 6 | Luka | Pick **Morgen 8–10** | Slot on the case |
| 7 | Presenter | Demo panel → **Skip to tomorrow** | |
| 8 | Installer | Photo after repair `data/demo/repair_done.jpg`, Invoice (PDF) `data/demo/invoice_RE-2026-1187.pdf` → **Mark as done** | Invoice + price check, Luka asked "Wieder warm?" |
| 9 | Luka | Tap **Ja, alles warm** | Case closed, invoice + report on unit 4b |

### Extra beat: plug in a new partner live (about 1 minute, after step 9 or in Q&A)
Pitch line: "The next partner plugs in without a line of code."
1. Staff page → **Partners** → **+ Onboard a partner** (or open http://localhost:8000/partners/join).
2. Click **Fill demo partner** (Heizung Müller GmbH, heating + plumbing, Vaillant + Buderus, 15 km around 52062, two technicians). Click through the three steps; point at the manifest JSON building on the right and the spec checklist turning green (17/17), especially the consent flags.
3. **Go live** → "Heizung Müller is live" with **Open partner portal** and **Open as Jonas / Eva**. Back on **Partners**, the new card is there.
4. The next matching case ranks Heizung Müller with no code change: #2 for a plumbing case, #3 for Luka's heating case (Schmidt stays first because of its framework agreement and rating).

The onboarded manifest is saved as `partners/heizung-mueller.json` and survives **Reset**. To remove it after the demo: delete that file, then reset.

### Variant: Luka calls instead of sending a voice note (step 1)
Luka **calls** Debye (phone number, or the `/call` page as "Luka"): "Meine Heizung ist seit heute Morgen kalt … alle Heizkörper … auf dem Display steht F 28." Debye greets Luka by name and doesn't ask for address or boiler. It explains "die Zündung ist fehlgeschlagen (Fehlercode F.28)", opens the case and hangs up. Within about 10 s:
- staff page: case opened, timeline line **"Call with Luka (0:47): heating cold, all radiators cold, ignition failed (F.28). Case opened, consent asked on WhatsApp."**
- Luka's WhatsApp: "Danke für deinen Anruf, Luka! 📞 Kurz zusammengefasst: …" and right after it the consent buttons. Steps 2 and 4 merge into one tap on **Ja, gerne**, and the run continues at step 5.

Pitch line: one case, two channels. The call continues in the chat without asking anything twice.

## If something breaks

| Problem | Do this |
|---|---|
| Debye doesn't answer on WhatsApp | Look at the server terminal. Webhooks arrive as `POST /webhooks/whatsapp`. No POST means the tunnel or webhook URL is wrong. Meanwhile, use the web chat below. |
| WhatsApp / Meta / venue network down | Use the **web chat** (same backend, same case): http://localhost:8000/chat/c_202 for Luka, http://localhost:8000/chat/c_203 for Jonas. Mirror that tab instead of the phone. |
| Model slow, down or no API key | Nothing to do. Debye falls back to scripted replies for each step (after 20 s at most, immediately without a key). |
| A tenant step won't go through | Push that one step from a terminal (shows on the staff page live):<br>`python scripts\simulate.py --direct --step report` (then `neighbour`, `consent`, `pick`, `fixed`) |
| Partner page won't load | Same idea for the installer side: `python scripts\simulate.py --step accept` (then `slots`, `complete`) |
| Call: Debye can't look Luka up / no WhatsApp after the call | Tunnel URL changed: run `python scripts\elevenlabs_agent.py --base https://<tunnel>` again. Check that `VOICE_TOOL_SECRET` and `ELEVENLABS_AGENT_ID` are in `.env`. Server log shows `POST /api/voice/tools/...` per call. |
| Call page says "Konnte nicht verbinden" | Allow the microphone. `ELEVENLABS_AGENT_ID` missing → 503. Fallback: the voice-note flow (step 1). |
| Wrong state, start over | `.\scripts\demo_reset.ps1`, or the demo panel → **Reset** |
| Server crashed | Restart it (step 3). Data is kept in `backend/debye.db`. Reset if the state looks wrong. |
| Nothing works | Play the whole flow hands-off on the staff page: `python scripts\simulate.py --direct --reset --pause 4`. Last resort: the backup video. |

Against the deployed server, add `--base https://<render-url>` to `simulate.py`, and pass the URL to `demo_reset.ps1` as the first argument.

## Rehearsal check

```powershell
python scripts\simulate.py --reset
```
It must end with `GOLDEN PATH OK`. That run goes through the real webhook and checks every Debye reply in fake-send mode (empty `WA_TOKEN`). With a real `WA_TOKEN`, the messages actually go out to the phones, so run it with `--direct` instead. The simulator sends the English voice note `data/demo/voice_note_hot_water_en.ogg` ("Hi, there's no hot water in the shower since this morning, and something is blinking on the boiler.") and the boiler photo, so with `OPENAI_API_KEY` set you see the real transcript and the real model reading F.28.

### WhatsApp route (`.env`)
- **Linked phone (current demo route)**: `WA_PROVIDER=wweb`, `WWEB_SECRET`; start `.\scripts\start_bridge.ps1` next to the backend, and scan the QR once (Settings → Linked Devices). `http://127.0.0.1:3010/health` must say `ready: true`. Details: [whatsapp-setup.md](whatsapp-setup.md#linked-phone-demo-route-wa_providerwweb).
- **Twilio sandbox** is the live route: `WA_PROVIDER=twilio`, `TWILIO_*`, `PUBLIC_BASE_URL=<tunnel>`, and Twilio's "When a message comes in" set to `<tunnel>/webhooks/twilio`. Every phone must have sent `join <code>` once, and should send "hi" shortly before the pitch to open the 24 h window. Buttons show up as numbered choices; residents answer with the number. See [whatsapp-setup.md](whatsapp-setup.md#twilio-whatsapp-sandbox-current-route-meta-locked-the-business-account).
- Meta Cloud API (`WA_PROVIDER=meta`) is still supported but locked right now (error 131031). Its delivery failures are logged as `WhatsApp delivery FAILED`.
- `scripts/simulate.py` doesn't care about the provider. With `WA_FAKE_SEND=1` (or without credentials), everything goes to the fake outbox.

### Model settings (`.env`)
- `LLM_PROVIDER=openai` (default): Debye's chat turns, photo reading and invoice extraction run on `OPENAI_CHAT_MODEL` (default `gpt-6-luna`) with `OPENAI_REASONING_EFFORT=none`. `LLM_PROVIDER=anthropic` switches to Claude (`claude-opus-5-5`, needs `ANTHROPIC_API_KEY`).
- `OPENAI_BASE_URL=https://eu.api.openai.com/v1` is required: our OpenAI project is EU-region only. That is also the default when the variable is missing.
- One key does everything on the OpenAI side: chat model and transcription (`gpt-4o-transcribe`, falling back to `gpt-4o-mini-transcribe`, then `whisper-1`).
- Measured on the webhook rehearsal: a Debye turn with gpt-6-luna takes 2.5–3.5 s (1–2 model calls), transcription about 1 s, invoice extraction 1.4–2.2 s.
