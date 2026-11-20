# WhatsApp Cloud API setup (checklist)

About 30–45 minutes. You need a Facebook account and the 3 demo phones: the resident (Luka), the neighbour (Jonas) and one spare. The installer uses the partner web page, so they don't need WhatsApp. The values you collect go into `.env` (never commit it).

| `.env` variable | Where it comes from (step) |
|---|---|
| `WA_PHONE_NUMBER_ID` | 2 |
| `WA_TOKEN` | 4 (permanent token, not the 24 h one) |
| `WA_APP_SECRET` | 5 |
| `WA_VERIFY_TOKEN` | you pick it (6) |
| `WA_GRAPH_VERSION` | optional, default `v21.0`; use the version shown on the API Setup page |

## Twilio WhatsApp sandbox (current route: Meta locked the business account)

Debye sends through Twilio when `WA_PROVIDER=twilio`, or when `WA_PROVIDER` is unset and `TWILIO_ACCOUNT_SID` is set. The Meta steps below stay valid for `WA_PROVIDER=meta`.

1. `.env`: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM=whatsapp:+<sandbox number>`, and `PUBLIC_BASE_URL=https://<your tunnel>`. The public URL is used to check Twilio's signature and to serve voice notes to Twilio. On this machine the shell also exports other `TWILIO_*` values; the `.env` values win (the server logs a warning).
2. Every demo phone joins the sandbox once: send `join <your-code>` to the sandbox number. The code is shown in Twilio Console → Messaging → Try it out → Send a WhatsApp message. A joined phone stays in for 72 h. Free-form replies only work within 24 h of that phone's last message.
3. Twilio Console → that sandbox page → **Sandbox settings**:
   - "When a message comes in": `https://<your tunnel>/webhooks/twilio`, method **POST**.
   - "Status callback URL": leave empty. Debye sets `/webhooks/twilio/status` on every message it sends.
4. The real phone numbers go in `data/seed.local.json` (Luka `c_202`, Jonas `c_203`), in E.164 (`+49151…`). Twilio's `From: whatsapp:+49…` is normalised to that.
5. Smoke test: send "hi" from Luka's phone. The server log shows `POST /webhooks/twilio` and `Twilio message SM… queued`. Failed deliveries show up as `Twilio delivery FAILED … error=<code>`. 63016 means outside the 24 h window, so the phone has to message first.

**What's different from Meta.** The sandbox can't send WhatsApp buttons or lists without approved templates. Debye sends them as numbered text instead ("Antworte mit der Zahl: 1 = Überall kalt, 2 = Nur ein Raum"), and the resident's "1" or "Überall kalt" is mapped back to the same button, so the flow is identical. Voice notes from ElevenLabs go out as media from a short-lived public URL (`/webhooks/twilio/media/…`).

**Escape hatch.** If the signature check fails behind an unusual proxy, set `TWILIO_VALIDATE_SIGNATURE=0`. Use it for the demo only.

## 1. Create the app
1. Open https://developers.facebook.com/apps and log in.
2. **Create app** → use case **Other** → app type **Business** → name `Debye Demo` → contact email → **Create app**. If asked for a Business portfolio, create one (`Debye Hackathon`).
3. On the app dashboard, find **WhatsApp** in "Add products to your app" → **Set up**.

## 2. Test number and IDs
1. Left menu: **WhatsApp → API Setup**.
2. Under "From", Meta has created a **test phone number**. Copy the **Phone number ID** (a long number, not the phone number itself) → `WA_PHONE_NUMBER_ID`.
3. Write down the test number itself (`+1 555 …`). This is the number the demo phones will message.

### Profile picture (Debye mascot)
1. WhatsApp → **API Setup** → under "From", click the test number → **Profile** (or WhatsApp Manager → **Phone numbers** → the number → **Profile**).
2. Upload `docs/design/mascot/debye-mascot-whatsapp-1024.png` as the profile photo. Set the display name to "Debye" and the "About" text to "AI assistant · reltix".
3. It can take a few minutes before the phones show the new picture.

## 3. Verify the demo phones (max 5 recipients)
1. Still on **API Setup**, field "To" → **Manage phone number list** → **Add phone number**.
2. Enter each demo phone in international format (`+49 151 …`), then type in the code that arrives on WhatsApp.
3. Repeat for all 3 phones. A test number can only message verified recipients.
4. Put the real numbers into `data/seed.local.json` (git-ignored), not `data/seed.json`: Luka → `c_202`, Jonas → `c_203`.

## 4. Permanent token (the API Setup token dies after 24 h)
1. Open https://business.facebook.com/settings → choose the business portfolio from step 1.
2. **Users → System users → Add** → name `debye-bot`, role **Admin** → **Create system user**.
3. Select `debye-bot` → **Assign assets** → **Apps** → `Debye Demo` → toggle **Full control** → **Save**.
4. Also **Assign assets → WhatsApp accounts** → the test WhatsApp Business Account → **Full control** → **Save**.
5. **Generate new token** → app `Debye Demo` → expiry **Never** → permissions `whatsapp_business_messaging` and `whatsapp_business_management` → **Generate token**.
6. Copy the token right away (it is shown once) → `WA_TOKEN`.

## 5. App secret
1. developers.facebook.com → your app → **App settings → Basic**.
2. **App secret → Show** (asks for your password) → `WA_APP_SECRET`. The backend uses it to check the `X-Hub-Signature-256` header on every webhook.

## 6. Webhook
1. Start the backend with a public URL. Local: `uvicorn app.main:app --port 8000` and in a second terminal `cloudflared tunnel --url http://localhost:8000` (or `ngrok http 8000`). Deployed: the Railway/Render URL.
2. Pick any random string as `WA_VERIFY_TOKEN`, put it in `.env` and restart the backend.
3. developers.facebook.com → your app → **WhatsApp → Configuration → Webhook → Edit**.
   - Callback URL: `https://<your-host>/webhooks/whatsapp`
   - Verify token: the same `WA_VERIFY_TOKEN`
   - **Verify and save**. Meta calls `GET /webhooks/whatsapp`; the backend echoes the challenge.
4. Under **Webhook fields**, click **Manage** → subscribe to **messages**.
5. Only one webhook URL is active per app. Agree in the team whose tunnel or deployment it points to.

## 7. Smoke test
1. From Luka's phone, send "hi" to the test number.
2. The backend log should show the inbound message. Debye answers within a few seconds.
3. If nothing arrives: check the webhook fields subscription (step 6.4), that the phone is verified (step 3), and the backend log for `bad signature` (wrong `WA_APP_SECRET`).

## 8. Before the pitch
- From **every** demo phone, send "hi" to the test number less than 24 h before the pitch. This opens the 24 h customer-service window that free-form text, buttons and lists need (no templates required).
- Optional, not needed for the demo: submit utility templates `job_offer` and `slot_confirmed` under **WhatsApp Manager → Message templates**.

## Without Meta (development and plan C)
- Leave `WA_TOKEN` empty (or set `WA_FAKE_SEND=1`): nothing is sent to Meta. Outbound messages are printed to the backend log and listed at `GET /webhooks/whatsapp/_outbox?since=<seq>` (needs `DEMO_MODE=1`).
- `scripts/simulate.py` posts Meta-shaped webhooks. For media, use ids of the form `local:<path to file>`; the adapter reads the file from disk instead of the Graph API.
- Stage fallback if WhatsApp or Wi-Fi fails: open `https://<host>/chat/c_202` on the phone. It's a WhatsApp-style web chat with the same backend and agent.
