# centrix partner connector spec (v0.1)

What any ecosystem partner provides to plug into centrix, so Debye can detect the moment, hand over context, hold the conversation and close the loop. The next partner plugs in by adding one manifest; no redesign.

## 1. Principles

1. **One manifest per partner** describes what they offer, where, for whom, what data they need and how to reach them.
2. **One lifecycle for everyone.** Every order or job moves through the same states, whatever the partner's tech.
3. **Three transports, same lifecycle.**
   - `api`: for partners with systems (internet, energy, insurance).
   - `portal`: partners without their own system get a centrix partner page (job inbox, accept, slots, upload invoice). Used in the demo.
   - `conversational`: for partners without an API (most craftsmen). Debye talks to them on WhatsApp or email and turns their replies into the same lifecycle events.
4. **Consent before context.** A partner receives only the `required_context` fields the resident agreed to share, for a stated purpose. Every handover is recorded.

## 2. Manifest

| Field | Type | Meaning |
|---|---|---|
| `partner_id` | string | Stable id |
| `name` | string | Display name |
| `category` | string | Dotted taxonomy: `repair.heating`, `telecom.internet`, `energy.electricity`, `insurance.household`, `moving` |
| `kind` | `sell` \| `deliver` | Sells a contract, or delivers a service on site |
| `triggers` | string[] | centrix moments this partner is relevant for: `case.repair.heating`, `tenant.move_in`, `contract.energy.expiring` |
| `service_area` | object | `postcodes[]` or `radius_km` around `base_postcode` |
| `capabilities` | object | Free-form per category (trades, brands certified, products) |
| `eligibility` | rule[] | `{field, op, value}`; ops: `eq`, `in`, `in_service_area`, `gte`, `lte`. Fields address the centrix context (`property.*`, `unit.*`, `asset.*`, `tenant.*`) |
| `offers` | object[] | `sell` partners: `{offer_id, title, monthly_price_eur, min_term_months, details}`, or `offers_endpoint` for live offers |
| `pricing` | object | `deliver` partners: `model` (`framework_agreement` \| `quote`), fees and rates |
| `required_context` | object[] | `{key, source, pii, consent_required}`: what the partner needs and where centrix gets it |
| `availability` | object | `mode`: `api` (`availability_endpoint`), `conversational` (asked per job) or `static` (`hours`) |
| `transport` | object | `{type: "api", base_url, auth}`, `{type: "portal", url, notify}` (partner works in the centrix partner page) or `{type: "conversational", channel: "whatsapp" \| "email", address}` |
| `status_events` | string[] | Lifecycle states the partner reports (subset of section 3) |
| `documents_returned` | string[] | `contract`, `invoice`, `visit_report`, `meter_reading`, `confirmation` |
| `sla` | object | `{urgent_response_hours, standard_response_hours}`; Debye re-dispatches on breach |

Examples: [`partners/heizung-schmidt.json`](../partners/heizung-schmidt.json) (deliver, conversational) and [`partners/example-fibre.json`](../partners/example-fibre.json) (sell, api).

## 3. Lifecycle

```
deliver:  requested → accepted → scheduled → in_progress → completed → invoiced → closed
sell:     offered   → accepted → signed    → active                              → closed
any:      → declined | needs_info | cancelled
```

Each transition is a `status_event`:

```json
{
  "order_ref": "ord_8f2c",
  "partner_id": "heizung-schmidt",
  "status": "scheduled",
  "at": "2026-11-20T18:40:00+01:00",
  "data": { "slot_start": "2026-11-21T08:00:00+01:00", "slot_end": "2026-11-21T10:00:00+01:00" },
  "documents": []
}
```

## 4. API transport

| Direction | Call | Body |
|---|---|---|
| centrix → partner | `POST {base_url}/eligibility` | `{address, postcode, asset?, date?}` → `{eligible, reasons[]}` |
| centrix → partner | `GET {base_url}/offers?postcode=…` or `GET {base_url}/availability?from=…` | → offers or slots |
| centrix → partner | `POST {base_url}/orders` | `{order_ref, offer_id?, context{consented fields}, consent{data_shared, given_at, channel, purpose}}` → `{partner_order_id, status}` |
| partner → centrix | `POST /api/partners/{partner_id}/events` | status_event (section 3); signed with a shared secret (HMAC header) |

Documents are sent as URLs or base64 with `{kind, filename, mime}`.

### 4.1 What is built (Heiztechnik API GmbH, `partners/heiztechnik-api.json`)

- **Order out** (`backend/app/partners/transport.py`): when `services.dispatch_job` passes its gates (consent + staff approval, unchanged) and `transport.type` is `api`, centrix POSTs `{base_url}/orders` with `{order_ref: "ord_<case_id>", partner_id, case{case_id, type, title, summary, error_code}, trade, priority, cost_cap_eur, slot_hints[{start,end}], context, consent{data_shared, given_at, channel, purpose}, events_webhook}`. `context` holds the manifest's `required_context` keys, and keys with `consent_required` only when the tenant consented for this partner and case. The raw body is signed: `X-Centrix-Signature: sha256=<hex HMAC-SHA256>` with the secret from the env var named in `transport.auth.secret_env`. The answer's `partner_order_id` is stored on the case (`data.partner_order`). If the partner is unreachable or the secret is missing, the case keeps status `requested` and a `job.send_failed` event shows it to staff; nothing crashes. `portal` partners behave exactly as before.
- **Events in** (`backend/app/partner_events_api.py`): `POST /api/partners/{partner_id}/events` with a status_event (§3), signed the same way. 401 bad/missing signature, 422 wrong shape or unknown status, 404 unknown `order_ref`, 409 transition not allowed by the lifecycle. Each event calls the same services as the partner page: `accepted` → `partner_accept` (with `data.slots: [{start,end}]` → `propose_slots`, may repeat to re-propose), `scheduled` (`data.slot_start` of a proposed slot) → `confirm_slot`, `in_progress` → event only, `completed` (+ documents `photo`, `invoice`, `visit_report`; `data.invoice` may carry the invoice fields so no OCR is needed) → `record_completion` with the price check, `invoiced` → invoice + price check, `declined`/`cancelled` → `partner_decline`, `needs_info` (`data.question`) → `job.needs_info` + `case.data.open_question`. Documents come as `base64` or as a `url` on the partner's own `base_url` host (no other hosts are fetched), max 10 MB.
- **Lifecycle check**: the partner-side state is derived from the case status (`slots_proposed` counts as `accepted`); `in_progress` is optional between `scheduled` and `completed`; nothing moves after `declined`, `cancelled` or `closed`.
- **Fake partner**: `python scripts/fake_partner.py --port 8100 --debye http://localhost:8000` (needs `PARTNER_API_SECRET` in `.env`). It accepts after ~3 s, proposes the first two `slot_hints` after ~3 s more, and posts `completed` + the demo invoice from its page (`http://localhost:8100`) or with `--auto-complete 10`.

## 5. Conversational transport

For partners without an API. Debye:

1. Sends a **job card** to `transport.address` on the given channel: what, where, asset, photos (if consented), urgency, with buttons (Accept / Decline).
2. Reads replies (text, voice, photos, PDFs) and maps them to lifecycle events: "Morgen 8–10 oder Do 14–16" → slots proposed; "erledigt" + photo → completed; PDF invoice → invoiced (fields extracted and price-checked).
3. Writes the same `status_event`s as an API partner would. centrix doesn't care which transport produced them.

## 6. Consent and privacy

- Before any handover, Debye asks the resident: "I'll share {fields} with {partner} so they can {purpose}. OK?" One tap.
- Stored record: `{contact_id, partner_id, case_id, data_shared[], purpose, channel, given_at, revoked_at}`; matches the `consent` object in reltix's result payload.
- Only consented `required_context` keys leave centrix. Sensitive access details (key-safe codes) are released just in time (on the job day) and logged.
- Data minimisation: partners never get lease, rent or other tenants' data.

## 7. Result written back

When the lifecycle reaches `closed` (deliver) or `active` (sell), centrix links the outcome to the unit: `service_contract` or `service_job` with partner, status, dates, price/invoice, documents and the consent record.

### 7.1 What is built: the sell flow (Example Fibre GmbH, `partners/example-fibre.json`)

Proof that the spec is generic: the internet partner runs end to end with no fibre-specific code.

1. **Trigger** (`backend/app/triggers.py`): centrix sends `tenant.move_in {unit_id, contact_id?, move_in_date?}` to `POST /api/centrix/events` (staff unit page button "Tenant moves in", or `POST /demo/trigger/move_in`). Every active partner whose `triggers` contain the event is checked with its `eligibility` rules (`property.fibre_available eq true`, `in_service_area`); each eligible one gets a case of its `category` (`telecom.internet`, status `offered`, cost bearer tenant). Ineligible partners come back in `skipped` with the failed rules. Firing twice does not open a second offer while one is open.
2. **Offer** (`agent/flow.send_offers`): the manifest's `offers` become buttons ("Fibre 250 · €29.99/month", "Fibre 500 · €34.99/month", "No thanks").
3. **Consent**: on a pick Debye asks for the manifest's `consent_required` fields ("your name, your address and your move-in date … OK?"). Nothing leaves centrix before the tap. No staff approval: the tenant signs their own contract.
4. **Order** through the API transport (§4.1) with `offer_id` and the consented context; case status `ordered`.
5. **Lifecycle** through the events webhook: `offered → accepted → signed (+ contract document) → active`, anything else is a 409.
6. **Result** on `active`: written to the unit in reltix's shape `{unit_id, contact_id, service_contract: {partner, category, product, status, start, monthly_price_eur, consent: {data_shared, given_at, channel}}}`, stored as a `service` Contract on the unit, on the case (`data.result`) and as a JSON document; the case closes. The staff unit page lists it under "Service contracts", the tenant portal under "Your services".

Fake partner: `python scripts/fake_fibre.py --port 8101 --debye http://localhost:8000` (`FIBRE_SECRET` in `.env`) answers accepted → signed → active about 3 s apart.

## 8. Adding the next partner

1. Write the manifest (15 minutes).
2. API partner: implement 3 endpoints + the events webhook. Conversational partner: provide a WhatsApp number or email address.
3. Drop the file into `partners/`. Debye picks it up for every matching trigger.

## 9. Onboarding a partner in 2 minutes

A partner doesn't have to write the manifest by hand. The **Become a partner** page (`/partners/join`, linked from the staff Partners page as "+ Onboard a partner") asks three short steps and builds the manifest live next to the form:

| Step | Asks | Becomes |
|---|---|---|
| Company | name, trades (chips), certified brands (chips per trade) | `partner_id` (slug of the name), `category` (`repair.<first trade>`), `triggers` (`case.repair.<trade>` per trade), `capabilities.trades`, `capabilities.brands_certified` |
| Area & prices | radius around a postcode or a postcode list; fixed rates (call-out + hourly) or quote; urgent response time | `service_area`, `eligibility` (`property.postcode in_service_area`, plus `asset.type in [gas_boiler, heat_pump]` for heating-only partners), `pricing`, `sla` |
| Jobs & team | how jobs arrive (partner portal / API with base URL / WhatsApp / email), which context fields they need, technicians (name + skill chips) | `transport`, `availability`, `required_context` (personal fields always `consent_required: true`), technician roster |

Defaults fill the rest: the deliver lifecycle `status_events` (`accepted, declined, scheduled, in_progress, completed, invoiced`) and `documents_returned` (`visit_report, invoice`).

**Validation is the spec.** Every keystroke posts the manifest to the same validator that guards the save, and the page shows the checklist: schema, slug, dotted category and triggers, trades, service area, eligibility ops and fields (`property|unit|asset|tenant|case.*`), an `in_service_area` rule, context sources, **consent on every PII field**, required lifecycle events (`accepted, declined, scheduled, completed` for deliver), a complete transport, pricing model and SLA.

| Method | Path | Body → Returns |
|---|---|---|
| GET | `/api/partners/onboard/schema` | trades with brands, lifecycle, ops, transports, default `required_context` and form defaults |
| POST | `/api/partners/onboard/validate` | `{manifest}` → `{valid, checks:[{id, ok, message}]}` |
| POST | `/api/partners/onboard` | `{manifest, technicians:[{name, skills[], phone_e164?}]}` → `{partner_id, name, portal_url, technicians:[{tech_id, name, url}], manifest, file}`; 422 with the failed checks, 409 if the id belongs to a seeded partner |

On save the partner is a DB row (active), its technicians get calendars (free slots for the next 3 days), and in `DEMO_MODE` the manifest is written to `partners/<id>.json` with an extra `technicians` roster, so it survives a demo reset like any hand-written partner. `rank_partners` picks it up for the next matching case with no code change (covered by `backend/tests/test_onboarding.py`).

`service_area` with `radius_km` + `base_postcode` is evaluated without a geocoder in the demo: within 10 km the first 4 postcode digits must match, within 30 km the first 3, beyond that the first 2. A real deployment swaps in a distance lookup; the manifest stays the same.


## 10. Partner review (built)

A partner that onboards on `/partners/join` is saved with `status: "pending_review"` and is **not** ranked
or dispatched until reltix staff approve it. Partner states: `pending_review | active | rejected | suspended`
(`Partner.status`, with `Partner.review = {reviewer, decided_at, reason, checks}`); seeded partners are `active`.

- The join form sends its documents (trade licence, liability insurance, gas registration, VAT certificate,
  with numbers and valid-until dates). They are stored as `Document(kind="partner_doc", partner_id=…)`.
- `partners/verification.py` pre-checks every application: all documents present, valid-until dates in the
  future, insurance cover ≥ €1,000,000, company name the same in manifest and documents, base postcode inside
  the service area, gas registration present for the heating trade. Each row is `pass | warn | fail`.
- Staff API: `GET /api/staff/partners/applications`, `POST /api/staff/partners/{id}/approve`,
  `POST /api/staff/partners/{id}/reject {reason}` (reason required). The Partners page shows a "New partners"
  section; the inbox shows a banner.
- `services.rank_partners` and `dispatch_job` use only `active` partners (`dispatch_job` raises
  `partner_not_active` otherwise).
- Expiry: `/demo/skip-to-tomorrow` and a daily background check suspend active partners whose insurance or
  gas registration has expired (`partner.suspended` event).

## 11. Decline or no response → next partner (built)

`services.partner_decline` now calls `redispatch(case_id, reason)`. It ranks again without the partners in
`case.data.declined_by` and without non-active partners, then:
- the new partner needs consent the tenant hasn't given → status `awaiting_consent`; the agent sends one message
  ("Heizung Schmidt can't take it. I'm asking Wärme Wagner instead.") with consent buttons;
- consent is already there (or nothing personal is shared) → staff approval (`rules.approval_status`) and
  `dispatch_job`; an earlier staff approval was for the previous partner, so it is asked again;
- nobody is left → status `needs_staff` ("Needs you" in the staff inbox), and the tenant is told the
  property manager takes over.
SLA: `dispatch_job` stores `case.data.sla = {hours, sent_at, due_at}` from the manifest's
`sla.urgent_response_hours` / `standard_response_hours` (by case priority). A job still `requested` after
`due_at` counts as a decline with reason "no response within X h". This is checked on `/demo/skip-to-tomorrow`
and by a 60 s background loop. The declined job leaves the partner's inbox.
