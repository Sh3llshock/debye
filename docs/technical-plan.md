> **v2 decisions (see [interfaces.md](interfaces.md) §0):** the product is **Debye (AI assistant)**. Residents use WhatsApp only. Partners work in their own web page (`/partner`), staff in their own page (`/staff`). Wherever this doc says the installer uses WhatsApp, read: the installer uses the partner page.

# Debye: technical build plan

How to build the Debye demo for the reltix track ("Plug a Partner into centrix") in the time left before the Sat 10:30 deadline. Read [pitch-plan.md](pitch-plan.md) for the why; this file is the how.

**Flow we build:** broken heater → heating installer, with the tenant and the installer both on WhatsApp, and the result written back to the unit in a centrix mock.

**Golden path (what must work live):**

1. Tenant sends a voice note + photo on WhatsApp.
2. Debye triages with centrix context, asks one question, opens a case (and merges a neighbour's duplicate report).
3. Tenant gives consent with one tap.
4. Debye ranks partners and sends a job card to the installer's WhatsApp.
5. Installer accepts and types time slots in plain text; the tenant picks one from a WhatsApp list.
6. Installer sends "erledigt" + photo + invoice PDF; Debye extracts the invoice, the tenant confirms, the case closes.
7. Every step appears live on the centrix dashboard; the invoice and report land on unit 4b.

---

## 1. Repo layout

```
debye/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, routers, static frontend mount
│   │   ├── config.py            # env vars (pydantic-settings)
│   │   ├── db.py                # SQLite (sqlmodel), session helper
│   │   ├── models.py            # tables (section 3)
│   │   ├── seed.py              # loads data/seed.json + partners/*.json
│   │   ├── events.py            # in-process event bus + SSE stream
│   │   ├── channels/
│   │   │   ├── base.py          # Channel interface + normalized Message
│   │   │   ├── whatsapp.py      # Meta Cloud API: webhook parse, send, media download
│   │   │   └── webchat.py       # WhatsApp-lookalike web chat (fallback + portal)
│   │   ├── router.py            # inbound message → contact → role → case → agent
│   │   ├── agent/
│   │   │   ├── loop.py          # Claude tool-use loop
│   │   │   ├── tools.py         # tool schemas + Python implementations
│   │   │   └── prompts.py       # tenant persona, partner persona
│   │   ├── partners/
│   │   │   ├── manifest.py      # pydantic model of the connector manifest
│   │   │   ├── eligibility.py   # evaluates manifest eligibility rules
│   │   │   ├── ranking.py       # scores eligible partners
│   │   │   └── transports.py    # ConversationalTransport, ApiTransport
│   │   ├── rules.py             # consent gate, spending limit, key release
│   │   ├── media.py             # STT (OpenAI), TTS (ElevenLabs), invoice extraction
│   │   ├── centrix_api.py       # REST used by the dashboard
│   │   └── demo.py              # /demo/reset, /demo/skip-to-tomorrow, /demo/trigger
│   ├── tests/
│   │   └── test_golden_path.py  # runs the whole flow through the simulator
│   └── requirements.txt
├── frontend/                    # Vite + React + Tailwind
│   └── src/
│       ├── pages/Centrix.tsx    # unit record, case timeline, approvals
│       ├── pages/Partner.tsx    # partner's view of jobs (backup for the WhatsApp side)
│       ├── pages/Portal.tsx     # tenant portal: same case + web chat
│       └── lib/sse.ts
├── data/seed.json               # properties, units, assets, contacts, contracts
├── partners/*.json              # one connector manifest per partner
├── scripts/
│   ├── simulate.py              # fakes WhatsApp webhooks: no phone needed
│   └── demo_reset.sh
├── docs/
│   ├── technical-plan.md        # this file
│   ├── connector-spec.md        # partner connector spec (deliverable)
│   └── pitch-plan.md            # pitch + strategy
├── .env.example
└── README.md
```

One deployable service: FastAPI serves the API, the webhook and the built frontend (`frontend/dist`). One URL for judges, one webhook URL for Meta.

---

## 2. Setup (do this first, in parallel)

### 2.1 Environment variables (`.env.example`)

| Variable | Used for |
|---|---|
| `ANTHROPIC_API_KEY` | Claude (agent, vision, invoice extraction) |
| `OPENAI_API_KEY` | Voice-note transcription (sponsor) |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | Debye voice replies (sponsor, optional) |
| `WA_TOKEN` | Meta system-user permanent token |
| `WA_PHONE_NUMBER_ID` | The test number's ID (not the phone number itself) |
| `WA_VERIFY_TOKEN` | Any random string; Meta echoes it during webhook verification |
| `WA_APP_SECRET` | To check the `X-Hub-Signature-256` header on webhooks |
| `PUBLIC_BASE_URL` | Deployed URL, used in links |
| `DEMO_MODE` | `1` enables /demo endpoints and the time-skip button |

### 2.2 WhatsApp Cloud API (owner: A, ~45 min)

1. developers.facebook.com → create app (type Business) → add product **WhatsApp**.
2. In WhatsApp → API Setup: note the **test phone number ID**, add the **3 demo phones** (tenant, neighbour, installer) as recipients and confirm the codes. The test number can only message verified recipients (max 5).
3. Business Settings → System users → create one, give it the app with `whatsapp_business_messaging` + `whatsapp_business_management`, generate a **permanent token** (the API Setup token dies after 24 h).
4. Webhook: callback URL `https://<host>/webhooks/whatsapp`, verify token = `WA_VERIFY_TOKEN`, subscribe to the `messages` field.
5. Submit 2 utility templates right away (`job_offer`, `slot_confirmed`). Approval is usually fast but not guaranteed; the demo must not depend on it.
6. Before the pitch, send "hi" from every demo phone to the test number so the 24 h customer-service window is open for free-form and interactive messages.

Plan B: Twilio WhatsApp sandbox (join code, no approval). Plan C: the web-chat channel (section 5.2), same backend.

### 2.3 Hosting

- Dev: `uvicorn app.main:app --reload` + `cloudflared tunnel --url http://localhost:8000` (or ngrok). Each dev can point Meta at their own tunnel, but only one webhook URL is active at a time: agree who owns it.
- Demo: Railway or Render, one service, Dockerfile or Nixpacks; SQLite on a volume (or just re-seed on boot: the demo resets anyway).
- Phone on projector: `scrcpy` (Android, USB) or QuickTime (iPhone). Use a phone hotspot, not venue Wi-Fi.

---

## 3. Data model (SQLite via SQLModel)

Keep the shapes close to reltix's example payloads so the output looks native to centrix.

| Table | Key fields |
|---|---|
| `property` | id, address, postcode, city, building_year, heating_type, heating_central (bool), energy_class, energy_valid_until |
| `unit` | id, property_id, floor, size_sqm, rooms, meters (JSON) |
| `asset` | id, property_id, unit_id (nullable for central), type (`gas_boiler`), make, model, installed, last_service |
| `contact` | id, role (`tenant`/`owner`/`partner_staff`/`pm`), name, phone_e164, email, language, unit_id, partner_id, whatsapp_opt_in (bool) |
| `contract` | id, type (`lease`/`framework`/`service`), unit_id, partner_id, data (JSON: rent, price list, `auto_approve_limit_eur`) |
| `partner` | id, manifest (JSON), active |
| `case` | id, type (`repair.heating`), status, priority, property_id, unit_id, asset_id, reporter_contact_id, partner_id, cost_bearer, estimated_cost_eur, slot_start, slot_end, created_at, closed_at |
| `case_contact` | case_id, contact_id, relation (`reporter`/`affected`) |
| `case_event` | id, case_id, ts, actor (`debye`/`tenant`/`partner`/`pm`/`system`), kind, summary, data (JSON) |
| `message` | id, case_id, contact_id, channel, direction, wa_message_id, text, media_ids (JSON), ts |
| `document` | id, case_id, unit_id, kind (`photo`/`invoice`/`report`/`contract`), filename, mime, path, extracted (JSON) |
| `consent` | id, contact_id, partner_id, case_id, data_shared (JSON list), purpose, channel, given_at, revoked_at |
| `conversation` | contact_id, case_id, claude_messages (JSON), updated_at |

Seed (`data/seed.json`): Musterstraße 12, 52062 Aachen; units 4b (Lena Hoffmann) and 2a (Jonas Weber); owner Maria Becker; central Vaillant ecoTEC plus boiler; framework contract with Heizung Schmidt (auto-approve limit €500). The partners table is loaded from `partners/*.json`.

**Zero-forms counter:** for each case, store `prefilled_fields` (list of fields taken from centrix) and `tenant_inputs` (messages/taps) in `case.data`. The dashboard shows "14 pre-filled · 1 voice note, 2 taps".

---

## 4. Events and live dashboard

- `events.py` keeps an `asyncio.Queue` per SSE subscriber. Every write to `case_event` also publishes `{type, case_id, payload}`.
- `GET /api/stream` → `text/event-stream`. The frontend subscribes once and patches state.
- Event types: `case.created`, `case.linked_reporter`, `consent.recorded`, `partner.ranked`, `approval.required`, `approval.granted`, `job.sent`, `job.accepted`, `slot.proposed`, `slot.confirmed`, `job.completed`, `document.attached`, `invoice.checked`, `case.closed`, `message.in`, `message.out`.
- `message.in`/`message.out` let the dashboard show the WhatsApp thread next to the timeline (this is also the "channels share context" bonus).

---

## 5. Channels

### 5.1 WhatsApp adapter (`channels/whatsapp.py`)

Normalized inbound type:

```python
@dataclass
class InboundMessage:
    channel: str            # "whatsapp" | "webchat"
    from_phone: str         # E.164
    wa_message_id: str | None
    text: str | None
    button_id: str | None   # reply-button or list-row id
    media: list[Media]      # (media_id, mime): audio/ogg, image/jpeg, application/pdf
```

Endpoints:

- `GET /webhooks/whatsapp`: verification. If `hub.mode == "subscribe"` and `hub.verify_token == WA_VERIFY_TOKEN`, return `hub.challenge` as plain text.
- `POST /webhooks/whatsapp`: check `X-Hub-Signature-256` (HMAC-SHA256 of the raw body with `WA_APP_SECRET`). Parse `entry[].changes[].value.messages[]`. Ignore `statuses` events except for logging. **Return 200 immediately** and process in a background task; Meta retries slow webhooks, which causes duplicate replies. Deduplicate on `wa_message_id`.

Outbound (all `POST https://graph.facebook.com/v21.0/{WA_PHONE_NUMBER_ID}/messages`, bearer `WA_TOKEN`; use the Graph API version current on Meta's API Setup page):

```jsonc
// text
{"messaging_product":"whatsapp","to":"49151...","type":"text","text":{"body":"..."}}

// reply buttons (max 3, title max 20 chars)
{"messaging_product":"whatsapp","to":"49151...","type":"interactive",
 "interactive":{"type":"button","body":{"text":"Sind alle Heizkörper kalt?"},
  "action":{"buttons":[
   {"type":"reply","reply":{"id":"cold_all","title":"Überall kalt"}},
   {"type":"reply","reply":{"id":"cold_some","title":"Nur ein Raum"}}]}}}

// list (max 10 rows) for slots
{"messaging_product":"whatsapp","to":"49151...","type":"interactive",
 "interactive":{"type":"list","body":{"text":"Wann passt es dir?"},
  "action":{"button":"Termin wählen","sections":[{"title":"Heizung Schmidt","rows":[
   {"id":"slot_1","title":"Morgen 8–10"},{"id":"slot_2","title":"Do 14–16"},
   {"id":"slot_none","title":"Passt beides nicht"}]}]}}}

// document / image / audio by uploaded media id or link
{"messaging_product":"whatsapp","to":"49151...","type":"audio","audio":{"id":"<media_id>"}}
```

Media in: `GET /{media_id}` returns a short-lived `url`; download it with the same bearer token. Save to `storage/` and create a `document` row.

Media out (ElevenLabs voice reply): upload with `POST /{WA_PHONE_NUMBER_ID}/media` (multipart, `messaging_product=whatsapp`), then send `type: audio`. WhatsApp voice notes want `audio/ogg; codecs=opus`; convert the TTS output with ffmpeg if needed.

### 5.2 Web-chat adapter (`channels/webchat.py`)

- WebSocket `/ws/chat/{contact_id}`. Same `InboundMessage` in; outbound uses the same `send_text/send_buttons/send_list` interface, rendered as WhatsApp-style bubbles in `Portal.tsx`.
- `channels/base.py` defines `Channel.send_text`, `send_buttons`, `send_list`, `send_media`. The agent never knows which channel it is on; `router.py` picks the channel from the contact's last inbound message.
- Used for (a) the Wi-Fi/Meta fallback on stage, (b) the portal "continue the conversation" bonus, and (c) local dev without phones.

### 5.3 Simulator (`scripts/simulate.py`)

Posts realistic WhatsApp webhook payloads (text, button reply, list reply, audio/image/document with local files) to the backend, with a `--fake-send` flag that prints outbound messages instead of calling Meta. This lets B and C work on the full flow without phones and powers `tests/test_golden_path.py`. **Build this in the first two hours.**

---

## 6. Router (`router.py`)

```
inbound → dedupe(wa_message_id)
        → contact = lookup by phone            (unknown → polite "not registered" reply, stop)
        → log message, publish message.in
        → media: audio → STT text; image/pdf → document row
        → role = contact.role
            tenant  → case = open case for this contact, or None
            partner → case = the job this partner is on (latest active, or by button id)
        → agent.run(role, contact, case, inbound)
```

Button and list ids carry intent (`consent_yes:<case_id>`, `job_accept:<case_id>`, `slot_2:<case_id>`). Handle these **deterministically in code** without calling the LLM. That makes the critical taps instant and unbreakable, and leaves the LLM for free text, voice and photos.

---

## 7. Debye agent

### 7.1 Model and API choices

- Claude through the official Python SDK (`pip install anthropic`), Messages API with a **manual tool-use loop** in our backend. Why not a hosted agent (Managed Agents): our tools read and write our own SQLite and the loop has to answer inside a webhook in a few seconds, so we keep the loop in-process.
- Model `claude-opus-5-5` with `output_config={"effort": "low"}` for chat turns (snappy replies) and `"medium"` for triage and invoice checks. Thinking is adaptive and on by default on this model; don't send `thinking: {type: "disabled"}` (returns 400).
- `tool_choice` stays `auto` (forced tool choice returns 400 on this model). Put `strict: True` on every tool so inputs always match the schema.
- Refusal fallback on by default: beta `server-side-fallback-2026-07-01` with `fallbacks="default"`. Always check `stop_reason` before reading content.
- Images go in as base64 `image` blocks; the invoice PDF as a base64 `document` block (`media_type: application/pdf`).
- Timeout: `client.with_options(timeout=20)`. On any API error, fall back to a scripted reply for the current step (section 7.5).

### 7.2 Loop (`agent/loop.py`)

```python
import anthropic

client = anthropic.Anthropic()

def run_agent(system: str, history: list, tools: list, ctx) -> list:
    """Runs one Debye turn. history is the stored Claude message list for this contact+case."""
    messages = list(history)
    while True:
        response = client.with_options(timeout=20).beta.messages.create(
            model="claude-opus-5-5",
            max_tokens=4000,
            system=system,
            tools=[t.schema for t in tools],
            messages=messages,
            output_config={"effort": ctx.effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            return messages + [scripted_handoff(ctx)]     # tell user a PM will follow up
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return messages                               # final text already sent via send_* tools
        results = []
        for block in response.content:
            if block.type == "tool_use":
                results.append(execute_tool(block, ctx))  # returns a tool_result dict, is_error on failure
        messages.append({"role": "user", "content": results})  # all results in ONE user message
```

Notes:
- The agent talks to people **only through tools** (`reply`, `ask_buttons`, `ask_list`). Free text in the final assistant turn is ignored. That way every outbound message is logged and channel-agnostic.
- Store `messages` per (contact, case) in the `conversation` table. Append-only; never rewrite history.
- The system prompt is stable (persona + rules); the per-turn centrix context goes in the user message as a `<centrix_context>` JSON block, so prompt caching keeps working.

### 7.3 Tools (`agent/tools.py`)

All have `strict: True`, `additionalProperties: false`, every property in `required`.

| Tool | Who | Input | Effect |
|---|---|---|---|
| `get_unit_context` | tenant, partner | `unit_id` | Returns property, unit, assets, lease, open cases (what centrix knows) |
| `reply` | both | `text` | Sends a text message to the current contact |
| `ask_buttons` | both | `text`, `options[{id,title}]` (≤3) | Sends reply buttons |
| `ask_list` | both | `text`, `button_label`, `rows[{id,title}]` (≤10) | Sends a list message |
| `open_case` | tenant | `type`, `priority`, `summary`, `symptoms`, `error_code`, `asset_id` | Creates the case; returns `case_id`. Rule: if an open case exists for the same central asset, returns `{"duplicate_of": id}` instead |
| `link_to_case` | tenant | `case_id`, `relation` | Adds the contact as affected (the dedupe step) |
| `request_consent` | tenant | `case_id`, `partner_id`, `fields[]`, `purpose` | Sends the consent buttons; the tap is handled in code and writes `consent` |
| `rank_partners` | tenant | `case_id` | Runs eligibility + ranking; returns the top 3 with reasons |
| `dispatch_job` | system | `case_id`, `partner_id` | **Code-gated**: needs consent + (estimate ≤ limit or PM approval). Sends via the partner's transport |
| `parse_slots` | partner | `text` | Returns ISO slots (Claude reads "Morgen 8–10 oder Do 14–16" relative to today) |
| `propose_slots` | partner | `case_id`, `slots[]` | Sends the tenant a list message |
| `report_completion` | partner | `case_id`, `notes` | Marks the job completed, links photos |
| `attach_invoice` | partner | `case_id`, `document_id` | Runs invoice extraction + price check, attaches to case and unit |
| `close_case` | system | `case_id`, `resolution` | After tenant 👍; writes the result payload and notifies the owner |

### 7.4 Prompts (`agent/prompts.py`)

Tenant persona, in short:
- You are Debye, the reltix assistant in WhatsApp. Reply in the tenant's language (German by default), 1–3 short sentences, friendly, no jargon.
- You already know the tenant's unit, building, heating and lease from `<centrix_context>`. Never ask for anything that's in it.
- Ask at most one question per message, using buttons when the answers are predictable.
- For heating: read the photo for an error code; give at most one safe self-check (never ask a tenant to open the boiler or touch gas parts). If gas smell: tell them to leave and call the emergency number, and escalate.
- You can't promise costs or dates until the installer confirms.

Partner persona: terse job-card style, German, always include the address, floor, asset and error code; never share data that isn't in the consented field list (the tool layer enforces this too).

### 7.5 Rules in code (`rules.py`), not in the prompt

- `can_share(contact, partner, fields)`: true only if a `consent` row covers all fields.
- `needs_approval(case)`: `estimated_cost_eur > framework.auto_approve_limit_eur` or the owner requires approval → create an `approval.required` event and stop until a PM clicks approve.
- `release_access_details(case)`: key-safe code only on the slot day, only to the assigned partner, logged.
- Scripted fallbacks per step (`STEP_FALLBACKS`) if Claude times out: e.g. after a photo, "Danke! Sind alle Heizkörper kalt?" with the two buttons.

---

## 8. Partner layer

### 8.1 Manifest + eligibility

`partners/manifest.py` is a pydantic model of the schema in [connector-spec.md](connector-spec.md). `eligibility.py` evaluates rules like `{"field": "asset.type", "op": "in", "value": [...]}` against a flat dict built from the centrix context (`property.postcode`, `asset.type`, `asset.make`, ...). Supported ops: `eq`, `in`, `in_service_area`, `gte`, `lte`.

### 8.2 Ranking (`ranking.py`)

Score for each eligible partner (weights in config, shown on the dashboard as "why this partner"):

| Signal | Weight |
|---|---|
| Certified for the asset's brand | 0.30 |
| Earliest availability (from last known availability or SLA) | 0.25 |
| Framework agreement with this PM | 0.20 |
| Rating | 0.15 |
| Has worked on this property before | 0.10 |

Return the top 3 with a one-line reason each. Seed three heating partners so the ranking is visible: Heizung Schmidt (wins), a cheaper one without Vaillant certification, a certified one that's fully booked.

### 8.3 Transports (`transports.py`)

Both implement `send_order(case, consented_context) → order_ref` and feed status changes into the same lifecycle (`requested → accepted → scheduled → in_progress → completed → invoiced → closed`).

- `ConversationalTransport` (Heizung Schmidt): sends the job card on WhatsApp with `Annehmen`/`Ablehnen` buttons. Partner replies go through the router to the partner persona, whose tools emit lifecycle events.
- `ApiTransport` (Example Fibre, stretch): `POST {base_url}/orders` with the consented context; partner calls back `POST /api/partners/{partner_id}/events` with `{order_ref, status, documents[]}`. Ship a 30-line mock partner server (`scripts/mock_fibre.py`) so the demo shows it end to end.
- SLA timer: an asyncio task per dispatched job; if not accepted within the manifest's `sla.urgent_response_hours` (shortened to 60 s in `DEMO_MODE`), dispatch to the next ranked partner and tell the tenant.

---

## 9. Media (`media.py`)

- **Voice note → text:** OpenAI transcription (`gpt-4o-transcribe` or `whisper-1`), `language="de"` hint. WhatsApp sends `audio/ogg` (opus), which the API accepts. Keep demo voice notes under 10 s.
- **Photo → error code:** pass the image to the agent turn; the tenant prompt asks it to read the display. Seed a known error table for the demo boiler (F.28 = ignition failed, F.22 = low water pressure) as a tool result so the answer is reliable.
- **Invoice PDF → fields:** `client.messages.parse(...)` with a pydantic `Invoice` model (`invoice_number`, `date`, `net_eur`, `vat_eur`, `gross_eur`, `line_items[{desc, qty, unit_price}]`, `labour_hours`), then compare against the framework price list; flag lines more than 10% above. Prepare the demo invoice PDF in advance (generate it once with reportlab or any template).
- **Debye voice reply (optional):** ElevenLabs TTS → ffmpeg to ogg/opus → upload → send as audio. Only for the first reply, so it's a moment, not a gimmick.

---

## 10. centrix dashboard (frontend)

`/centrix` (the money shot, right half of the projector):
- **Unit card** for 4b: address, building year, heating, energy class, tenant, lease. "Documents" list where the invoice and report appear.
- **Case card**: status pill (lifecycle), priority, cost bearer, assigned partner, slot, zero-forms counter.
- **Timeline**: `case_event` stream, newest at the bottom, with actor icons (Debye/tenant/installer/PM/system). Animate new items.
- **"Why this partner"** panel: top 3 with scores and reasons.
- **Approval card** (only when needed): "Approve €620 repair? [Approve]".
- **Consent record** expandable: `data_shared`, `given_at`, `channel`, exactly like reltix's example payload.
- **Result payload** viewer: the JSON written back to the unit at close.

`/partner`: jobs table + job detail (backup view of the installer side).
`/portal`: tenant's case status + web chat (fallback channel + bonus).
Demo controls (hidden unless `DEMO_MODE`): Reset, Skip to tomorrow, Trigger neighbour report.

Design: big type (readable from the back of Sint Janskerk), reltix-ish dark purple accent, no clutter.

---

## 11. API surface (backend)

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/webhooks/whatsapp` | Meta verification / inbound |
| WS | `/ws/chat/{contact_id}` | Web-chat channel |
| GET | `/api/stream` | SSE events |
| GET | `/api/units/{unit_id}` | Unit record with documents and cases |
| GET | `/api/cases/{case_id}` | Case with events, consents, partner, documents |
| POST | `/api/cases/{case_id}/approve` | PM approval |
| GET | `/api/partners` | Loaded manifests |
| POST | `/api/partners/{partner_id}/events` | Partner status webhook (API transport) |
| POST | `/api/events/centrix` | Inject centrix trigger events (e.g. `tenant.move_in`) |
| POST | `/demo/reset`, `/demo/skip-to-tomorrow`, `/demo/trigger/{name}` | Demo controls |
| GET | `/files/{document_id}` | Serve documents |

---

## 12. Result written back to centrix

At `close_case`, write to `unit.documents` and publish this payload (same shape as reltix's example, extended for a repair):

```json
{
  "unit_id": "unit_4b",
  "contact_id": "c_202",
  "service_job": {
    "partner": "Heizung Schmidt GmbH",
    "category": "repair.heating",
    "case_id": "case_0001",
    "status": "closed",
    "visit": { "start": "2026-11-21T08:00:00+01:00", "end": "2026-11-21T10:00:00+01:00" },
    "resolution": "Ignition electrode replaced, boiler restarted",
    "invoice": { "number": "RE-2026-1187", "gross_eur": 249.90, "document_id": "doc_0007", "price_check": "ok" },
    "affected_units": ["unit_4b", "unit_2a"],
    "consent": {
      "data_shared": ["name", "phone", "address", "unit_floor", "photos"],
      "given_at": "2026-11-20T18:21:00+01:00",
      "channel": "whatsapp"
    }
  }
}
```

---

## 13. Testing and demo safety

- `tests/test_golden_path.py`: drives the simulator through the full flow with `--fake-send` and a stubbed Claude (recorded responses) and asserts the case ends `closed` with an invoice on the unit. Run it before every deploy.
- A second run with the real Claude to catch prompt regressions (costs a few cents).
- `POST /demo/reset` drops and re-seeds the DB, clears conversations, keeps the WhatsApp windows open.
- Rehearse with the real phones at least 3 times on the deployed URL over the hotspot.
- Record the backup video from a clean run (OBS), 60–90 s.

---

## 14. Work packages and owners

Mirrored as GitHub issues with milestones. Times are re-based on the real clock (hacking started Fri 13:30; rooms close 18:00, so move to the overnight spot).

| # | Package | Owner | Milestone |
|---|---|---|---|
| 1 | Meta app, test number, 3 phones verified, permanent token, templates submitted | A | M1 WhatsApp round-trip (Fri 19:30) |
| 2 | FastAPI skeleton, config, deploy pipeline, tunnel | B | M1 |
| 3 | WhatsApp adapter: verify, inbound parse, signature check, send text/buttons/list, media download | A | M1 |
| 4 | Simulator + fake-send mode | B | M1 |
| 5 | Data model + seed + partner manifests | B | M2 Golden path E2E (Fri 23:00) |
| 6 | Agent loop + tools + tenant prompt; deterministic button handling | A | M2 |
| 7 | STT (OpenAI) + photo error-code reading | A | M2 |
| 8 | Partner layer: eligibility, ranking, conversational transport, partner prompt, slot parsing | B | M2 |
| 9 | Dashboard: unit card, case card, timeline via SSE | C | M2 |
| 10 | Close the loop: completion, invoice extraction + price check, tenant confirmation, result payload | A+B | M3 Hosted V1 (Sat 02:00) |
| 11 | Dedupe (neighbour), consent record view, approval card, zero-forms counter, why-this-partner | B+C | M3 |
| 12 | Web-chat channel + portal page | C | M3 |
| 13 | Connector spec doc + second partner (ApiTransport + mock Fibre server) | B | M4 Feature freeze (Sat 06:00) |
| 14 | ElevenLabs voice reply (optional) | A | M4 |
| 15 | Golden-path test, demo reset, skip-to-tomorrow | B | M4 |
| 16 | README, architecture diagram, assumptions, backup video, submission | D | M5 Submit (Sat 10:00) |
| 17 | Pitch script, slides, rehearsals, phone mirroring setup | D | M5 |

---

## 15. Known limitations (say them before judges do)

- WhatsApp test number: only verified recipients; production needs a verified business number and approved templates.
- Partner availability is parsed from free text; production would add calendar integration for partners who have one.
- The centrix side is a mock with seeded data; we assumed which fields reltix holds (see README).
- Cost estimate before the visit is a heuristic from the error code and framework prices.
