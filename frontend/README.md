# Debye frontend

Vite + React + TypeScript + Tailwind. Two web pages (residents only use WhatsApp):

| Route | Who |
|---|---|
| `/staff`, `/staff/cases/:caseId`, `/staff/units/:unitId` | reltix staff (centrix stand-in) |
| `/partner/:partnerId`, `/partner/:partnerId/jobs/:caseId` | partner dispatcher: accept, pick a technician and his free slots |
| `/tech/:techId`, `/tech/:techId/jobs/:caseId` | technician phone page: his jobs, big Confirm button |

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
3. ▶ "Luka picks a slot" → job is scheduled.
4. Partner: Mark as done with photo + PDF → invoice is extracted.
5. ▶ "Luka confirms" → case closed, result payload and invoice land on unit 4b.

`case_0002` waits for approval (€620 > €500) to demo the Approve button.

## Code map

- `src/theme.ts`: **every** colour, font, size, radius and spacing. Wired into `tailwind.config.ts`. Change design here only.
- `src/api/types.ts`: shapes from `docs/interfaces.md` §4. `client.ts`: typed REST client. `mock.ts`: fixtures.
- `src/lib/stream.ts`: one shared `EventSource('/api/stream')`; pages patch the case in place and refetch (debounced).
- `src/components/case/CasePanels.tsx`: service line, zero-forms strip, activity, conversation, inspector, partner choice table.
- `src/lib/lifecycle.ts`: the service line stations (staff and partner) and status texts. `src/lib/errors.ts`: error codes explained meaning first (`error_label` from the API, else a local map).
- Design: Version B (impeccable), `docs/design/v2/version-b-impeccable/`. Mascot: `docs/design/v2/mascot/` (downscaled copies in `public/mascot/`).
- `src/pages/*`: route pages.

## Stage text size

Add `?stage=1` to any URL to make all text 10 % bigger for the projector (`?stage=1.2` = 120 %, `?stage=0` = back to 100 %). The setting is remembered in the browser. With `VITE_DEMO=1` the demo panel also has A− / A+ buttons (90–140 %). Only text scales; layout spacing stays the same.

## Language

EN / DE toggle at the top right of every page (English by default, remembered in localStorage; `?lang=de` also works). UI copy lives in `src/lib/de.ts`, keyed by the English text; wrap new copy in `t('…')`. API data and WhatsApp messages are shown as sent.
