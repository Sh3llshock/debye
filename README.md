# Debye

**reltix's assistant in the resident's WhatsApp, plugged into centrix.** A tenant sends one voice note about a broken heater; Debye opens the case, gets consent, books the right heating installer (also on WhatsApp), and files the invoice on the unit. Zero calls, zero forms.

Built for the reltix track "Plug a Partner into centrix" at MAIN Maastricht 2026.

## Docs

| File | What it is |
|---|---|
| [docs/technical-plan.md](docs/technical-plan.md) | Architecture, data model, channels, agent, partner layer, work packages |
| [docs/connector-spec.md](docs/connector-spec.md) | The partner connector spec (deliverable): manifest, lifecycle, transports, consent |
| [docs/pitch-plan.md](docs/pitch-plan.md) | Flow choice, demo story, 3-minute pitch, Q&A prep |
| [partners/](partners/) | One connector manifest per partner (3 heating installers, 1 internet provider) |
| [data/seed.json](data/seed.json) | Seed data for the centrix mock |

## Status

Planning done; build in progress. Work is tracked as GitHub issues with milestones:
M1 WhatsApp round-trip → M2 Golden path end to end → M3 Hosted V1 → M4 Feature freeze → M5 Submit.

## Run (once the backend exists)

```bash
cp .env.example .env            # fill in keys
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload
cloudflared tunnel --url http://localhost:8000   # webhook URL for Meta
```

## Assumptions

- Tenant phone numbers come from the lease; tenants opt in to WhatsApp at onboarding.
- The property manager has framework agreements with local trades, including price lists and a per-job auto-approval limit.
- Heating repairs are the landlord's cost.
- Boiler make, model and service history come from the PM's maintenance records.
- centrix is mocked with seeded data (no reltix API exists for the hackathon).
