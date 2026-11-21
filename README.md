# Debye (AI assistant)

**reltix's AI assistant in the resident's WhatsApp, plugged into centrix.** A resident sends one voice note about a broken heater; Debye opens the case, gets consent, sends the job to the right heating installer's partner page, books a slot with the resident on WhatsApp, and files the invoice on the unit. Staff follow everything live on their own page. Zero calls, zero forms.

Built for the reltix track "Plug a Partner into centrix" at MAIN Maastricht 2026.

## Docs

| File | What it is |
|---|---|
| [docs/interfaces.md](docs/interfaces.md) | Team contracts: who owns which files, Python and REST interfaces, v2 product decisions |
| [docs/technical-plan.md](docs/technical-plan.md) | Architecture, data model, channels, agent, partner layer, work packages |
| [docs/connector-spec.md](docs/connector-spec.md) | The partner connector spec (deliverable): manifest, lifecycle, transports, consent |
| [docs/pitch-plan.md](docs/pitch-plan.md) | Flow choice, demo story, 3-minute pitch, Q&A prep |
| [partners/](partners/) | One connector manifest per partner (3 heating installers, 1 internet provider) |
| [data/seed.json](data/seed.json) | Seed data for the centrix mock |

## Status

Planning done; build in progress. Work is tracked as GitHub issues with milestones:
M1 WhatsApp round-trip → M2 Golden path end to end → M3 Hosted V1 → M4 Feature freeze → M5 Submit.

## Run

Step-by-step guide (backend, web pages, demo data, WhatsApp, public link, emails, voice, tests):
**[docs/running.md](docs/running.md)**

Quick start:

```bash
cp .env.example .env                       # set OPENAI_API_KEY, LLM_PROVIDER=openai, DEMO_MODE=1
cd backend && pip install -r requirements.txt
cd ../frontend && npm ci && npm run build
cd ../backend && uvicorn app.main:app --port 8000
curl -X POST http://localhost:8000/demo/scenarios   # demo data
```

Then open http://localhost:8000/staff, /partner/heizung-schmidt/new and /tenant.

## Assumptions

- Tenant phone numbers come from the lease; tenants opt in to WhatsApp at onboarding.
- The property manager has framework agreements with local trades, including price lists and a per-job auto-approval limit.
- Heating repairs are the landlord's cost.
- Boiler make, model and service history come from the PM's maintenance records.
- centrix is mocked with seeded data (no reltix API exists for the hackathon).
