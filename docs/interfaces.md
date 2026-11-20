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
def get_unit_context(unit_id: str) -> dict            # property, unit, assets, lease, open cases (JSON-safe)
def find_open_case_for_asset(asset_id: str) -> Case | None
def open_case(reporter_contact_id: str, type: str, priority: str, summary: str,
              symptoms: str, error_code: str | None, asset_id: str | None) -> Case
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
# event ∈ "job_accepted" | "slots_proposed" (data.slots=[{start,end,label}]) | "job_completed"
#        | "approval_granted" | "partner_declined"
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
| POST | `/api/staff/cases/{case_id}/approve` | `CaseDetail` |
| GET | `/api/stream` | SSE, each `data:` line is `{"type", "case_id", "event"}` |

### Partner page (partner chosen by `partner_id` in the URL; no auth for the demo)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/partner/{partner_id}` | | partner profile from manifest |
| GET | `/api/partner/{partner_id}/jobs` | | `[JobSummary]` |
| GET | `/api/partner/{partner_id}/jobs/{case_id}` | | `JobDetail` (only consented context!) |
| POST | `/api/partner/{partner_id}/jobs/{case_id}/accept` | | `JobDetail` |
| POST | `/api/partner/{partner_id}/jobs/{case_id}/decline` | `{reason}` | `JobDetail` |
| POST | `/api/partner/{partner_id}/jobs/{case_id}/slots` | `{slots:[{start,end}]}` | `JobDetail` |
| POST | `/api/partner/{partner_id}/jobs/{case_id}/complete` | multipart: `notes`, `photo`, `invoice` (PDF) | `JobDetail` |

### Files and demo
`GET /files/{document_id}`; `POST /demo/reset`, `POST /demo/skip-to-tomorrow`, `POST /demo/trigger/{name}` (only when `DEMO_MODE=1`).

### Shapes
```jsonc
// CaseSummary
{"case_id":"case_0001","type":"repair.heating","title":"No heating – central boiler","status":"scheduled",
 "priority":"urgent","unit_id":"unit_4b","address":"Musterstraße 12, 52062 Aachen",
 "partner":{"partner_id":"heizung-schmidt","name":"Heizung Schmidt GmbH"},"updated_at":"..."}

// CaseDetail = CaseSummary + 
{"reporters":[{"contact_id":"c_202","name":"Lena Hoffmann","unit_id":"unit_4b","relation":"reporter"}],
 "asset":{"make":"Vaillant","model":"ecoTEC plus VC 206/5-5","error_code":"F.28","error_label":"Ignition failed: no flame at start-up"},
 "cost_bearer":"landlord","estimated_cost_eur":250,"approval":{"required":false,"rule":"auto-approved: < €500"},
 "slot":{"start":"...","end":"..."},
 "zero_forms":{"prefilled":["address","unit","floor","boiler model","..."],"tenant_inputs":["voice note","tap: Überall kalt","tap: consent"]},
 "ranking":[{"partner_id":"heizung-schmidt","name":"...","score":0.86,"reasons":["Vaillant-certified","free tomorrow 8–10"]}],
 "consents":[{"partner_id":"heizung-schmidt","data_shared":["name","phone","address","photos"],"given_at":"...","channel":"whatsapp","purpose":"heating repair visit"}],
 "documents":[{"document_id":"doc_0003","kind":"invoice","filename":"RE-2026-1187.pdf","url":"/files/doc_0003","extracted":{}}],
 "events":[{"ts":"...","actor":"debye","kind":"case.created","summary":"Case opened from Lena's voice note"}],
 "messages":[{"ts":"...","direction":"in","contact":"Lena Hoffmann","text":"Die Heizung ist kalt …","media":[]}],
 "result":null}

// CaseSummary also carries error_code + error_label (plain-English meaning, e.g. "Water pressure too low").
// JobSummary / JobDetail (partner view): status, address, floor, asset, error_code, error_label, photos[], tenant contact
// (only if consented), proposed slots, confirmed slot, documents
```

## 5. Definition of done for any PR
- Runs locally from a clean clone with the README steps.
- Golden path (technical-plan intro) still works with `scripts/simulate.py`.
- No secrets committed; real phone numbers only in `data/seed.local.json`.
