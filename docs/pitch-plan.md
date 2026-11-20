# Debye: build plan and 3-minute pitch (reltix track)

**Track:** reltix, "Plug a Partner into centrix" · 24 h build · 3-minute pitch
**Idea:** Debye, an AI assistant that lives in the resident's WhatsApp and turns a moment in a property's life into a finished outcome with zero forms.

Judging weights, which decide every trade-off in this plan:

| Criterion | Weight | What it means for us |
|---|---|---|
| Demo quality | 30% | One flow, trigger to result, working live on real phones |
| User experience | 25% | Minimal effort for tenant, partner and property manager (PM); channel choice must be obviously right |
| Feasibility & realism | 20% | Realistic data, consent logged, partner side real (not a stub) |
| Connector spec | 15% | The next partner plugs in without redesign; prove it |
| Partner choice | 10% | One clear sentence on why this partner and this moment |

---

## 1. The decision: which flow

**Recommendation: Broken heater → craftsman (heating installer).** Keep "Move-in → internet" as a 15-second proof that the connector is generic.

Why this flow fits Debye on WhatsApp:

- **WhatsApp is where the problem already lives.** Tenants report defects by sending photos and voice notes. German trades businesses already coordinate jobs over WhatsApp. Putting both sides on the same channel is the most believable UX choice a judge will see.
- **It's the richest end-to-end process.** Triage, picking the craftsman, booking a slot, access details, the repair, the invoice and closing the case. The brief calls this out as the "deliver" example, and judges asked for processes "end to end".
- **It's visual.** Photo of the boiler error code, a list of slots on the phone, the invoice PDF landing in the unit record in centrix. All of it reads from the back of a room.
- **Partner choice (10%) answers itself.** "A broken heater in November is the most urgent, most frequent and most phone-heavy case a PM has. The brief says it takes a dozen calls. We make it zero."
- **It has a built-in wow: deduplication.** Two tenants in the same building report "no heat". Debye knows from centrix that the building has *central* gas heating, so it opens **one** case for the boiler instead of two, and tells the second tenant "we're already on it, the technician comes Thursday 8–10". Few teams will think of this.

Why not internet at move-in as the main flow: it's proactive, which is good, but the "partner" is a contract API with one signature step. It's harder to make visibly impressive, and every second team will pick it because it's the first example in the brief.

---

## 2. The story we demo (the golden path)

Seed data: Musterstraße 12, Aachen, unit 4b, tenant Lena Hoffmann, 1972 building, gas central heating, boiler Vaillant ecoTEC plus (installed 2014, last service 2025-10). Neighbour Jonas Weber in unit 2a. PM: a reltix property manager. Partner: "Heizung Schmidt GmbH" (fictional), a heating installer with a framework agreement.

1. **Detect.** Lena sends Debye a WhatsApp voice note: *"Hi, die Heizung ist kalt seit heute morgen"* plus a photo of the boiler display showing error **F.28**.
2. **Understand with context.** Debye transcribes the voice note and reads the photo. From centrix it already knows the unit, the boiler model and that the heating is central. It does **not** ask for address, name or phone. It asks one smart question with buttons: *"Are the radiators cold everywhere, or only in one room?"* → `Everywhere`.
3. **Triage.** F.28 on a Vaillant means the ignition failed. Debye tells Lena one safe check ("is the gas tap open?"). Still broken → a repair case is opened in centrix, priority *urgent* (heating, November), and the cost bearer is the landlord.
4. **Dedupe (wow).** Jonas from 2a reports the same thing a minute later. Debye links him to the existing case: "Already on it."
5. **Consent.** *"I'll share your name, phone, unit and the photo with Heizung Schmidt GmbH so they can book a visit. OK?"* → `Yes, share`. A consent record is written.
6. **Pick the partner.** Debye ranks partners: trade = heating, Vaillant-certified, serves PLZ 52062, framework price, rating, earliest availability, has worked on this building before. The centrix dashboard shows **why** it picked Schmidt (explainable).
7. **PM in the loop, only where needed.** Estimated cost is under the €500 auto-approval limit, so the job goes out automatically. The dashboard shows the rule ("auto-approved: < €500, urgent heating"). Above the limit, the PM gets a one-click approve card instead.
8. **The partner receives the job on WhatsApp.** The craftsman's phone gets a job card: address, floor, boiler model, error code, photo, tenant availability, with buttons `Accept` / `Decline`. He accepts and replies in plain text: *"Morgen 8–10 oder Do 14–16"*.
9. **Book the slot.** Debye parses that and sends Lena a WhatsApp list: `Tomorrow 8–10` / `Thu 14–16` / `Neither`. She taps one. Both sides get a confirmation; a calendar entry is linked to the case. Access: "Will you be home?" If not, the key-safe code goes to the craftsman only on the job day, logged.
10. **Close the loop.** Demo-mode "skip to tomorrow" button. The craftsman sends *"erledigt"* + a photo + the invoice PDF. Debye extracts the invoice (number, amount, VAT, line items), checks it against the framework price, and asks Lena *"Is the heating warm again?"* → 👍. The case closes. The invoice, the visit report and the boiler service entry appear on **unit 4b in centrix**. The owner gets a two-line summary.

On the dashboard, every step appears live as a timeline on the case. That is the "result appears on the unit" moment the brief asks for.

---

## 3. Architecture

```
          Tenant phone (WhatsApp)          Craftsman phone (WhatsApp)
                     \                              /
                      WhatsApp Cloud API (Meta) webhook
                                   |
                        ┌──────────▼──────────┐
                        │  Channel adapters   │  whatsapp | webchat (portal) | email(stub)
                        └──────────┬──────────┘
                                   │ normalized Message{from, contact_id, text, media, buttons}
                        ┌──────────▼──────────┐
                        │   Debye agent       │  Claude with tool use, one conversation
                        │   (orchestrator)    │  state per case + contact
                        └───┬────────┬────────┘
              tools:        │        │
   centrix API (mock) ◄─────┘        └─────► Partner connector layer
   get_unit, get_contact,                      ├─ API transport (big partners)
   open_case, link_case,                       └─ Conversational transport (WhatsApp
   record_consent, attach_doc,                     adapter: turns chat replies into
   request_pm_approval                             standard status events)
                                   │
                        ┌──────────▼──────────┐
                        │  SQLite + event bus │──SSE──► centrix dashboard (React)
                        └─────────────────────┘          + partner view + tenant portal
```

### Stack (pick what the team already knows; this is a safe default)

| Layer | Choice | Why |
|---|---|---|
| Backend | Python **FastAPI** (or Node/Express if the team is JS) | Fast webhooks, async, simple |
| DB | **SQLite** + seed JSON | Zero setup; matches "a JSON file or small database" in the brief |
| LLM | Claude via the Anthropic API with tool use: `claude-sonnet-5-5` for the agent, `claude-haiku-5-5` for cheap classification and invoice extraction | Tool use gives structured, auditable actions; vision reads the error-code photo and the invoice PDF |
| Speech-to-text | **OpenAI** transcription (Whisper / gpt-4o-transcribe) for voice notes | Voice notes are how people actually report defects. OpenAI is an event sponsor, so visible use helps with the final jury and sponsor prizes |
| Voice replies (nice-to-have) | **ElevenLabs** TTS: Debye answers a voice note with a short voice note in German | Second event sponsor; makes the WhatsApp exchange feel natural on stage. Keep replies under 10 s |
| WhatsApp | **Meta WhatsApp Cloud API**, test number | Free and instant; no business verification needed for the test number |
| Tunnel/hosting | `cloudflared` or ngrok during dev; deploy to Railway/Render/Fly for the demo | The webhook needs public HTTPS |
| Frontend | Vite + React + Tailwind; SSE for live updates | One app with three routes: `/centrix`, `/partner`, `/portal` |
| Phone on projector | `scrcpy` (Android) or QuickTime mirroring (iPhone) | Judges must see the real phone |

### Data model (what centrix realistically holds)

- `properties` (address, building year, heating type and whether it's central, energy certificate)
- `units` (floor, sqm, rooms, meters)
- `assets` (boiler make/model/install year/last service; this is realistic because PMs keep maintenance records for central heating)
- `contacts` (owners, tenants, partner staff; phone and email; preferred language)
- `contracts` (lease; partner framework agreements with price lists and the auto-approval limit)
- `cases` (type, priority, status, cost bearer, linked units/contacts)
- `case_events` (the timeline: every message, decision and status change)
- `documents` (photos, invoice, visit report, linked to case + unit)
- `consents` (who, what data, to which partner, when, which channel, purpose)
- `partners` (loaded from connector manifests; see section 4)

**Assumptions to state out loud** (the brief says "tell us what you assumed"):
- Tenant phone numbers are in centrix from the lease, and tenants opted in to WhatsApp at onboarding (a WhatsApp Business requirement).
- The PM has framework agreements with a few local trades, including price lists and a spending limit per job without owner approval.
- Heating repairs are the landlord's cost. We don't apply the small-repairs clause to heating.
- Boiler make and model come from the PM's maintenance records.

### Debye agent design (judges reward deliberate agent design)

- **One system prompt per role**: Debye talks to tenants (friendly, German/English, short) and separately to partners (terse, job-card style). Same backend, different persona and tools.
- **Tools, not free text, for every side effect**: `open_case`, `link_to_case`, `record_consent`, `rank_partners`, `send_job`, `propose_slots`, `confirm_slot`, `attach_document`, `request_pm_approval`, `close_case`. Each call writes a `case_event`, so the timeline doubles as an audit log.
- **Hard rules in code, not in the prompt**: no partner gets data without a consent record; jobs over the limit need PM approval; key-safe codes are released only on the job day. Say this in Q&A: "the model proposes, the rules decide."
- **Use WhatsApp-native UI**: reply buttons (max 3), list messages (max 10 rows), media. No links to web forms. That is the "zero forms" promise.
- **Deterministic fallbacks**: if the LLM call fails, fall back to a scripted path so the demo never dead-ends.

### WhatsApp risks and how to defuse them

| Risk | Mitigation |
|---|---|
| Business-initiated messages need an approved template outside the 24 h window | The tenant starts the conversation (she reports the defect), so the window is open. **Before the pitch, send "hi" from the craftsman's phone too**, so his window is open. Also submit 2–3 utility templates (job offer, slot confirmation) in hour 1. They usually get approved quickly, but don't count on it. |
| Test number only messages up to 5 verified recipients | Verify the tenant, neighbour and craftsman phones in hour 1. |
| Temporary access token expires after 24 h | Create a system-user permanent token in hour 1. |
| Venue Wi-Fi / Meta outage | Build a **web-chat channel adapter** that looks like WhatsApp and runs on the same backend. It also scores the "channels share the same context" bonus (the tenant continues the conversation in the portal). Plus a recorded backup video. |
| Fallback provider | Twilio WhatsApp sandbox as plan C (join code, no approval). |

---

## 4. Partner connector spec (15%: make it generic and prove it)

Core idea: **every partner is described by one manifest plus a standard order lifecycle.** Two transports implement the same lifecycle:

- **API transport** for partners with systems (internet providers, energy suppliers, insurers).
- **Conversational transport** for the long tail of small trades that will never build an API. Debye talks to them on WhatsApp or email and turns their replies into the same standard events.

That second transport is our strongest feasibility argument. Most craftsmen have WhatsApp, not webhooks.

### Manifest (example)

```json
{
  "partner_id": "heizung-schmidt",
  "name": "Heizung Schmidt GmbH",
  "category": "repair.heating",
  "kind": "deliver",
  "service_area": { "postcodes": ["52062", "52064", "52066"] },
  "capabilities": { "trades": ["heating", "plumbing"], "brands_certified": ["Vaillant", "Viessmann"] },
  "eligibility": [
    { "field": "asset.type", "op": "in", "value": ["gas_boiler", "heat_pump"] },
    { "field": "property.postcode", "op": "in_service_area" }
  ],
  "required_context": [
    { "key": "address", "source": "property.address", "pii": true },
    { "key": "unit_floor", "source": "unit.floor" },
    { "key": "asset", "source": "asset[type=heating]" },
    { "key": "tenant_contact", "source": "tenant.phone", "pii": true, "consent_required": true },
    { "key": "photos", "source": "case.documents[type=photo]", "consent_required": true }
  ],
  "pricing": { "model": "framework_agreement", "callout_fee_eur": 89, "hourly_eur": 72 },
  "availability": { "mode": "conversational" },
  "transport": { "type": "conversational", "channel": "whatsapp", "address": "+49..." },
  "sla": { "urgent_response_hours": 4 }
}
```

The internet provider uses the **same schema**. Only the values change: `"kind": "sell"`, `"category": "telecom.internet"`, an `offers` endpoint, `"transport": {"type": "api", "base_url": ...}`, and eligibility based on `address_availability`.

### Standard lifecycle (all partners)

`requested → accepted | declined → scheduled → in_progress → completed → invoiced → closed` (plus `cancelled`, `needs_info`)

For `sell` partners: `offered → accepted → signed → active`.

### API transport endpoints (what an API partner implements)

| Endpoint | Purpose |
|---|---|
| `POST /eligibility` | Can you serve this unit? (address, asset, date) |
| `GET /offers` or `GET /availability` | Products and prices, or time slots |
| `POST /orders` | Place an order/job with the consented context only |
| `POST {centrix}/webhooks/partner-events` | Partner pushes status changes and documents (contract PDF, invoice) |

**Privacy built into the spec:** a partner only ever receives `required_context` fields the resident consented to. Every handover writes a consent record (fields, partner, purpose, channel, timestamp) exactly like the result payload in the brief. Data is minimised per step (the key-safe code goes out on the job day only).

**Live proof (do it if time allows, it's worth the 15%):** in the demo, drop a second manifest (`example-fibre.json`) into the partners folder. A move-in event fires, and Debye offers Lena internet on WhatsApp with no code change. Even 15 seconds of this answers "generic enough?" better than any slide.

---

## 5. Team split and 24-hour timeline

Assuming 4 people (adjust if 3: merge B and D).

| Role | Owns |
|---|---|
| **A: Agent & WhatsApp** | Cloud API setup, webhook, channel adapters, Debye agent and tools, prompts |
| **B: centrix backend & connector** | Data model, seed data, centrix mock API, partner ranking, manifests, lifecycle, consent, the spec doc |
| **C: Frontend** | centrix dashboard (unit record, case timeline, PM approval card, "why this partner"), partner view, web-chat fallback |
| **D: Pitch & demo owner** | Pitch script, slides (max 3), demo choreography, reset script, backup video, README, submission; also the QA tester from hour 8 |

**Event facts (MAIN Maastricht):** hacking Fri 13:30 → submission Sat 10:30 (about 21 real hours). University rooms close Fri 18:00, so mentor time is mostly before then, and you need **a place booked to work overnight**. Grand-final pitches are Sat afternoon on stage at Sint Janskerk: projector, bad Wi-Fi, use a phone hotspot.

| Time | Milestone |
|---|---|
| **Tonight (before start)** | Accounts only, no project code (check the event rules): Meta developer app + WhatsApp test number, verify the 3 demo phones, Twilio sandbox as backup, Anthropic + OpenAI + ElevenLabs keys, hosting account. Book the overnight workspace. Everyone reads the brief and this plan. |
| **Fri 13:30–14:30** | Find the reltix people in the first 30–60 min. Ask: what does an outstanding entry look like, which criterion matters most, which partner/moment would you most like to see, what do teams usually get wrong? **Write down their exact words** and reuse them in the pitch. Lock the flow and write the demo script **first**. Permanent token, submit templates. Repo + deploy pipeline. |
| **14:30–17:30** | **Riskiest piece first:** a WhatsApp message round-trips through the backend and Claude replies with a button. Seed DB. Dashboard skeleton with SSE. Second mentor check before 18:00 with what you have. |
| **18:00** | Move to the overnight location. |
| **18:00–20:00** | Tenant flow: voice note → STT, photo → vision, triage, case created and visible live on the dashboard. Consent. Partner job card to the craftsman's phone. **Checkpoint 20:00: the golden path runs end to end, ugly is fine.** |
| **20:00–01:00** | Slots, close the loop (completion photo, invoice extraction, tenant confirmation, documents on the unit), dedupe for the neighbour, PM approval card. **Hosted V1 by 01:00.** |
| **01:00–06:00** | Staggered sleep (at least 3–4 h each). Whoever is awake: connector spec doc, second manifest (internet), web-chat fallback, reset script, "skip to tomorrow" button. |
| **06:00 feature freeze.** | Polish only what's on screen during the pitch. README with architecture diagram and assumptions. |
| **08:30–10:00** | Record the backup video, final README, submit by **10:00** (deadline 10:30). |
| **Sat before the final** | Rehearse the pitch at least 3–5 times with a timer, target 2:50. Open the WhatsApp windows on every demo phone. Test the hotspot and the mirroring setup. |

**Demo hygiene:** one command resets the DB to the seed state; phones charged, Do Not Disturb on except WhatsApp; notification previews off; a hotspot as Wi-Fi backup; pre-generated fallback replies cached in case the LLM is slow.

---

## 6. The 3-minute pitch

Principles from the research: open with what it does and for whom (not market size). The live demo is most of the time. One wow moment. End on time and stop talking. Two people: one narrates, one drives the phones. The left half of the projector shows the mirrored phones, the right half the centrix dashboard.

| Time | Who | What happens on screen | What is said (draft) |
|---|---|---|---|
| **0:00–0:20** Hook | Presenter | Photo: cold radiator, a phone call log with 12 calls | "It's November in Aachen. Lena's heating dies. Today that means a dozen calls and emails between her, the property manager and a heating installer before anyone shows up. We made it zero calls and zero forms." |
| **0:20–0:30** What | Presenter | Debye logo + one line | "This is Debye: reltix's assistant in the resident's WhatsApp, plugged straight into centrix." |
| **0:30–1:25** Tenant side (live) | Driver on the tenant phone | Voice note + photo sent; Debye replies with one question and buttons; case appears live on the dashboard with the boiler model already filled in | "Lena just sends a voice note and a photo, like she would to a friend. Debye already knows her unit, her boiler and that the heating is central, so it asks one question, not twelve. Error F.28: ignition. The case is in centrix, marked urgent." Neighbour message arrives: "And when her neighbour reports the same thing? Debye knows it's one central boiler. One case, not two." |
| **1:25–2:05** Partner side (live) | Driver on the craftsman phone | Consent tap; "why this partner" card; job card on the craftsman's WhatsApp; he accepts and types slots; Lena gets a slot list and taps | "Lena agrees to share her details, and we log that consent. Debye picks Heizung Schmidt: Vaillant-certified, framework price, free tomorrow, and under the PM's €500 limit, so no approval click is needed. The installer gets the job on WhatsApp, where he already works. No app, no portal. He types two time slots; Lena taps one. Booked." |
| **2:05–2:30** Close the loop | Driver | Skip to tomorrow → "erledigt" + invoice PDF → Lena 👍 → invoice and report appear on unit 4b | "Next day: he sends a photo and his invoice. Debye reads it, checks it against the agreed prices, asks Lena if it's warm, and files everything on the unit in centrix. Case closed. The PM touched nothing." |
| **2:30–2:50** Connector + realism | Presenter | One slide: manifest + lifecycle; optionally the internet manifest dropped in live | "Every partner plugs in with one manifest and one lifecycle. Big partners use our API. The small trades that will never build one plug in through WhatsApp, and Debye turns their messages into the same status events. Partners only ever get data the resident consented to." |
| **2:50–3:00** Close | Presenter | Back to the dashboard with the closed case | "One message from Lena. A finished repair on the unit. That's Debye." *Stop.* |

**Make "zero forms" visible:** a counter on the dashboard case card, e.g. **"14 fields pre-filled from centrix · tenant gave: 1 voice note, 2 taps"**. Point at it during the demo and end on the before/after: "about 12 calls and emails → 1 message and 2 taps".

**Speak their language:** centrix, the property record, moment → outcome, zero forms, close the loop, connector spec, partner marketplace. Use their example payload shapes (`tenant.move_in`-style events, `service_contract` with `consent`) so the output looks native to their platform. Put your assumptions on the connector slide or a backup slide.

**If the live demo breaks:** the driver switches to the web-chat channel (same backend), or straight to the backup video at the matching timestamp. Never debug on stage.

**Name nugget for the opener or Q&A:** Nobel laureate Peter Debye was born in Maastricht, where the final is held, and studied in Aachen, where the demo property is. One sentence, and it makes the name memorable.

### Q&A prep (have 1-sentence answers ready)

- **"What did you build vs. wire together?"** The agent tools, the partner ranking, the consent and approval rules, the connector spec and both transports, the centrix mock. WhatsApp, Claude and STT are off-the-shelf.
- **"What breaks first at scale?"** Name it honestly: template approval and per-message costs at Meta, and partner availability parsing from free text. The fix is calendar integration for partners who have one.
- **"GDPR?"** Data minimisation per step, consent records per partner and purpose, EU hosting, WhatsApp opt-in at lease signing, key codes released just in time, PM can audit every action on the timeline.
- **"Why WhatsApp and not the portal?"** Tenants don't log into portals when the heating is broken; they text. Craftsmen already run their business on WhatsApp. The portal shows the same case for anyone who prefers it.
- **"What if the craftsman declines or doesn't answer?"** SLA timer from the manifest (4 h for urgent). Debye moves to the next ranked partner and tells the tenant.
- **"How do reltix and the partner earn?"** Partners get jobs with no customer acquisition cost and pay a referral fee or commission per completed job/contract. reltix cuts PM hours per case and improves tenant satisfaction. For sell partners (internet, energy) it's a classic marketplace commission.
- **"What if the tenant doesn't reply?"** Debye sends one reminder, then the PM sees the case flagged on the dashboard. For urgent heating the craftsman can still be booked with key-safe access if the tenant consented earlier.
- **"Why WhatsApp, given GDPR and the Business API?"** Reach: almost every tenant in Germany has it. Production uses the official Business API with opt-in at lease signing, approved templates and EU data processing. Personal data lives in centrix, not in the chat.
- **"How do you avoid the AI doing something wrong?"** The model proposes, rules in code decide: consent gates, spending limits, PM approval above the limit, full audit log.

---

## 7. Deliverables checklist

- [ ] Working demo: event → resident on WhatsApp → partner gets job → result on the unit
- [ ] Connector spec (markdown in the repo: manifest schema, lifecycle, endpoints, consent rules, two example manifests)
- [ ] README: what it does, setup, architecture diagram, which file does what, **assumptions**, known limitations, honest AI-use note
- [ ] Backup demo video (60–90 s, real narration)
- [ ] 3 slides max: hook, connector, close
- [ ] Repo with real commit history

## 8. Stretch goals (only after H12 checkpoint passes)

1. Second partner via manifest (internet at move-in), shown live (connector spec 15%)
2. Tenant portal page showing the same case and continuing the chat (channel bonus)
3. PM approval flow above the limit, shown with one click
4. Proactive detection: boiler service overdue → Debye books the maintenance visit before it breaks
