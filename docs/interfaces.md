# Debye (AI assistant): team contracts

Owner of this file: the code lead. Coders don't change a contract on their own; ask the lead (message the lead session) and the lead updates this file on `main`.

## 0. Product decisions (v2, supersede older docs where they differ)

- Product name: **Debye (AI assistant)**. In UI copy: "Debye", subtitle "AI assistant".
- **The resident (tenant/student) talks to Debye purely through WhatsApp.** No resident web page. (The web-chat adapter stays only as a hidden stage fallback, owned by the agent coder, styled minimally.)
- **Partners have their own web page** (`/partner`): job inbox, accept/decline, propose time slots, mark done with photo + invoice PDF upload. The heating installer does NOT use WhatsApp in the demo.
- **Staff (reltix property managers) have their own web page** (`/staff`, the centrix stand-in): unit record, cases with live timeline, approvals, consent records, partner ranking, documents.
- Visual design follows https://www.reltix.de/ (designer delivers `docs/design/` with tokens + Figma link). Frontend must take colours, type and spacing from `frontend/src/theme.ts`, never hard-code them, so the design can land late without rework.

## 1. Ownership (who may edit which files)

| Session | Owns (only edits these) |
|---|---|
| **backend-core** | `backend/app/main.py`, `config.py`, `db.py`, `models.py`, `seed.py`, `events.py`, `services.py`, `rules.py`, `staff_api.py`, `partner_api.py`, `demo.py`, `backend/app/partners/**`, `scripts/**`, `backend/tests/**`, `backend/requirements.txt`, `Dockerfile` |
| **agent-whatsapp** | `backend/app/channels/**`, `backend/app/router.py`, `backend/app/agent/**`, `backend/app/media.py`, `backend/app/notify.py`, `backend/tests/agent/**` (add deps by asking backend-core or in a separate `backend/requirements-agent.txt`) |
| **frontend** | `frontend/**` |
| **designer** | `docs/design/**` (+ the Figma file) |
| **lead** | `docs/*.md`, `data/**`, `partners/**`, `README.md`, merges to `main` |

Each session works on its own branch and opens a PR to `main` in `Sh3llshock/debye`. Small PRs, early and often. The lead reviews and merges.

## 2. Stack

Python 3.11+, FastAPI, SQLModel (SQLite at `backend/debye.db`), `anthropic`, `openai`, `httpx`. Frontend: Vite + React + TypeScript + Tailwind, built to `frontend/dist`, served by FastAPI at `/`. Dev: backend on :8000, Vite on :5173 with proxy `/api`, `/files` → :8000.

## 3. Python contracts

### 3.1 `models.py` (backend-core)
Tables as in [technical-plan.md §3](technical-plan.md). IDs are short strings (`case_0001`, `doc_0001`). Timestamps are timezone-aware ISO strings (Europe/Berlin offset).

### 3.2 `events.py` (backend-core)
```python
async def publish(type: str, case_id: str | None, payload: dict) -> None
def record_event(case_id: str, actor: str, kind: str, summary: str, data: dict | None = None) -> CaseEvent
    # writes case_event AND publishes {"type": kind, "case_id": ..., "event": <CaseEvent dict>}
```
`actor` ∈ `debye | tenant | partner | staff | system`.

### 3.3 `services.py` (backend-core): what the agent calls
```python
def get_contact_by_phone(phone_e164: str) -> Contact | None
def get_unit_context(unit_id: str) -> dict            # property, unit, assets, lease, open cases (JSON-safe)   # + "notices": [{id, title, body, kind, active, starts, ends}] (building notices; demo trigger maintenance_notice toggles one)
def find_open_case_for_asset(asset_id: str) -> Case | None
def open_case(reporter_contact_id: str, type: str, priority: str, summary: str,
              symptoms: str, error_code: str | None, asset_id: str | None,
              trade: str | None = None, diagnosis: dict | None = None) -> Case
    # trade: heating | plumbing | electrical (from the diagnosis); diagnosis: see §4c
def set_case_diagnosis(case_id: str, diagnosis: dict, trade: str | None = None) -> Case   # §4c, later diagnosis
def notify_caretaker(case_id: str, reason: str) -> dict   # §4c, caretaker outcome, no partner
def close_self_help(case_id: str, resolution_text: str = "") -> dict   # = close_without_partner(case_id, "self_help", text)
def close_without_partner(case_id: str, resolution: str = "self_help", note: str = "") -> dict
    # §4c: self_help | caretaker | utility → status closed, no partner, saving shown on the staff page
def link_contact_to_case(case_id: str, contact_id: str, relation: str) -> None
def attach_document(case_id: str, kind: str, filename: str, mime: str, path: str,
                    extracted: dict | None = None) -> Document
def record_consent(contact_id: str, partner_id: str, case_id: str, fields: list[str],
                   purpose: str, channel: str) -> Consent
def rank_partners(case_id: str) -> list[dict]          # [{partner_id, name, score, reasons: [str]}], top 3
def dispatch_job(case_id: str, partner_id: str) -> dict
    # raises rules.RuleViolation("consent_missing" | "approval_required")
def confirm_slot(case_id: str, slot_index: int) -> dict   # 1-based, matching list ids slot_1, slot_2, ... (decided: 1-based)
def log_message(contact_id: str, case_id: str | None, channel: str, direction: str,
                text: str | None, wa_message_id: str | None, media_ids: list[str]) -> Message
    # direction "in" | "out"; writes a message row and publishes message.in / message.out
def get_case_contacts(case_id: str) -> list[Contact]       # reporter + affected tenants (notify_tenant messages all of them)
def set_case_error_code(case_id: str, code: str) -> Case
    # sets case.error_code (e.g. read from a photo after the case was opened), records one event
    # "case.error_code" with summary "Boiler error: <label> (<code>)", re-estimates cost before dispatch;
    # same code again is a no-op. The agent calls this instead of writing Case.error_code directly.
def tenant_confirms_fixed(case_id: str, fixed: bool) -> dict   # fixed=True closes the case, returns result payload
def close_case(case_id: str, resolution: str) -> dict          # result payload (technical-plan §12)
```

### 3.3a Responsibilities (who records what)
- `open_case` does NOT assign a partner; `dispatch_job` sets `case.partner_id` and status `requested`.
- The agent/router records conversational events itself via `events.record_event` (e.g. actor `tenant`, kind `triage.answer`); services record only the events of the state changes they perform (`case.created`, `consent.recorded`, `job.sent`, `slot.confirmed`, `case.closed`, ...). Never record the same event twice.

### 3.3b Mounting (backend-core `main.py`)
```python
from app.channels.whatsapp import router as whatsapp_router   # GET/POST /webhooks/whatsapp, GET /webhooks/whatsapp/_outbox (DEMO_MODE)
from app.channels.webchat import router as webchat_router     # WS /ws/chat/{contact_id}, GET /chat/{contact_id}
app.include_router(whatsapp_router); app.include_router(webchat_router)
```
Fake send is on when `WA_TOKEN` is empty or `WA_FAKE_SEND=1`; outbound messages then go to the `_outbox` log. Simulator media: `scripts/simulate.py` uploads files to `POST /demo/sim-media`, which returns ids like `sim-ab12cd.ogg`; in fake mode the WhatsApp adapter reads them from `demo.sim_media_path(media_id)` instead of the Graph API (`local:<path>` ids may be supported too).

Extra services (additive): `message_seen(wa_message_id) -> bool` (dedupe), `add_tenant_input(case_id, label)` (zero-forms counter). Status values and notify data shapes: backend-core's hand-over notes (backend-core.md in the shared notes folder).

### 3.4 `notify.py` (agent-whatsapp): what the backend calls when staff/partner act
backend-core ships a stub that only logs; agent-whatsapp replaces it.
```python
async def notify_tenant(case_id: str, event: str, data: dict) -> None
# event ∈ "job_accepted" | "slots_proposed" (data.slots=[{start,end,label}], data.technician_name)
#        | "technician_confirmed" (data.technician_name, data.tech_id, data.slot={start,end})
#        | "job_completed" | "approval_granted" (data.partner_name) | "approval_rejected" (data.partner_name, data.reason)
#        | "partner_declined"
# Sends the right WhatsApp message (e.g. list message with slots; "Is it warm again?" buttons).
```

### 3.5 `media.py` (agent-whatsapp)
```python
async def transcribe(path: str, language: str = "de") -> str
async def extract_invoice(path: str) -> dict
# {invoice_number, date, net_eur, vat_eur, gross_eur, line_items:[{desc, qty, unit_price}], labour_hours}
```
backend-core calls `extract_invoice` from the partner "complete" endpoint (stub returns a fixed dict until the real one lands).

### 3.6 Button/list ids (WhatsApp)
`consent_yes:<case_id>`, `consent_no:<case_id>`, `cold_all:<case_id>`, `cold_some:<case_id>`, `slot_<n>:<case_id>`, `slot_none:<case_id>`, `fixed_yes:<case_id>`, `fixed_no:<case_id>`. The router handles these in code and calls `services.*`.

## 4. REST contracts (backend-core implements, frontend consumes)

All JSON. Errors: `{"detail": "..."}` with 4xx.

### Staff page
| Method | Path | Returns |
|---|---|---|
| GET | `/api/staff/units` | `[UnitSummary]` |
| GET | `/api/staff/units/{unit_id}` | `UnitDetail` (property, unit, assets, tenant, lease, documents, cases) |
| GET | `/api/staff/cases` | `[CaseSummary]` newest first |
| GET | `/api/staff/cases/{case_id}` | `CaseDetail` |
| POST | `/api/staff/cases/{case_id}/approve` | `CaseDetail` (dispatches the job, see §4b) |
| POST | `/api/staff/cases/{case_id}/reject` | `CaseDetail`, body `{reason}` (status `rejected`, see §4b) |
| GET | `/api/stream` | SSE, each `data:` line is `{"type", "case_id", "event"}` |

### Partner page (partner chosen by `partner_id` in the URL; no auth for the demo)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/partners` | | `[manifest + {active, staff, open_jobs, total_jobs, technicians:[{tech_id,name,skills}]}]`, one per partner (staff "Partners" page) |
| GET | `/api/partner/{partner_id}` | | partner profile from manifest |
| GET | `/api/partner/{partner_id}/jobs` | | `[JobSummary]` |
| GET | `/api/partner/{partner_id}/jobs/{case_id}` | | `JobDetail` (only consented context!) |
| POST | `/api/partner/{partner_id}/jobs/{case_id}/accept` | | `JobDetail` |
| POST | `/api/partner/{partner_id}/jobs/{case_id}/decline` | `{reason}` | `JobDetail` |
| GET | `/api/partner/{partner_id}/technicians` | | `[{tech_id, name, skills[], phone_e164, free_slots:[{start,end}]}]` |
| POST | `/api/partner/{partner_id}/jobs/{case_id}/slots` | `{tech_id?, slots:[{start,end}]}` (no tech_id → auto-assign, see §4a) | `JobDetail` |
| POST | `/api/partner/{partner_id}/jobs/{case_id}/complete` | multipart: `notes`, `photo`, `invoice` (PDF) | `JobDetail` |

### Files and demo
`GET /files/{document_id}`; `POST /demo/scenarios` (reset + 9 realistic demo cases built through the real services; units 4b and 2a stay empty; also `POST /demo/reset?scenarios=1`); `POST /demo/reset`, `POST /demo/skip-to-tomorrow`, `POST /demo/trigger/{name}` (only when `DEMO_MODE=1`).

### Shapes
```jsonc
// CaseSummary
{"case_id":"case_0001","type":"repair.heating","title":"No heating – central boiler","status":"scheduled",
 "priority":"urgent","unit_id":"unit_4b","address":"Musterstraße 12, 52062 Aachen",
 "partner":{"partner_id":"heizung-schmidt","name":"Heizung Schmidt GmbH"},"updated_at":"..."}

// CaseDetail = CaseSummary + 
{"reporters":[{"contact_id":"c_202","name":"Luka","unit_id":"unit_4b","relation":"reporter"}],
 "asset":{"make":"Vaillant","model":"ecoTEC plus VC 206/5-5","error_code":"F.28","error_label":"Ignition failed: no flame at start-up"},
 "cost_bearer":"landlord","estimated_cost_eur":250,"approval":{"required":false,"rule":"auto-approved: < €500"},
 "slot":{"start":"...","end":"..."},
 "zero_forms":{"prefilled":["address","unit","floor","boiler model","..."],"tenant_inputs":["voice note","tap: Überall kalt","tap: consent"]},
 "ranking":[{"partner_id":"heizung-schmidt","name":"...","score":0.86,"reasons":["Vaillant-certified","free tomorrow 8–10"]}],
 "consents":[{"partner_id":"heizung-schmidt","data_shared":["name","phone","address","photos"],"given_at":"...","channel":"whatsapp","purpose":"heating repair visit"}],
 "documents":[{"document_id":"doc_0003","kind":"invoice","filename":"RE-2026-1187.pdf","url":"/files/doc_0003","extracted":{}}],
 "events":[{"ts":"...","actor":"debye","kind":"case.created","summary":"Case opened from Luka's voice note"}],
 "messages":[{"ts":"...","direction":"in","contact":"Luka","text":"Die Heizung ist kalt …","media":[]}],
 "result":null}

// CaseSummary also carries error_code + error_label (plain-English meaning, e.g. "Water pressure too low").
// JobSummary / JobDetail (partner view): status, address, floor, asset, error_code, error_label, photos[], tenant contact
// (only if consented), proposed slots, confirmed slot, documents
```

## 4a. Technician flow

The partner's dispatcher assigns one of the partner's technicians. The tenant then picks a slot from that technician's free time, and the technician confirms on their phone page.

**Data.** `technicians` in `data/seed.json` (table `technician`): `{id, partner_id, name, phone_e164, skills[], busy[]}`. Heizung Schmidt has Tom Schmidt (`tech_tom`; heating, Vaillant), Ali Yilmaz (`tech_ali`; heating, plumbing) and Jana Krüger (`tech_jana`; heating). Wärme Wagner and Heiztechnik Grün have one each. In the seed, the busy windows are relative to the demo day (`{day: 1, window: "08-10"}`, where day 1 = tomorrow); they become absolute ISO intervals when seeding. All contacts have `language: "en"` (English is the default).

**Free slots.** The next 3 days (tomorrow … +3), windows 08–10 / 10–12 / 14–16 (Europe/Berlin), minus busy intervals. A confirmed job is added to the technician's busy list.

**Flow and statuses.**
1. Partner accepts → `accepted`.
2. The dispatcher picks a technician (`GET …/technicians`) and proposes 2–3 of that technician's free slots: `POST …/slots {tech_id, slots}` → `slots_proposed`. `case.data.technician = {tech_id, name}`, and the event `technician.assigned` is "Dispatcher assigned Tom Schmidt". An explicit `tech_id` returns 409 if the technician belongs to another partner or isn't free in a slot.
   **Without `tech_id`** the dispatcher auto-assigns the best technician who is free in every proposed slot. Ranking: skill matching the asset brand (Vaillant), then the trade (heating), then the fewest booked jobs. The event is "Dispatcher auto-assigned Tom Schmidt (Vaillant-skilled, heating trade, free in all proposed slots)", with `data.auto = true`. 409 if nobody is free in all slots. A partner without technicians keeps the old flow (no technician, `confirm_slot` → `scheduled`).
   Slot labels follow the tenant's language: `en` "Tomorrow 8–10", "Today 14–16", "Sat 21 Nov, 8–10". The agent uses them as-is. `notify_tenant("slots_proposed", {slots, partner_name, technician_name})`.
3. The tenant picks on WhatsApp: `services.confirm_slot(case_id, n)` (1-based, unchanged) → **`awaiting_technician`** (only `scheduled` if no technician was assigned). Event `slot.confirmed`.
4. The technician confirms: `POST /api/tech/{tech_id}/jobs/{case_id}/confirm` → **`scheduled`**. This books the slot on the technician's calendar, records the event `technician.confirmed` "Technician Tom Schmidt confirmed Sat 08:00–10:00" (actor `partner`), and calls `notify.notify_tenant(case_id, "technician_confirmed", {technician_name, tech_id, slot:{start, end, label}})`. The label is the one the tenant picked. 409 if the tenant hasn't picked yet or the job is already confirmed.

Status lifecycle: `new → approval_pending → requested → accepted → slots_proposed → awaiting_technician → scheduled → completed → invoiced → closed` (side states `rejected`, `partner_declined`, `reopened`).

**Technician phone page API** (technician chosen by `tech_id` in the URL; no auth for the demo):
| Method | Path | Returns |
|---|---|---|
| GET | `/api/tech/{tech_id}` | `{tech_id, name, partner_id, partner_name, skills}` |
| GET | `/api/tech/{tech_id}/jobs` | `[JobSummary + chosen_slot + needs_confirmation]`, only jobs assigned to this technician |
| GET | `/api/tech/{tech_id}/jobs/{case_id}` | `JobDetail` (consented context only) + `chosen_slot:{start,end}` + `needs_confirmation` |
| POST | `/api/tech/{tech_id}/jobs/{case_id}/confirm` | same as GET detail, status `scheduled` |

**Shapes.** CaseSummary, CaseDetail, JobSummary and JobDetail get `technician: {tech_id, name} | null`. Technician jobs: `slot` (= `chosen_slot`) is the slot the tenant picked. The close-case result payload `service_job.technician` is the technician's name.

Services (additive): `get_technicians(partner_id)`, `get_technician(tech_id)`, `technician_confirm(case_id, tech_id)`; `propose_slots(case_id, partner_id, slots, tech_id=None)`.

## 4b. Staff approval (APPROVAL_POLICY)

A reltix staff member confirms **every** job before the partner is contacted, so no technician goes out for nothing.

- `APPROVAL_POLICY=always` (default): approval is always required. `APPROVAL_POLICY=limit` keeps the old rule (auto-approve below the framework contract's `auto_approve_limit_eur`, €500 for Heizung Schmidt).
- After consent, `services.dispatch_job(case_id, partner_id)` does **not** send the job. The case goes to **`approval_pending`** (`case.data.pending_partner_id` = the partner), the event `approval.required` is recorded ("Waiting for staff approval: Heizung Schmidt GmbH, est. €263"), and `rules.RuleViolation("approval_required")` is raised. Calling it again records no second event. The caller (agent) tells the tenant that staff are approving. The backend sends no extra `approval_pending` notification, so the tenant doesn't get it twice.
- `POST /api/staff/cases/{id}/approve` (optional body `{staff_name}`, default the seeded property manager Anna Becker) records `approval.granted` (actor `staff`, "Anna Becker approved the job for Heizung Schmidt GmbH (est. €263)", `data.approved_by`), dispatches the job (`job.sent`, status `requested`; the partner sees it only now), and calls `notify_tenant(case_id, "approval_granted", {partner_name, dispatched})`.
- `POST /api/staff/cases/{id}/reject {reason, staff_name?}` is only allowed in `approval_pending` (409 otherwise). It sets status **`rejected`**, records `approval.rejected` ("Anna Becker rejected the job for Heizung Schmidt GmbH: <reason>"), and calls `notify_tenant(case_id, "approval_rejected", {partner_name, reason})`. The partner is never contacted. A rejected case doesn't count as open, so a new report opens a new case.
- Partner JobDetail `approval` = `{granted, granted_by, granted_at, text}`. `text` is partner-facing: "Approved by reltix staff (Anna Becker)", or "Approved automatically (…)" under `APPROVAL_POLICY=limit`. Use it instead of a hard-coded "approved automatically".
- CaseDetail `approval` (the staff card) also has `granted_by`, `granted_at`, `rejected_by`: `{required, granted, rejected, reason, rule, amount_eur, partner:{partner_id,name}, suggested_technician:{tech_id,name}|null, suggested_slot:{start,end,label}|null}`. `partner` is the pending partner, because `case.partner` stays null until the job is sent. The suggestion (only while `approval_pending`) is what auto-assign would pick for the earliest free slot, e.g. Tom Schmidt, "Tomorrow 8–10"; it's informational and nothing is booked. With `always` the rule is "reltix staff approve every job before the partner is contacted". The old status `awaiting_approval` is gone; use `approval_pending`.

## 4c. Diagnosis and trade routing

The knowledge base is `data/diagnosis/no_hot_water.json` ([docs/diagnosis.md](diagnosis.md)). The agent diagnoses and backend-core stores the result and routes on it.

- `open_case(..., trade=None, diagnosis=None)` stores both on the case (`case.data.trade`, `case.data.diagnosis`). A diagnosis records the event `diagnosis.recorded` "Debye diagnosed: Shower mixer / thermostatic cartridge faulty (85%)". `set_case_diagnosis(case_id, diagnosis, trade=None)` does the same when the agent concludes after the case was opened.
- **Input** (agent): `{cause_id, confidence, reasoning, questions_asked}`, plus optional `label`, `outcome`, `trade`, `estimated_cost_eur`, `estimated_saving_eur`. Missing fields are filled from the KB cause (`cause_id`). `confidence` may be 0–1 or a percentage (85 → 0.85). `questions_asked` items may be `{question, answer}` dicts or plain strings or KB question ids (an id is replaced by the KB wording, answer null).
- **Stored and returned** `CaseDetail.diagnosis` = `{cause_id, label, confidence (0–1), reasoning, questions_asked:[{question, answer}], outcome (self_help|caretaker|technician|utility|emergency), trade, estimated_cost_eur, estimated_saving_eur}`.
  - `estimated_cost_eur` comes from the KB cause and also becomes the case estimate when there's no partner yet.
  - `estimated_saving_eur` is only set for self_help/caretaker: the cause's `estimated_saving_eur` if the KB has one, else €180 (a typical plumber visit).
- **Closed without a partner:** `close_without_partner(case_id, resolution, note)` (resolution `self_help` | `caretaker` | `utility`). Status `closed`, `case.partner` null. Event `case.closed` "Closed without a technician (self-help), saved ~€180: tank reheated". CaseSummary and CaseDetail get `resolution` and `saving_eur`. 409 (RuleViolation `has_partner`) if a partner is already on the job; use `close_case` then.
- Without an explicit trade, the trade comes from the case type (`repair.heating` → `heating`).
- **Ranking** (`rank_partners`) filters by trade: partners whose manifest `capabilities.trades` include the case trade. Plumbing → Heizung Schmidt (its `plumbing` trade); electrical → Elektro Klein. The brand bonus (Vaillant-certified) applies only to heating; for other trades its weight goes to the trade match (reason "plumbing trade").
- **Technician pre-selection** (auto-assign and the approval-card suggestion) only considers technicians with the trade skill when the partner has any. Plumbing → Ali Yilmaz; electrical → Marco Klein. For heating the Vaillant skill still comes first.
- **Caretaker outcome:** `notify_caretaker(case_id, reason)` stores `case.data.caretaker = {contact_id, name, phone_e164, reason, notified_at}` and records the event `caretaker.notified` "Caretaker Peter Wolf notified: top up system pressure". No partner and no approval; the case status is unchanged.
- **Shapes:** CaseSummary gets `trade`, `resolution`, `saving_eur`. CaseDetail gets `trade`, `diagnosis`, `caretaker`, `resolution`, `saving_eur`. The staff approval card (`CaseDetail.approval`, §4b) gets `trade` and `diagnosis: {cause_id, label, confidence, reasoning, outcome, estimated_cost_eur}`.
- **Agent call sequence:**
  - technician outcome: `open_case(..., trade, diagnosis)` → consent → `dispatch_job` (approval_pending)
  - self-help: `open_case(..., diagnosis)` → `close_without_partner(case_id, "self_help", note)` once the tenant confirms it worked (or right away)
  - caretaker: `open_case(..., diagnosis)` → `notify_caretaker(case_id, reason)` → later `close_without_partner(case_id, "caretaker")`

## 5. Definition of done for any PR
- Runs locally from a clean clone with the README steps.
- Golden path (technical-plan intro) still works with `scripts/simulate.py`.
- No secrets committed; real phone numbers only in `data/seed.local.json`.
