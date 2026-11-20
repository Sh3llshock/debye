# Debye frontend

Vite + React + TypeScript + Tailwind. Two web pages (residents only use WhatsApp):

| Route | Who |
|---|---|
| `/staff`, `/staff/cases/:caseId`, `/staff/units/:unitId` | reltix staff (centrix stand-in) |
| `/partner/:partnerId`, `/partner/:partnerId/jobs/:caseId` | heating installer (phone-friendly) |

`/` redirects to `/staff`; `/partner` redirects to `/partner/heizung-schmidt`.

## Run

```bash
cd frontend
npm install
npm run dev            # needs the backend on :8000 (proxy for /api, /files, /demo)
npm run dev:fixtures   # no backend: in-browser fake API + demo controls (.env.fixtures)
npm run build          # → frontend/dist, served by FastAPI at /
```

Env flags (Vite, build-time):

- `VITE_USE_FIXTURES=1`: use `src/api/mock.ts` instead of HTTP. State is kept in `localStorage` and synced across tabs, so a staff tab and a partner tab behave like one backend.
- `VITE_DEMO=1`: show the hidden demo panel (tiny dot bottom-right, or press `d`): Reset, Skip to tomorrow and, with fixtures, "▶ next step" which plays the resident's WhatsApp side of the golden path.
- `DEBYE_BACKEND` (dev server only): proxy target, default `http://localhost:8000`.

## Golden path with fixtures

1. `/staff` → demo panel → press ▶ five times (voice note, tap, neighbour, ranking, consent). Case is sent to Heizung Schmidt.
2. `/partner/heizung-schmidt` → open the job → Accept → tap 2 slots → Send.
3. ▶ "Lena picks a slot" → job is scheduled.
4. Partner: Mark as done with photo + PDF → invoice is extracted.
5. ▶ "Lena confirms" → case closed, result payload and invoice land on unit 4b.

`case_0002` waits for approval (€620 > €500) to demo the Approve button.

## Code map

- `src/theme.ts`: **every** colour, font, size, radius and spacing. Wired into `tailwind.config.ts`. Change design here only.
- `src/api/types.ts`: shapes from `docs/interfaces.md` §4. `client.ts`: typed REST client. `mock.ts`: fixtures.
- `src/lib/stream.ts`: one shared `EventSource('/api/stream')`; pages patch the case in place and refetch (debounced).
- `src/components/case/CasePanels.tsx`: staff case panels (case card, timeline, WhatsApp thread, ranking, consent, documents, result).
- `src/pages/*`: route pages.
