# Spec: partners work the job over WhatsApp (conversational transport)

Hand this file to the implementing chat: "Implement docs/partner-whatsapp-spec.md."

## Goal

Today a partner can only work a job by logging into our partner portal. Real craftsmen live in WhatsApp.
After this change, a partner whose manifest says `transport.type = "conversational", channel = "whatsapp"`
gets the job as a WhatsApp message from Debye and runs the whole job by replying in plain language:
accept with a time, decline, report done, send the invoice PDF. Anna's staff page updates live.

**Demo moment:** Anna clicks Approve → the partner's phone buzzes with the job → he types
"Ja, morgen 8–10 passt" → Anna's screen flips to Accepted and Luka gets the time on WhatsApp.

The connector spec (`docs/connector-spec.md`) and the onboarding validator
(`backend/app/partners/onboarding.py:144`) already allow `conversational` + `whatsapp` + `address`.
Nothing implements it yet. This spec does.

## Rules

- **Reuse, don't fork.** Portal and WhatsApp must end up calling the same service functions
  (`services.partner_accept`, `partner_decline`, `propose_slots`, `technician_confirm`, `record_completion`)
  and the same `notify.notify_tenant(...)` events. No second lifecycle.
- **Consent still gates everything.** The job message is built from `partner_api.job_detail(...)`, which
  already returns only consented fields. Never put rent, lease, bank details or other tenants in a message.
- The portal keeps working for every partner, including WhatsApp ones (the message carries the portal link).
- Every partner message, in and out, is logged with `be.log_message(...)` and recorded as a case event, so
  it shows on the staff case timeline.

## 1. Data / config

1. `partners/heizung-schmidt.json`: change `transport` to
   ```json
   "transport": { "type": "conversational", "channel": "whatsapp",
                  "address": "+49...", "language": "de", "url": "/partner/heizung-schmidt" }
   ```
   `address` comes from env `PARTNER_WHATSAPP_DEMO` (the demo partner's real phone) when set. Apply that override
   where manifests are loaded/seeded (`backend/app/seed.py` / `scenarios.py`) so `/demo/scenarios` sets it up.
2. Seed a `Contact` with `role="partner_staff"`, name "Tom Schmidt", `phone_e164` = that address
   (model: `backend/app/models.py:53`). Resolve contact → partner by matching the phone against
   `manifest.transport.address` (add `services.partner_for_phone(phone) -> partner_id | None`). No schema change.
3. Keep other partners on `portal`.

## 2. New module `backend/app/partners/whatsapp_transport.py`

```python
async def offer_job(case_id: str, partner_id: str) -> None        # outbound, after dispatch
async def handle_partner_message(contact, partner_id: str, text: str | None,
                                 media: list, button_id: str | None) -> None   # inbound
async def on_tenant_picked_slot(case_id: str) -> None             # tenant chose a slot
async def send(partner_id: str, case_id: str, body: str, options=None, media_paths=()) -> None
def is_whatsapp_partner(partner_id: str) -> bool
```

`send` uses `channels.base.channel_for(address)` → `send_text` / `send_buttons` / `send_media`
(the wweb bridge turns buttons into numbered text and maps "1"/"Annehmen" back via `remember_options`,
`channels/twilio.py:100`). Log each send with `be.log_message(contact_id, case_id, channel, "out", ...)`.

### 2a. Outbound: the job offer

Call `await whatsapp_transport.offer_job(case_id, partner_id)` right after every successful
`services.dispatch_job(...)` **when `is_whatsapp_partner(partner_id)`**. Call sites:
- `backend/app/staff_api.py:219` (approve → `approve_case` → `dispatch_job`): after it returns with `dispatched`.
- `backend/app/agent/flow.py:239` (auto-dispatch path).
Use `asyncio.create_task` if the caller is sync. Do not await network inside `services.py`.

Build the message from `partner_api.job_detail(s, case, partner_id)` (consented fields only). German template
(English if `transport.language == "en"`):

```
Neuer Auftrag über reltix · DRINGEND
Heizung + Warmwasser aus · Vaillant ecoTEC plus (Gas) · Fehler F.28
Musterstraße 12, 52062 Aachen · 2. OG, Whg. 4b
Diagnose: Kesselstörung (Zündung) · Kostenrahmen bis €350
Fotos: 2 (folgen)

Einfach antworten, z. B. „Ja, morgen 8–10" oder „Nein, keine Zeit".
Details: <PUBLIC_BASE_URL>/partner/heizung-schmidt/jobs/<case_id>
```
Buttons: `[Annehmen] [Ablehnen]` (ids `wa_accept:<case_id>`, `wa_decline:<case_id>`).
Then send consented photos/voice-note transcript as media if consent includes photos.
Record event `partner.offer_sent` ("Job offered to Heizung Schmidt via WhatsApp").

### 2b. Inbound: routing

`backend/app/router.py:84-89` currently answers every non-tenant with "Jobs and appointments are on the reltix
partner page." Replace that branch:

```python
if role == "partner_staff":
    pid = services.partner_for_phone(msg.from_phone)
    if pid and whatsapp_transport.is_whatsapp_partner(pid):
        await whatsapp_transport.handle_partner_message(contact, pid, text, msg.media, msg.button_id)
        return
    ... existing reply ...
```
Do this **before** the tenant buffer/agent. Voice notes are already transcribed above it (lines 47-73),
so a spoken "Ja, morgen um acht" works too. Media: download with `ch.download_media(m)` (already done above:
reuse the paths, don't download twice).

### 2c. Which job?

Active job = most recent case with `partner_id == pid` and status not in (`closed`, `rejected`,
`partner_declined`), or with a pending offer for `pid`. Button ids carry the case id; use it when present.
If several jobs are open and the text names no address, reply with a numbered list of addresses and wait.

### 2d. Understanding the reply

One structured-output LLM call, same pattern as `agent/diagnosis.py:676 _classify_answers` (strict JSON
schema, `reasoning_effort` from env, 8 s timeout, `{}` on failure). Give it the current time in
Europe/Berlin, the job status, and the slots already proposed. Schema:

```json
{ "intent": "accept | decline | propose_slots | arrived | done | question | other",
  "slots": [{"start": "ISO-8601 +01:00", "end": "ISO-8601 +01:00"}],
  "reason": "string", "notes": "string" }
```
Examples to put in the prompt: "Ja, morgen 8–10" → accept + 1 slot; "kann erst Montag 10-12 oder 14-16" →
accept + 2 slots; "nein, voll diese Woche" → decline, reason; "erledigt, Zündelektrode getauscht" → done, notes;
"welcher Kessel genau?" → question.

**Fallback without an API key** (tests and offline demo): regex — `^(ja|yes|ok|passt|annehmen)` → accept,
`^(nein|no|ablehnen)` → decline, `(heute|morgen|übermorgen|mo|di|mi|do|fr|sa)\w*\s*(\d{1,2})\s*[-–]\s*(\d{1,2})`
→ one slot, `erledigt|fertig|done` → done. Buttons `wa_accept` / `wa_decline` skip the LLM.

### 2e. Actions (by intent and current status)

| Reply | Status | Do | Reply to partner |
|---|---|---|---|
| accept + slots | requested | `partner_accept` then `propose_slots(case, pid, slots, tech_id=None)` + the same `notify_tenant` calls the portal endpoints make (`partner_api.py:191-252`) | "Danke, angenommen. Wir haben Luka Sa 22.11., 8–10 angeboten. Sie hören von uns, sobald er bestätigt." |
| accept, no slot | requested | `partner_accept` + notify | "Danke! Wann können Sie? z. B. „morgen 8–10"" (wait for slots) |
| propose_slots | accepted | `propose_slots` + notify | as row 1 |
| decline | requested/accepted | `partner_decline(reason)` + notify (as `partner_api.py:206`) | "Alles klar, danke für die schnelle Antwort." |
| done (+photo/PDF) | scheduled | `record_completion(case, pid, notes, photo_t, invoice_t)` + notify `job_completed` | no invoice yet: "Danke! Bitte schicken Sie noch die Rechnung als PDF." |
| PDF alone | after done | `record_completion` with the invoice (check whether it accepts a second call with only the invoice, as the portal does; if not, keep the report in `case.data["wa_pending_report"]` until the PDF arrives) | "Rechnung erhalten: €237,41 · im Kostenrahmen ✓" (use the parsed amount and price check from the result) |
| question | any | record event `partner.question`, forward to staff (event is enough; Anna sees it live) | "Gute Frage, ich gebe sie an die Hausverwaltung weiter." |
| other / unclear | any | nothing | short re-prompt with the buttons that fit the status |

**Do the refactor first:** move the bodies of the portal endpoints `accept`, `decline`, `slots`, `complete` in
`partner_api.py` into async helpers (e.g. `partners/actions.py: accept_job(case, pid)`, ...) that run the
service call and the `notify_tenant` call. The portal endpoints and the WhatsApp handler both call those.
Catch `rules.RuleViolation` and reply with its message in plain language.

### 2f. Closing the loop with the partner

- **Tenant picks a slot.** Where the tenant's choice is handled (`services.confirm_slot`, `services.py:834`,
  called from the agent/router), afterwards call `whatsapp_transport.on_tenant_picked_slot(case_id)` for
  WhatsApp partners. It auto-runs `services.technician_confirm(case_id, assigned_tech_id)` (the partner offered
  that slot, so the pick is the booking), sends the usual tenant confirmation, and messages the partner:
  "Luka hat bestätigt: Sa 22.11., 8–10 Uhr · Musterstraße 12, 2. OG · Tel. +49 … (nur für diesen Auftrag)".
  Share the phone only if it's in the consented fields.
- **Evening before:** if a reminder job exists for tenants, send the partner a one-line reminder too (optional).
- **After `close_case`:** "Auftrag abgeschlossen. Danke! Bewertung von Luka: ★★★★★" if a rating exists (optional).

## 3. Staff page (small)

- In the staff case page, partner card: badge "via WhatsApp" when the partner is conversational, and show the
  partner's WhatsApp messages in the timeline (they come from the events/messages, so check they render with
  the partner's name, e.g. "Heizung Schmidt (WhatsApp): Ja, morgen 8–10 passt").
- Event names: `partner.offer_sent`, `partner.message`, `partner.question`. Make sure the SSE stream pushes
  them (it pushes case events today).

## 4. Stretch (only if time is left): decline → next partner

On decline, take `services.rank_partners(case_id)` without the decliners. Consent is per partner, so
ask Luka on WhatsApp: "Heizung Schmidt can't come. Wärme Wagner can come in 6 days. Shall I share your
details with them?" On yes, `record_consent` then `dispatch_job` (approval is already granted, so check
`rules.check_dispatch`). Record event `job.redispatched`.

## 5. Tests: `backend/tests/test_partner_whatsapp.py`

Use the fake/recording channel the existing router tests use (no network, no LLM key → regex fallback).
1. Dispatch to a WhatsApp partner sends exactly one offer to `transport.address`. The text contains the address
   and error code and does **not** contain rent, IBAN or lease data.
2. "Ja, morgen 8–10" from the partner's number → status accepted, slots proposed, tenant notified with the slot.
3. Tenant picks the slot → technician confirmed automatically, partner gets the confirmation with tenant phone.
4. "Nein, keine Zeit" → `partner_declined`, tenant notified.
5. "erledigt" + PDF → completion recorded, invoice parsed, partner gets the amount back.
6. Unknown number and tenants are unaffected: run the existing test suite (`pytest -q`, 198 passing today).
7. Portal accept still works for a WhatsApp partner (no double notify).

## 6. Demo setup and manual check

- 3 phones: Debye's WhatsApp (linked to the bridge, `bridge/index.mjs`), Luka's phone, the partner's phone
  (`PARTNER_WHATSAPP_DEMO`). Start backend + bridge, `POST /demo/scenarios`.
- Run: Luka voice note → diagnosis → consent → Anna approves on the laptop → partner phone buzzes →
  partner types "Ja, morgen 8–10" → Anna's case shows Accepted + the message → Luka picks the slot →
  partner gets the confirmation → next day `/demo/skip-to-tomorrow` → partner sends "erledigt" + photo +
  `data/demo/invoice_RE-2026-1187.pdf` → Luka "Yes, all warm" → case closed.

## Done when

- The demo run above works end to end with no portal clicks by the partner.
- Tests in section 5 pass and the existing suite still passes.
- No personal field leaves centrix without consent (test 1).
