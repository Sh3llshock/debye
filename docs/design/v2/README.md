# Debye design v2: navy and white

The user's feedback on v1 was "no purple, it looks too AI". This folder has a new mascot and two alternative versions of the main screens, so the user can pick one. Both versions use the same data as v1 (case_0001, unit 4b, Heizung Schmidt, Lena's WhatsApp thread).

Figma: [Debye (AI assistant)](https://www.figma.com/design/vW4cyvW7lLOjYGOg7Ul1iJ), pages **Mascot v2**, **Version A – unslop** and **Version B – impeccable**.

| Folder | What it is |
|---|---|
| [`mascot/`](mascot/) | New mascot: a small navy apartment house with window eyes and a brass wrench |
| [`version-a-unslop/`](version-a-unslop/) | The screens redone by following [unslop](https://github.com/heydamir/unslop) |
| [`version-b-impeccable/`](version-b-impeccable/) | The screens redone by following [impeccable](https://github.com/pbakaus/impeccable) |

Each version folder has `tokens.json`, so the frontend can switch by mapping one file into `frontend/src/theme.ts`.

## A and B side by side

| | A · unslop | B · impeccable |
|---|---|---|
| Shell | White 256 px sidebar with text nav, light grey page | Navy 72 px icon rail, tinted ground, white work areas |
| Colour | Neutral ink greys; navy is the only accent | Navy shell plus one blue for actions, state colours only where they mean something |
| Type | IBM Plex Sans, plus Plex Mono for IDs, times and figures | Public Sans only, tabular figures |
| Depth | Cards with a hairline and a 1 px shadow | Borders only, no shadows |
| Case page | Cards: timeline + WhatsApp, then case facts and unit, then partner choice and documents | Work areas: a lifecycle line across the top, then activity and conversation, plus an inspector panel on the right |
| Signature | Brass key tag for case IDs | The lifecycle line (Reported → … → Closed), also used in each row of the cases list |
| Rich element | Invoice drawn as a paper document; boiler display photo | The lifecycle line; the week grid for picking visit times |
| Approval | A calm card above the stats | An amber group inside the cases table |

## Mascot v2

Generated with the OpenAI Images API (`gpt-image-1.5` on the EU endpoint). It took 7 images: 3 concepts (house, caretaker, speech bubble), then 4 edits of the house. Palette: navy `#0F2444`, white, and brass `#D9A441` on the wrench only.

| File | Use |
|---|---|
| `debye-mascot-whatsapp-1024.png` | WhatsApp profile picture (upper body on white, fits the circle crop) |
| `debye-mascot-avatar-256.png` | Small avatar used in the UI (the Figma component "Debye avatar v2") |
| `debye-mascot.png` | Main character, 1024 square, transparent |
| `debye-mascot-fullbody.png` | Full body, 1024×1536, for the pitch slide and empty states |
| `debye-mascot-waving.png` / `-thumbs-up.png` / `-thinking.png` | Onboarding / repair done / working on it |
| `mascot-overview.png` | All of them side by side |
