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

### `needs_info`: the partner asks the resident

Built for portal partners. A partner who needs something before the visit asks the resident from the job card instead of phoning around.

| Method | Path | Body → Returns |
|---|---|---|
| POST | `/api/partner/{partner_id}/jobs/{case_id}/question` | `{text}` (1–500 chars) → the job detail with `questions[]` and `open_question`; 404 if the job isn't this partner's, 409 while a question is still open or the job is closed, 422 for an empty or too-long question |

1. The question is stored on the case (`data.questions[]`, `data.open_question`), logged as `job.needs_info` and sent to the resident on WhatsApp: "Ali from Heizung Schmidt GmbH asks: Is there parking nearby?" (the assigned technician's first name, else the partner's staff contact).
2. The resident's next free-text reply on that case is the answer. Button taps and the hot-water diagnosis keep their own handling; the reply goes to the open question only if neither took it. Debye confirms "Thanks, I've passed that on to …".
3. The answer is stored on the question (`answer`, `answered_at`), logged as `job.info_provided` and shown on the partner's job card and the staff timeline.

One open question per case at a time. A partner only sees its own questions.

**Planned:** API partners sending `needs_info` as a `status_event` with `data.question`, and conversational partners asking by message (section 5). Both would reuse the same store and tenant routing.

## 4. API transport

| Direction | Call | Body |
|---|---|---|
| centrix → partner | `POST {base_url}/eligibility` | `{address, postcode, asset?, date?}` → `{eligible, reasons[]}` |
| centrix → partner | `GET {base_url}/offers?postcode=…` or `GET {base_url}/availability?from=…` | → offers or slots |
| centrix → partner | `POST {base_url}/orders` | `{order_ref, offer_id?, context{consented fields}, consent{data_shared, given_at, channel, purpose}}` → `{partner_order_id, status}` |
| partner → centrix | `POST /api/partners/{partner_id}/events` | status_event (section 3); signed with a shared secret (HMAC header) |

Documents are sent as URLs or base64 with `{kind, filename, mime}`.

## 5. Conversational transport

For partners without an API. Debye:

1. Sends a **job card** to `transport.address` on the given channel: what, where, asset, photos (if consented), urgency, with buttons (Accept / Decline).
2. Reads replies (text, voice, photos, PDFs) and maps them to lifecycle events: "Morgen 8–10 oder Do 14–16" → slots proposed; "erledigt" + photo → completed; PDF invoice → invoiced (fields extracted and price-checked).
3. Writes the same `status_event`s as an API partner would. centrix doesn't care which transport produced them.

**Status: planned.** The demo partners with `transport.type: conversational` are handled through the partner portal today. The job-card message, reply parsing and event mapping above are not built yet.

## 6. Consent and privacy

- Before any handover, Debye asks the resident: "I'll share {fields} with {partner} so they can {purpose}. OK?" One tap.
- Stored record: `{contact_id, partner_id, case_id, data_shared[], purpose, channel, given_at, revoked_at}`; matches the `consent` object in reltix's result payload.
- Only consented `required_context` keys leave centrix. Sensitive access details (key-safe codes) are released just in time (on the job day) and logged; see below.
- Data minimisation: partners never get lease, rent or other tenants' data.

### Access details, just in time

- Stored on the unit: `Unit.access = {key_safe_code, intercom_name, parking_note}` (seeded for `unit_4b`).
- A partner that needs them lists `{"key": "access_details", "source": "unit.access", "pii": true, "consent_required": true}` in `required_context`. The three seeded heating partners do.
- Debye's consent covers `access_details`, and the consent text tells the resident: "They only get the access details (key safe, intercom) on the day of the visit."
- The job detail (`GET /api/partner/{id}/jobs/{case_id}` and the technician page) carries `access`:

| Situation | `access` |
|---|---|
| unit has no access details | `null` |
| no consent for `access_details` | `{consented: false, released: false}` |
| consent, no slot booked yet | `{consented: true, released: false, available_on: null}` |
| consent, not the slot's day (or case closed) | `{consented: true, released: false, available_on: "YYYY-MM-DD"}` |
| consent, on the slot's day (demo clock) | `{consented: true, released: true, available_on, key_safe_code, intercom_name, parking_note}` |

The first release writes an `access.released` event (fields and partner) to the case timeline. The day before and the day after, the values are held back.

**Planned:** pushing access details to API partners on the job day (today they are only shown in the portal and on the technician page), and letting the resident revoke consent.

## 7. Result written back

When the lifecycle reaches `closed` (deliver) or `active` (sell), centrix links the outcome to the unit: `service_contract` or `service_job` with partner, status, dates, price/invoice, documents and the consent record.

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

### Start from the partner's website

The partner registration flow (`/partner/register`) opens with **Start with your website**. The partner types their URL and clicks **Fill in for me**, or **Skip** to the empty form.

| Method | Path | Body → Returns |
|---|---|---|
| POST | `/api/partners/onboard/from-website` | `{url}` → `{fields, manifest_draft, sources, message?}`; 400 for a URL that isn't http(s) or points at a local or private address |

- Debye fetches the page the partner entered plus `/impressum` and `/kontakt` on the same host (German Impressum pages carry the legal name, address, VAT ID and register entries). Each page: 10 s timeout, at most ~500 KB, HTML stripped to text with `mailto:` and `tel:` links kept.
- **SSRF guard:** only `http`/`https`; the host must resolve to public addresses only (loopback, private, link-local, reserved and the cloud metadata IP are refused); redirects are followed by hand and every hop is checked again.
- The text goes to the LLM (same provider setting as invoice extraction, `LLM_PROVIDER`) with a strict JSON schema. Results are cleaned: trades and brands are limited to the onboarding schema lists, postcodes must be 5 digits, VAT IDs are normalised.
- `fields` has one entry per field found, `{value, confidence, source_snippet}`, for `name, street, postcode, city, phone, email, vat_id, hwk_no, trades, brands, service_area`. `manifest_draft` is the same data as a manifest skeleton; it goes through `POST /api/partners/onboard/validate` like any other.
- **Nothing is saved.** The form is pre-filled, each filled field carries a "from your website" tag until the partner edits it, and the partner still checks and submits every step.
- No API key, a site that can't be opened, or an unusable answer: `{fields: {}}` with a message ("Please fill in the form."), and the partner continues by hand.

Covered by `backend/tests/test_website_autofill.py` (saved HTML fixture, stubbed resolver and LLM, SSRF cases).

`service_area` with `radius_km` + `base_postcode` is evaluated without a geocoder in the demo: within 10 km the first 4 postcode digits must match, within 30 km the first 3, beyond that the first 2. A real deployment swaps in a distance lookup; the manifest stays the same.

