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

## 8. Adding the next partner

1. Write the manifest (15 minutes).
2. API partner: implement 3 endpoints + the events webhook. Conversational partner: provide a WhatsApp number or email address.
3. Drop the file into `partners/`. Debye picks it up for every matching trigger.
